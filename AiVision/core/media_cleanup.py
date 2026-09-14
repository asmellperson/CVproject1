"""共享媒体生命周期：业务提供数据库引用，文件边界和保留/容量策略统一处理。"""
from __future__ import annotations

import datetime
import heapq
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from AiVision.core.logger import logger

MEDIA_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".mp4"})
GIB = 1024 ** 3
CLEANUP_BATCH_SIZE = 500
QUOTA_GRACE_SECONDS = 10 * 60


@dataclass
class MediaCleanupStats:
    removed_files: int = 0
    removed_bytes: int = 0
    removed_records: int = 0
    skipped_unsafe_paths: int = 0
    failed_files: int = 0


@dataclass(frozen=True)
class MediaRecord:
    id: int
    created_at: datetime.datetime
    paths: tuple[str, ...]


class MediaReferences(Protocol):
    """仅声明业务的引用、按时间分页和事务删除，不承担文件清理或调度。"""

    media_directories: tuple[str, ...]

    def iter_records(self, before: datetime.datetime) -> Iterator[MediaRecord]: ...

    def referenced_paths(self, paths: list[Path]) -> set[str]: ...

    def delete_record(self, record: MediaRecord, remove_file: Callable[[str], bool]) -> int: ...


class MediaCleaner:
    def __init__(self, data_path: str | Path, *, retention_days: int, max_bytes: int,
                 references: Sequence[MediaReferences]):
        self.data_path = Path(data_path).expanduser().resolve()
        self.retention_days = max(1, int(retention_days))
        self.max_bytes = max(0, int(max_bytes))
        self._primary_references = tuple(references)
        self._references = self._primary_references
        self._lock = threading.Lock()
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.set_additional_references(())

    def set_additional_references(self, references: Sequence[MediaReferences]) -> None:
        with self._lock:
            combined = (*self._primary_references, *references)
            directories = [name for source in combined for name in source.media_directories]
            if len(set(directories)) != len(directories) or any(
                Path(name).name != name or name in {"", ".", ".."} for name in directories
            ):
                raise ValueError("媒体目录必须是互不重叠的根目录下一级目录")
            self._references = combined

    def cleanup(self, now: datetime.datetime | None = None) -> MediaCleanupStats:
        stats = MediaCleanupStats()
        if not self._lock.acquire(blocking=False):
            logger.info("[MediaCleanup] 上一次媒体清理仍在运行，本轮跳过")
            return stats
        try:
            cleanup_now = now or datetime.datetime.now()
            cutoff = cleanup_now - datetime.timedelta(days=self.retention_days)
            for source in self._references:
                for record in source.iter_records(cutoff):
                    self._delete_record(source, record, stats)
            for _, source, path in self._orphan_candidates(cutoff.timestamp()):
                self._remove_file(path, stats, source.media_directories)
            self._enforce_size_limit(stats, cleanup_now)
            self._remove_empty_directories()
            logger.info(
                f"[MediaCleanup] 清理完成 records={stats.removed_records} files={stats.removed_files} "
                f"freed_mb={stats.removed_bytes / 1024 / 1024:.2f} "
                f"unsafe={stats.skipped_unsafe_paths} failed={stats.failed_files}"
            )
        except Exception as exc:
            logger.error(f"[MediaCleanup] 清理失败：{type(exc).__name__}")
        finally:
            self._lock.release()
        return stats

    def _delete_record(self, source: MediaReferences, record: MediaRecord, stats: MediaCleanupStats) -> None:
        # 业务事务内先安全删文件，事务提交成功后才累计已删除记录数。
        count = source.delete_record(record, lambda path: self._remove_file(path, stats, source.media_directories))
        stats.removed_records += count

    def _record_candidates(self, source: MediaReferences, before: datetime.datetime):
        for record in source.iter_records(before):
            yield record.created_at.timestamp(), source, record

    def _orphan_candidates(self, before_timestamp: float):
        candidates = sorted(self._media_files(), key=self._safe_mtime)
        for offset in range(0, len(candidates), CLEANUP_BATCH_SIZE):
            batch = candidates[offset:offset + CLEANUP_BATCH_SIZE]
            referenced: set[str] = set()
            owners = {}
            for source in self._references:
                paths = [path for path in batch if self._is_managed_path(path, source.media_directories)]
                if paths:
                    referenced.update(source.referenced_paths(paths))
                    owners.update((path, source) for path in paths)
            for path in batch:
                modified_at = self._safe_mtime(path)
                if str(path) not in referenced and modified_at < before_timestamp:
                    yield modified_at, owners[path], path

    def _enforce_size_limit(self, stats: MediaCleanupStats, now: datetime.datetime) -> None:
        if self.max_bytes <= 0:
            return
        total_bytes = self._media_size()
        if total_bytes <= self.max_bytes:
            return
        cutoff = now - datetime.timedelta(seconds=QUOTA_GRACE_SECONDS)
        # 所有业务和孤儿文件共用容量，按时间归并；每种数据库仍自行分页。
        candidates = heapq.merge(
            *(self._record_candidates(source, cutoff) for source in self._references),
            self._orphan_candidates(cutoff.timestamp()), key=lambda candidate: candidate[0],
        )
        for _, source, candidate in candidates:
            if total_bytes <= self.max_bytes:
                break
            before_bytes = stats.removed_bytes
            if isinstance(candidate, MediaRecord):
                self._delete_record(source, candidate, stats)
            else:
                self._remove_file(candidate, stats, source.media_directories)
            total_bytes -= stats.removed_bytes - before_bytes
        if total_bytes > self.max_bytes:
            logger.warning(
                "[MediaCleanup] 仍超过容量上限，保留近期或无法安全删除的媒体 "
                f"current_gb={total_bytes / GIB:.2f} max_gb={self.max_bytes / GIB:.2f}"
            )

    def _remove_file(self, path: str | Path, stats: MediaCleanupStats, directories: tuple[str, ...]) -> bool:
        removed, size = self._remove_managed_file(path, stats, directories)
        if removed and size:
            stats.removed_files += 1
            stats.removed_bytes += size
        return removed

    def _remove_managed_file(self, raw_path: str | Path, stats: MediaCleanupStats,
                             directories: tuple[str, ...] | None = None) -> tuple[bool, int]:
        try:
            raw = Path(raw_path).expanduser().absolute()
            path = raw.resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            stats.failed_files += 1
            return False, 0
        if not self._is_managed_path(raw, directories) or path.suffix.lower() not in MEDIA_EXTENSIONS:
            stats.skipped_unsafe_paths += 1
            logger.warning(f"[MediaCleanup] 拒绝删除媒体目录外或不安全的文件: {raw}")
            return False, 0
        try:
            if not path.exists():
                return True, 0
            if not path.is_file():
                stats.failed_files += 1
                logger.warning(f"[MediaCleanup] 媒体路径不是普通文件: {path}")
                return False, 0
            size = path.stat().st_size
            path.unlink()
            return True, size
        except OSError as exc:
            stats.failed_files += 1
            logger.warning(f"[MediaCleanup] 删除媒体失败 path={path}: {exc}")
            return False, 0

    def _is_managed_path(self, path: Path, directories: tuple[str, ...] | None = None) -> bool:
        allowed = directories if directories is not None else tuple(
            name for source in self._references for name in source.media_directories
        )
        try:
            relative = path.relative_to(self.data_path)
            if not relative.parts or relative.parts[0] not in allowed:
                return False
            resolved = path.resolve().relative_to(self.data_path)
            if not resolved.parts or resolved.parts[0] not in allowed:
                return False
            current = path
            while current != self.data_path:
                if current.is_symlink():
                    return False
                current = current.parent
            return True
        except (OSError, RuntimeError, ValueError):
            return False

    def _managed_entries(self):
        for source in self._references:
            for name in source.media_directories:
                directory = self.data_path / name
                if not self._is_managed_path(directory) or not directory.is_dir():
                    continue
                yield directory
                for path in directory.rglob("*"):
                    if self._is_managed_path(path):
                        yield path

    def _media_files(self) -> list[Path]:
        files = []
        for path in self._managed_entries():
            try:
                if not path.is_symlink() and path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                    files.append(path)
            except OSError:
                continue
        return files

    def _media_size(self) -> int:
        total = 0
        for path in self._media_files():
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def _remove_empty_directories(self) -> None:
        directories = sorted(
            (path for path in self._managed_entries() if path.is_dir()),
            key=lambda path: len(path.parts), reverse=True,
        )
        for path in directories:
            try:
                path.rmdir()
            except OSError:
                continue

    @staticmethod
    def _safe_mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return float("inf")
