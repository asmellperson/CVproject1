# 文件说明：实现资源清理相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""AiVision 报警图片、视频与数据库记录的一致性清理。"""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass
from pathlib import Path

from AiVision.core.db import session_scope
from AiVision.core.logger import logger
from .orm import AiViolationImage


MEDIA_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".mp4"})
GIB = 1024 ** 3
CLEANUP_BATCH_SIZE = 500
QUOTA_GRACE_SECONDS = 10 * 60


# 功能：一次报警图片清理的统计结果；输入与输出详见下方说明
# 参数：
#   - `removed_files`（int）：`removed_files` 对应的业务输入值
#   - `removed_bytes`（int）：`removed_bytes` 对应的业务输入值
#   - `removed_records`（int）：`removed_records` 对应的业务输入值
#   - `skipped_unsafe_paths`（int）：`skipped_unsafe_paths` 对应的业务输入值
#   - `failed_files`（int）：`failed_files` 对应的业务输入值
# 返回：MediaCleanupStats；返回新建的 `MediaCleanupStats` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::cleanup` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class MediaCleanupStats:
    """一次报警图片清理的统计结果。"""

    removed_files: int = 0
    removed_bytes: int = 0
    removed_records: int = 0
    skipped_unsafe_paths: int = 0
    failed_files: int = 0


# 功能：按保留天数和容量上限清理报警媒体及关联数据库记录；输入与输出详见下方说明
# 参数：
#   - `data_path`（str | Path）：`data_path` 对应的业务输入值
#   - `retention_days`（int）：`retention_days` 对应的业务输入值
#   - `max_bytes`（int）：`max_bytes` 对应的业务输入值
#   - `session_scope_factory`（未显式标注）：`session_scope_factory` 对应的业务输入值；默认值为 `session_scope`
# 返回：ViolationMediaCleaner；返回新建的 `ViolationMediaCleaner` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::__init__` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ViolationMediaCleaner:
    """按保留天数和容量上限清理报警媒体及关联数据库记录。"""

    # 功能：初始化或配置 `__init__` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `data_path`（str | Path）：`data_path` 对应的业务输入值
    #   - `retention_days`（int）：`retention_days` 对应的业务输入值
    #   - `max_bytes`（int）：`max_bytes` 对应的业务输入值
    #   - `session_scope_factory`（未显式标注）：`session_scope_factory` 对应的业务输入值；默认值为 `session_scope`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path(data_path).expanduser().resolve`、`Path(data_path).expanduser`、`Path`、`max`、`int`、`threading.Lock`、`self.data_path.mkdir`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
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

    # 功能：删除或清理 `cleanup` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `now`（datetime.datetime | None）：`now` 对应的业务输入值；默认值为 `None`
    # 返回：MediaCleanupStats；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::_delete_old` 调用本符号
    #   - 内部调用：`MediaCleanupStats`、`self._lock.acquire`、`logger.info`、`datetime.datetime.now`、`datetime.timedelta`、`self._delete_expired_records`、`self._delete_expired_orphans`、`cutoff.timestamp`、`self._enforce_size_limit`、`cleanup_now.timestamp`
    #          等共 13 个调用。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
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

    # 功能：删除或清理 `_delete_expired_records` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `cutoff`（datetime.datetime）：`cutoff` 对应的业务输入值
    #   - `stats`（MediaCleanupStats）：`stats` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::cleanup` 调用本符号
    #   - 内部调用：`self._session_scope`、`session.query(AiViolationImage).filter`、`session.query`、`query.filter`、`query.order_by(AiViolationImage.create_time.asc(),
    #          AiViolationImage.id.asc()).limit(CLEANUP_BATCH_SIZE).all`、`query.order_by(AiViolationImage.create_time.asc(),
    #          AiViolationImage.id.asc()).limit`、`query.order_by`、`AiViolationImage.create_time.asc`、`AiViolationImage.id.asc`、`int`
    #          等共 13 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务。
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

    # 功能：删除或清理 `_delete_expired_orphans` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `cutoff_timestamp`（float）：`cutoff_timestamp` 对应的业务输入值
    #   - `stats`（MediaCleanupStats）：`stats` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::cleanup` 调用本符号
    #   - 内部调用：`self._media_files`、`path.stat`、`candidates.append`、`range`、`len`、`self._referenced_paths`、`str`、`self._remove_managed_file`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：实现 `_enforce_size_limit` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `stats`（MediaCleanupStats）：`stats` 对应的业务输入值
    #   - `now_timestamp`（float）：`now_timestamp` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::cleanup` 调用本符号
    #   - 内部调用：`self._media_size`、`self._session_scope`、`session.query`、`query.filter`、`query.order_by(AiViolationImage.create_time.asc(),
    #          AiViolationImage.id.asc()).limit(CLEANUP_BATCH_SIZE).all`、`query.order_by(AiViolationImage.create_time.asc(),
    #          AiViolationImage.id.asc()).limit`、`query.order_by`、`AiViolationImage.create_time.asc`、`AiViolationImage.id.asc`、`int`
    #          等共 17 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务；会向日志系统输出运行或异常信息。
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

    # 功能：删除或清理 `_delete_quota_orphans` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `total_bytes`（int）：`total_bytes` 对应的业务输入值
    #   - `quota_cutoff`（float）：`quota_cutoff` 对应的业务输入值
    #   - `stats`（MediaCleanupStats）：`stats` 对应的业务输入值
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_enforce_size_limit` 调用本符号
    #   - 内部调用：`sorted`、`self._media_files`、`range`、`len`、`self._referenced_paths`、`str`、`path.stat`、`self._remove_managed_file`、`max`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：实现 `_referenced_paths` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `paths`（list[Path]）：`paths` 对应的业务输入值
    # 返回：set[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_expired_orphans`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_quota_orphans` 调用本符号
    #   - 内部调用：`str`、`self._session_scope`、`session.query(AiViolationImage.image_path).filter(AiViolationImage.image_path.in_(raw_paths)).all`、`session.query(AiViolationImage.image_path).filter`、`session.query`、`AiViolationImage.image_path.in_`、`session.query(AiViolationImage.video_path).filter(AiViolationImage.video_path.in_(raw_paths)).all`、`session.query(AiViolationImage.video_path).filter`、`AiViolationImage.video_path.in_`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：删除或清理 `_remove_optional_managed_file` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `raw_path`（str | Path | None）：`raw_path` 对应的业务输入值
    #   - `stats`（MediaCleanupStats）：`stats` 对应的业务输入值
    # 返回：tuple[bool, int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_expired_records`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_enforce_size_limit` 调用本符号
    #   - 内部调用：`self._remove_managed_file`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _remove_optional_managed_file(
        self,
        raw_path: str | Path | None,
        stats: MediaCleanupStats,
    ) -> tuple[bool, int]:
        if not raw_path:
            return True, 0
        return self._remove_managed_file(raw_path, stats)

    # 功能：删除或清理 `_remove_managed_file` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `raw_path`（str | Path）：`raw_path` 对应的业务输入值
    #   - `stats`（MediaCleanupStats）：`stats` 对应的业务输入值
    # 返回：tuple[bool, int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_expired_records`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_expired_orphans`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_enforce_size_limit`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_quota_orphans` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`Path(raw_path).expanduser().resolve`、`Path(raw_path).expanduser`、`Path`、`path.is_relative_to`、`logger.warning`、`path.exists`、`path.is_file`、`path.stat`、`path.unlink`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息。
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

    # 功能：实现 `_media_files` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[Path]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_expired_orphans`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_quota_orphans`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_media_size` 调用本符号
    #   - 内部调用：`self.data_path.rglob`、`path.is_symlink`、`path.is_file`、`path.suffix.lower`、`files.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：实现 `_media_size` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_enforce_size_limit` 调用本符号
    #   - 内部调用：`self._media_files`、`path.stat`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _media_size(self) -> int:
        total = 0
        for path in self._media_files():
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    # 功能：删除或清理 `_remove_empty_directories` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::cleanup` 调用本符号
    #   - 内部调用：`sorted`、`self.data_path.rglob`、`path.is_dir`、`len`、`path.rmdir`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：实现 `_safe_mtime` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `path`（Path）：目标路径
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`path.stat`、`float`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _safe_mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return float("inf")
