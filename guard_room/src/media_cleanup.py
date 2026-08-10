"""门卫室报警图片、视频与事件索引的统一清理。"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


GIB = 1024 ** 3
MEDIA_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mov"})
MANAGED_DIRECTORY_NAMES = ("alarms", "alarm_clips", "vehicle_clips")
QUOTA_GRACE_SECONDS = 10 * 60
_CLEANUP_LOCK = threading.Lock()


@dataclass
class AlarmMediaCleanupStats:
    """一次门卫室报警证据清理的结果。"""

    removed_files: int = 0
    removed_bytes: int = 0
    pruned_events: int = 0
    skipped_unsafe_paths: int = 0
    failed_files: int = 0
    remaining_bytes: int = 0
    skipped_busy: bool = False


@dataclass(frozen=True)
class _MediaFile:
    path: Path
    modified_at: float
    size: int


def cleanup_alarm_media(
    output_dir: str | Path,
    *,
    retention_days: int,
    max_bytes: int,
    now: float | None = None,
) -> AlarmMediaCleanupStats:
    """按保存天数和容量上限清理报警图片、视频及其事件索引。"""
    stats = AlarmMediaCleanupStats()
    if not _CLEANUP_LOCK.acquire(blocking=False):
        stats.skipped_busy = True
        return stats

    try:
        cleanup_now = time.time() if now is None else float(now)
        output_root = Path(output_dir).expanduser().resolve()
        managed_roots = tuple(
            (output_root / name).resolve()
            for name in MANAGED_DIRECTORY_NAMES
        )
        media = _collect_media(managed_roots, stats)
        cutoff = cleanup_now - max(1, int(retention_days)) * 86400

        removed_paths: set[Path] = set()
        for item in media:
            if item.modified_at < cutoff and _remove_file(item, stats):
                removed_paths.add(item.path)

        survivors = [item for item in media if item.path not in removed_paths and item.path.exists()]
        total_bytes = sum(item.size for item in survivors)
        limit = max(0, int(max_bytes))
        if limit > 0 and total_bytes > limit:
            quota_cutoff = cleanup_now - QUOTA_GRACE_SECONDS
            for item in sorted(survivors, key=lambda candidate: candidate.modified_at):
                if total_bytes <= limit:
                    break
                if item.modified_at >= quota_cutoff:
                    continue
                if _remove_file(item, stats):
                    removed_paths.add(item.path)
                    total_bytes = max(0, total_bytes - item.size)

        _prune_event_index(output_root, managed_roots, stats)
        _remove_empty_directories(managed_roots)
        stats.remaining_bytes = _directory_size(managed_roots)
        return stats
    finally:
        _CLEANUP_LOCK.release()


def event_media_available(event) -> bool:
    """判断内存报警事件的已落盘证据是否仍然存在。"""
    image_path = getattr(event, "image_path", None)
    if image_path and not Path(image_path).exists():
        return False
    video_path = getattr(event, "video_path", None)
    if video_path and not Path(video_path).exists():
        return False
    return True


def _collect_media(
    managed_roots: Iterable[Path],
    stats: AlarmMediaCleanupStats,
) -> list[_MediaFile]:
    media: list[_MediaFile] = []
    for root in managed_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            try:
                if path.is_symlink():
                    stats.skipped_unsafe_paths += 1
                    continue
                if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    stats.skipped_unsafe_paths += 1
                    continue
                file_stat = resolved.stat()
                media.append(_MediaFile(resolved, file_stat.st_mtime, file_stat.st_size))
            except OSError:
                stats.failed_files += 1
    return media


def _remove_file(item: _MediaFile, stats: AlarmMediaCleanupStats) -> bool:
    try:
        item.path.unlink(missing_ok=True)
        stats.removed_files += 1
        stats.removed_bytes += item.size
        return True
    except OSError:
        stats.failed_files += 1
        return False


def _prune_event_index(
    output_root: Path,
    managed_roots: tuple[Path, ...],
    stats: AlarmMediaCleanupStats,
) -> None:
    index_path = output_root / "alarm_events.json"
    if not index_path.exists():
        return
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stats.failed_files += 1
        return
    if not isinstance(payload, list):
        stats.failed_files += 1
        return

    retained: list[dict] = []
    for event in payload:
        if not isinstance(event, dict):
            stats.pruned_events += 1
            continue
        references = [
            path
            for path in (
                _managed_reference(event.get("image_path"), managed_roots, stats),
                _managed_reference(event.get("video_path"), managed_roots, stats),
            )
            if path is not None
        ]
        if references and any(not path.exists() for path in references):
            stats.pruned_events += 1
            for path in references:
                if not path.exists():
                    continue
                try:
                    size = path.stat().st_size
                    path.unlink()
                    stats.removed_files += 1
                    stats.removed_bytes += size
                except OSError:
                    stats.failed_files += 1
            continue
        retained.append(event)

    if len(retained) == len(payload):
        return
    temporary_path = index_path.with_suffix(".json.tmp")
    try:
        temporary_path.write_text(
            json.dumps(retained, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(index_path)
    except OSError:
        stats.failed_files += 1
        temporary_path.unlink(missing_ok=True)


def _managed_reference(
    raw_path,
    managed_roots: tuple[Path, ...],
    stats: AlarmMediaCleanupStats,
) -> Path | None:
    if not raw_path:
        return None
    try:
        path = Path(str(raw_path)).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        stats.skipped_unsafe_paths += 1
        return None
    if not any(path.is_relative_to(root) for root in managed_roots):
        stats.skipped_unsafe_paths += 1
        return None
    return path


def _directory_size(managed_roots: Iterable[Path]) -> int:
    total = 0
    for root in managed_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            try:
                if not path.is_symlink() and path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                    total += path.stat().st_size
            except OSError:
                continue
    return total


def _remove_empty_directories(managed_roots: Iterable[Path]) -> None:
    for root in managed_roots:
        if not root.exists():
            continue
        directories = sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for path in directories:
            try:
                path.rmdir()
            except OSError:
                continue
