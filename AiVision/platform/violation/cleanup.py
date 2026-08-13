"""AiVision 报警图片、视频与数据库记录的一致性清理。"""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass
from pathlib import Path

from core.db import session_scope
from core.logger import logger
from .orm import AiViolationImage


MEDIA_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".mp4"})
GIB = 1024 ** 3
CLEANUP_BATCH_SIZE = 500
QUOTA_GRACE_SECONDS = 10 * 60


@dataclass
class MediaCleanupStats:
    """一次报警图片清理的统计结果。"""

    removed_files: int = 0
    removed_bytes: int = 0
    removed_records: int = 0
    skipped_unsafe_paths: int = 0
    failed_files: int = 0


class ViolationMediaCleaner:
    """按保留天数和容量上限清理报警媒体及关联数据库记录。"""

    def __init__(
        self,
        data_path: str | Path,
        *,
        retention_days: int,
        max_bytes: int,
        session_scope_factory=session_scope,
    ):
        self.data_path = Path(data_path).expanduser().resolve()
        self.retention_days = max(1, int(retention_days))
        self.max_bytes = max(0, int(max_bytes))
        self._session_scope = session_scope_factory
        self._lock = threading.Lock()
        self.data_path.mkdir(parents=True, exist_ok=True)

    def cleanup(self, now: datetime.datetime | None = None) -> MediaCleanupStats:
        stats = MediaCleanupStats()
        if not self._lock.acquire(blocking=False):
            logger.info("[ViolationWriter] 上一次报警图片清理仍在运行，本轮跳过")
            return stats
        try:
            cleanup_now = now or datetime.datetime.now()
            cutoff = cleanup_now - datetime.timedelta(days=self.retention_days)
            self._delete_expired_records(cutoff, stats)
            self._delete_expired_orphans(cutoff.timestamp(), stats)
            self._enforce_size_limit(stats, cleanup_now.timestamp())
            self._remove_empty_directories()
            logger.info(
                "[ViolationWriter] 报警图片清理完成 "
                f"records={stats.removed_records} files={stats.removed_files} "
                f"freed_mb={stats.removed_bytes / 1024 / 1024:.2f} "
                f"unsafe={stats.skipped_unsafe_paths} failed={stats.failed_files}"
            )
        except Exception as exc:
            logger.warning(f"[ViolationWriter] 清理失败: {exc}")
        finally:
            self._lock.release()
        return stats

    def _delete_expired_records(
        self,
        cutoff: datetime.datetime,
        stats: MediaCleanupStats,
    ) -> None:
        cursor: tuple[datetime.datetime, int] | None = None
        while True:
            with self._session_scope() as session:
                query = session.query(AiViolationImage).filter(
                    AiViolationImage.create_time < cutoff
                )
                if cursor is not None:
                    cursor_time, cursor_id = cursor
                    query = query.filter(
                        (AiViolationImage.create_time > cursor_time)
                        | (
                            (AiViolationImage.create_time == cursor_time)
                            & (AiViolationImage.id > cursor_id)
                        )
                    )
                rows = (
                    query.order_by(
                        AiViolationImage.create_time.asc(),
                        AiViolationImage.id.asc(),
                    )
                    .limit(CLEANUP_BATCH_SIZE)
                    .all()
                )
                if not rows:
                    return
                cursor = (rows[-1].create_time, int(rows[-1].id))
                for row in rows:
                    image_removed, image_bytes = self._remove_managed_file(row.image_path, stats)
                    video_removed, video_bytes = self._remove_optional_managed_file(
                        row.video_path,
                        stats,
                    )
                    if not image_removed or not video_removed:
                        continue
                    session.delete(row)
                    stats.removed_records += 1
                    removed_bytes = image_bytes + video_bytes
                    if removed_bytes:
                        stats.removed_files += int(image_bytes > 0) + int(video_bytes > 0)
                        stats.removed_bytes += removed_bytes

    def _delete_expired_orphans(
        self,
        cutoff_timestamp: float,
        stats: MediaCleanupStats,
    ) -> None:
        candidates: list[Path] = []
        for path in self._media_files():
            try:
                if path.stat().st_mtime >= cutoff_timestamp:
                    continue
            except OSError:
                stats.failed_files += 1
                continue
            candidates.append(path)

        for offset in range(0, len(candidates), CLEANUP_BATCH_SIZE):
            batch = candidates[offset:offset + CLEANUP_BATCH_SIZE]
            referenced = self._referenced_paths(batch)
            for path in batch:
                if str(path) in referenced:
                    continue
                removed, removed_bytes = self._remove_managed_file(path, stats)
                if removed and removed_bytes:
                    stats.removed_files += 1
                    stats.removed_bytes += removed_bytes

    def _enforce_size_limit(
        self,
        stats: MediaCleanupStats,
        now_timestamp: float,
    ) -> None:
        if self.max_bytes <= 0:
            return
        total_bytes = self._media_size()
        if total_bytes <= self.max_bytes:
            return

        cursor: tuple[datetime.datetime, int] | None = None
        while total_bytes > self.max_bytes:
            with self._session_scope() as session:
                query = session.query(AiViolationImage)
                if cursor is not None:
                    cursor_time, cursor_id = cursor
                    query = query.filter(
                        (AiViolationImage.create_time > cursor_time)
                        | (
                            (AiViolationImage.create_time == cursor_time)
                            & (AiViolationImage.id > cursor_id)
                        )
                    )
                rows = (
                    query.order_by(
                        AiViolationImage.create_time.asc(),
                        AiViolationImage.id.asc(),
                    )
                    .limit(CLEANUP_BATCH_SIZE)
                    .all()
                )
                if not rows:
                    break
                cursor = (rows[-1].create_time, int(rows[-1].id))
                for row in rows:
                    if total_bytes <= self.max_bytes:
                        break
                    if row.create_time.timestamp() >= now_timestamp - QUOTA_GRACE_SECONDS:
                        continue
                    image_removed, image_bytes = self._remove_managed_file(row.image_path, stats)
                    video_removed, video_bytes = self._remove_optional_managed_file(
                        row.video_path,
                        stats,
                    )
                    if not image_removed or not video_removed:
                        continue
                    session.delete(row)
                    stats.removed_records += 1
                    removed_bytes = image_bytes + video_bytes
                    total_bytes = max(0, total_bytes - removed_bytes)
                    if removed_bytes:
                        stats.removed_files += int(image_bytes > 0) + int(video_bytes > 0)
                        stats.removed_bytes += removed_bytes

        if total_bytes > self.max_bytes:
            total_bytes = self._delete_quota_orphans(
                total_bytes,
                now_timestamp - QUOTA_GRACE_SECONDS,
                stats,
            )

        if total_bytes > self.max_bytes:
            logger.warning(
                "[ViolationWriter] 报警图片目录仍超过容量上限；"
                "可能存在近期文件或无法删除的文件 "
                f"current_gb={total_bytes / GIB:.2f} max_gb={self.max_bytes / GIB:.2f}"
            )

    def _delete_quota_orphans(
        self,
        total_bytes: int,
        quota_cutoff: float,
        stats: MediaCleanupStats,
    ) -> int:
        candidates = sorted(self._media_files(), key=self._safe_mtime)
        for offset in range(0, len(candidates), CLEANUP_BATCH_SIZE):
            if total_bytes <= self.max_bytes:
                break
            batch = candidates[offset:offset + CLEANUP_BATCH_SIZE]
            referenced = self._referenced_paths(batch)
            for path in batch:
                if total_bytes <= self.max_bytes:
                    break
                if str(path) in referenced:
                    continue
                try:
                    if path.stat().st_mtime >= quota_cutoff:
                        continue
                except OSError:
                    stats.failed_files += 1
                    continue
                removed, removed_bytes = self._remove_managed_file(path, stats)
                if removed and removed_bytes:
                    stats.removed_files += 1
                    stats.removed_bytes += removed_bytes
                    total_bytes = max(0, total_bytes - removed_bytes)
        return total_bytes

    def _referenced_paths(self, paths: list[Path]) -> set[str]:
        raw_paths = [str(path) for path in paths]
        with self._session_scope() as session:
            image_paths = {
                str(image_path)
                for (image_path,) in (
                    session.query(AiViolationImage.image_path)
                    .filter(AiViolationImage.image_path.in_(raw_paths))
                    .all()
                )
            }
            video_paths = {
                str(video_path)
                for (video_path,) in (
                    session.query(AiViolationImage.video_path)
                    .filter(AiViolationImage.video_path.in_(raw_paths))
                    .all()
                )
                if video_path
            }
            return image_paths | video_paths

    def _remove_optional_managed_file(
        self,
        raw_path: str | Path | None,
        stats: MediaCleanupStats,
    ) -> tuple[bool, int]:
        if not raw_path:
            return True, 0
        return self._remove_managed_file(raw_path, stats)

    def _remove_managed_file(
        self,
        raw_path: str | Path,
        stats: MediaCleanupStats,
    ) -> tuple[bool, int]:
        try:
            path = Path(raw_path).expanduser().resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            stats.failed_files += 1
            return False, 0
        if not path.is_relative_to(self.data_path):
            stats.skipped_unsafe_paths += 1
            logger.warning(f"[ViolationWriter] 拒绝删除 DATA_PATH 外的文件: {path}")
            return False, 0
        try:
            if not path.exists():
                return True, 0
            if not path.is_file():
                stats.failed_files += 1
                logger.warning(f"[ViolationWriter] 报警图片路径不是普通文件: {path}")
                return False, 0
            size = path.stat().st_size
            path.unlink()
            return True, size
        except OSError as exc:
            stats.failed_files += 1
            logger.warning(f"[ViolationWriter] 删除报警图片失败 path={path}: {exc}")
            return False, 0

    def _media_files(self) -> list[Path]:
        files: list[Path] = []
        for path in self.data_path.rglob("*"):
            try:
                if path.is_symlink():
                    continue
                if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
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
            (path for path in self.data_path.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
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
