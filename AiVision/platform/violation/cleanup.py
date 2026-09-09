"""
AiVision 报警图片、视频与数据库记录的一致性清理。

setting.py:
    告警媒体保留七天
    媒体容量上限10GB
    清理频率：每60分钟一次
    系统启动：立即清理一次
"""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass
from pathlib import Path

from AiVision.core.db import session_scope
from AiVision.core.logger import logger
from .orm import AiAlarmEvent

# 这四类是告警媒体
MEDIA_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".mp4"})
GIB = 1024 ** 3
# 每批最多处理500条
CLEANUP_BATCH_SIZE = 500
# 容量超限时保护10分钟
QUOTA_GRACE_SECONDS = 10 * 60
# 旧类型目录仅作为遗留告警文件清理范围，不用于推导新告警类型或归属。
ALARM_MEDIA_DIRECTORIES = tuple(str(value) for value in range(1, 11)) + ("alarm_clips",)

# 记录当前清理做了多少事情
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
        # setting七天
        self.retention_days = max(1, int(retention_days))
        # 容量10GB
        self.max_bytes = max(0, int(max_bytes))
        self._session_scope = session_scope_factory
        self._lock = threading.Lock()
        self.data_path.mkdir(parents=True, exist_ok=True)

    def cleanup(self, now: datetime.datetime | None = None) -> MediaCleanupStats:
        """
        清理入口
        """
        # 建立清理统计对象
        stats = MediaCleanupStats()
        # 如果锁现在正被另一次清理拿着，直接跳过
        if not self._lock.acquire(blocking=False):
            logger.info("[ViolationWriter] 上一次报警图片清理仍在运行，本轮跳过")
            return stats
        try:
            # 计算七天前的时间点
            cleanup_now = now or datetime.datetime.now()
            cutoff = cleanup_now - datetime.timedelta(days=self.retention_days)
            # 1、清理数据库里超过七天的告警
            self._delete_expired_records(cutoff, stats)
            # 2、清理磁盘上超过七天，但数据库已经不引用的孤儿文件
            self._delete_expired_orphans(cutoff.timestamp(), stats)
            # 3、检查当前媒体容量是不是超过10GB
            self._enforce_size_limit(stats, cleanup_now.timestamp())
            # 4、把已经没有文件的空目录删掉
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
        """
        数据库清理操作
        """
        # cursor记：上一批处理到哪个时间哪个id
        cursor: tuple[datetime.datetime, int] | None = None
        while True:
            with self._session_scope() as session:
                # 先查七天前的数据
                query = session.query(AiAlarmEvent).filter(
                    AiAlarmEvent.create_time < cutoff
                )
                if cursor is not None:
                    # 游标分页
                    cursor_time, cursor_id = cursor
                    query = query.filter(
                        (AiAlarmEvent.create_time > cursor_time)
                        | (
                            (AiAlarmEvent.create_time == cursor_time)
                            & (AiAlarmEvent.id > cursor_id)
                        )
                    )
                # 每批最多500条
                rows = (
                    query.order_by(
                        AiAlarmEvent.create_time.asc(),
                        AiAlarmEvent.id.asc(),
                    )
                    .limit(CLEANUP_BATCH_SIZE)
                    .all()
                )
                # 没有了就结束
                if not rows:
                    return
                # 保存下一批Cursor
                cursor = (rows[-1].create_time, int(rows[-1].id))
                for row in rows:
                    # 删除一条告警时先删图片再删视频（_remove_managed_file():文件不存在，被视为“已经删除成功”)
                    image_removed, image_bytes = self._remove_managed_file(row.image_path, stats)
                    video_removed, video_bytes = self._remove_optional_managed_file(
                        row.video_path,
                        stats,
                    )
                    # 图片和视频只要有一个删除失败，这条记录就不删
                    if not image_removed or not video_removed:
                        continue
                    # 文件处理后才删ORM
                    session.delete(row)
                    # 统计移除记录+1
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
        """
        orphans:孤儿文件： 磁盘上存在，但是数据库没有任何AiAlarmEvent.image_path或者video_path指向它
        """
        candidates: list[Path] = []
        # 先扫描所有媒体
        for path in self._media_files():
            try:
                # 文件系统最后修改时间mtime（mtime超过七天作为候选，刚创建3天不管）
                if path.stat().st_mtime >= cutoff_timestamp:
                    continue
            except OSError:
                stats.failed_files += 1
                continue
            candidates.append(path)

        for offset in range(0, len(candidates), CLEANUP_BATCH_SIZE):
            batch = candidates[offset:offset + CLEANUP_BATCH_SIZE]
            # 去数据库检查这500个文件路径中哪些还会出现在image_path,video_path
            referenced = self._referenced_paths(batch)
            for path in batch:
                # 数据库还在引用不删，数据库没人引用真正删除
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
        """容量控制"""
        # 如果ALARM_MEDIA_MAX_GB=0则容量控制关闭
        if self.max_bytes <= 0:
            return
        # 统计DATA_PATH告警目录里所有jpg/jpeg/png/mp4
        total_bytes = self._media_size()
        # 小于10GB什么都不做
        if total_bytes <= self.max_bytes:
            return

        cursor: tuple[datetime.datetime, int] | None = None
        while total_bytes > self.max_bytes:
            with self._session_scope() as session:
                query = session.query(AiAlarmEvent)
                if cursor is not None:
                    cursor_time, cursor_id = cursor
                    query = query.filter(
                        (AiAlarmEvent.create_time > cursor_time)
                        | (
                            (AiAlarmEvent.create_time == cursor_time)
                            & (AiAlarmEvent.id > cursor_id)
                        )
                    )
                # 最早发生告警的最先删除
                rows = (
                    query.order_by(
                        AiAlarmEvent.create_time.asc(),
                        AiAlarmEvent.id.asc(),
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
                    # 最近10分钟保护
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
            # 如果数据库告警都处理完了，还是大于10GB就去找没有数据库引用的孤儿媒体
            total_bytes = self._delete_quota_orphans(
                total_bytes,
                now_timestamp - QUOTA_GRACE_SECONDS,
                stats,
            )
        # 还是超过10GB，宁可短暂超限，也不无脑删除
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
        """判断这批数据有没有被数据库引用"""
        raw_paths = [str(path) for path in paths]
        with self._session_scope() as session:
            image_paths = {
                str(image_path)
                for (image_path,) in (
                    session.query(AiAlarmEvent.image_path)
                    .filter(AiAlarmEvent.image_path.in_(raw_paths))
                    .all()
                )
            }
            video_paths = {
                str(video_path)
                for (video_path,) in (
                    session.query(AiAlarmEvent.video_path)
                    .filter(AiAlarmEvent.video_path.in_(raw_paths))
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
        """没有视频需要删除直接返回True，0"""
        if not raw_path:
            return True, 0
        return self._remove_managed_file(raw_path, stats)

    def _remove_managed_file(
        self,
        raw_path: str | Path,
        stats: MediaCleanupStats,
    ) -> tuple[bool, int]:
        """把某个文件unlink掉"""
        try:
            raw = Path(raw_path).expanduser().absolute()
            path = raw.resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            stats.failed_files += 1
            return False, 0
        # 只能删DATA_PATH里的文件（文件删除边界保护）
        if not self._is_managed_path(raw) or path.suffix.lower() not in MEDIA_EXTENSIONS:
            stats.skipped_unsafe_paths += 1
            logger.warning(f"[ViolationWriter] 拒绝删除告警媒体目录外或不安全的文件: {raw}")
            return False, 0
        try:
            if not path.exists():
                return True, 0
            # 如果路径不是普通文件，不会直接删
            if not path.is_file():
                stats.failed_files += 1
                logger.warning(f"[ViolationWriter] 报警图片路径不是普通文件: {path}")
                return False, 0
            # 删除前先取文件大小
            size = path.stat().st_size
            # 执行删除操作
            path.unlink()
            return True, size
        except OSError as exc:
            stats.failed_files += 1
            logger.warning(f"[ViolationWriter] 删除报警图片失败 path={path}: {exc}")
            return False, 0

    def _media_files(self) -> list[Path]:
        """到底扫描哪些文件"""
        files: list[Path] = []
        for path in self._managed_entries():
            try:
                # 符号链接直接跳过
                if path.is_symlink():
                    continue
                # 只管指定后缀的文件
                if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                    files.append(path)
            except OSError:
                continue
        return files

    def _is_managed_path(self, path: Path) -> bool:
        """DATA_PATH 边界内还须命中告警目录白名单，并拒绝所有层级的符号链接。"""
        try:
            relative = path.relative_to(self.data_path)
            if not relative.parts or relative.parts[0] not in ALARM_MEDIA_DIRECTORIES:
                return False
            resolved = path.resolve().relative_to(self.data_path)
            if not resolved.parts or resolved.parts[0] not in ALARM_MEDIA_DIRECTORIES:
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
        for name in ALARM_MEDIA_DIRECTORIES:
            directory = self.data_path / name
            if not self._is_managed_path(directory) or not directory.is_dir():
                continue
            yield directory
            for path in directory.rglob("*"):
                if self._is_managed_path(path):
                    yield path

    def _media_size(self) -> int:
        """容量统计：DATA_PATH告警目录下被_media_files()识别出的jpg/jpeg/png/mp4总大小"""
        total = 0
        for path in self._media_files():
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def _remove_empty_directories(self) -> None:
        """按路径深度清楚空目录"""
        directories = sorted(
            (path for path in self._managed_entries() if path.is_dir()),
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
        """按文件修改时间来排序，从最久到最近的顺序"""
        try:
            return path.stat().st_mtime
        except OSError:
            return float("inf")
