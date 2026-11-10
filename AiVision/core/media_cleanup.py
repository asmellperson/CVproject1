"""多个业务共用的媒体保留时间、容量告警与安全删除流程。

业务通过 MediaReferences 提供记录、引用和事务删除，清理器只在声明的媒体子目录工作。
只删除超过保留期的记录和无引用文件；容量超限仅告警，不提前删除保留期内证据。
本模块会实际删除文件，调用方应在受控生命周期中调度，而不是在包导入时执行。
"""
from __future__ import annotations

import datetime
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from AiVision.core.logger import logger

MEDIA_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".mp4"})
GIB = 1024 ** 3
CLEANUP_BATCH_SIZE = 500


class _CleanupCancelled(Exception):
    """在文件操作与业务事务之间结束本轮维护，避免关停等待全盘扫描。"""


@dataclass
class MediaCleanupStats:
    """本轮清理计数，包括文件/字节/记录删除数，以及不安全路径和失败文件数。"""
    removed_files: int = 0
    removed_bytes: int = 0
    removed_records: int = 0
    skipped_unsafe_paths: int = 0
    failed_files: int = 0
    cancelled: bool = False


@dataclass(frozen=True)
class MediaRecord:
    """业务交给清理器的不可变记录摘要：主键、发生时间及该记录引用的媒体路径。"""
    id: int
    created_at: datetime.datetime
    paths: tuple[str, ...]


class MediaReferences(Protocol):
    """仅声明业务的引用、按时间分页和事务删除，不承担文件清理或调度。"""

    media_directories: tuple[str, ...]

    def iter_records(self, before: datetime.datetime) -> Iterator[MediaRecord]:
        """按时间升序分批提供 before 之前的记录，供保留时间清理。"""
        ...

    def referenced_paths(self, paths: list[Path]) -> set[str]:
        """返回候选文件中仍被本业务数据库引用的路径，避免把有效证据认作孤儿文件。"""
        ...

    def delete_record(self, record: MediaRecord, remove_file: Callable[[str], bool]) -> int:
        """在业务事务内重新核验记录，通过 remove_file 删除证据，返回实际删除的记录数。"""
        ...


class MediaCleaner:
    """协调业务引用与磁盘文件的清理器，使用非阻塞锁避免同一实例重复运行。"""
    def __init__(self, data_path: str | Path, *, retention_days: int, max_bytes: int,
                 references: Sequence[MediaReferences]):
        """规范化媒体根目录和保留参数，保存主要引用源并创建目录；构造时不执行删除。"""
        self.data_path = Path(data_path).expanduser().resolve()
        self.retention_days = max(1, int(retention_days))
        self.max_bytes = max(0, int(max_bytes))
        self._primary_references = tuple(references)
        self._references = self._primary_references
        self._lock = threading.Lock()
        self._stop_requested = threading.Event()
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.set_additional_references(())

    def request_stop(self) -> None:
        """不获取清理锁，让运行中的扫描也能收到退出通知。"""
        self._stop_requested.set()

    def reset_stop(self) -> None:
        """上一轮清理已退出后，由平台启动流程恢复定期维护。"""
        self._stop_requested.clear()

    def _check_cancelled(self) -> None:
        if self._stop_requested.is_set():
            raise _CleanupCancelled()

    def set_additional_references(self, references: Sequence[MediaReferences]) -> None:
        """合并固定与附加引用源，要求各源独占互不重名的根目录下一级媒体目录。"""
        with self._lock:
            combined = (*self._primary_references, *references)
            directories = [name for source in combined for name in source.media_directories]
            if len(set(directories)) != len(directories) or any(
                Path(name).name != name or name in {"", ".", ".."} for name in directories
            ):
                raise ValueError("媒体目录必须是互不重叠的根目录下一级目录")
            self._references = combined

    def cleanup(self, now: datetime.datetime | None = None) -> MediaCleanupStats:
        """执行过期清理和容量检查；已有清理在运行则跳过。

        Args:
            now: 用于计算保留截止时间的本地时间，默认当前时间，便于确定性验证。

        Returns:
            MediaCleanupStats: 本轮已执行操作的计数；异常记录后返回部分统计，不表示全量成功。
        """
        stats = MediaCleanupStats()
        if not self._lock.acquire(blocking=False):
            logger.info("[MediaCleanup] 上一次媒体清理仍在运行，本轮跳过")
            return stats
        try:
            self._check_cancelled()
            cleanup_now = now or datetime.datetime.now()
            cutoff = cleanup_now - datetime.timedelta(days=self.retention_days)
            for source in self._references:
                self._check_cancelled()
                for record in source.iter_records(cutoff):
                    # 当前记录的文件删除与数据库事务必须完整结束，再响应取消。
                    self._check_cancelled()
                    self._delete_record(source, record, stats)
                    self._check_cancelled()
            for _, source, path in self._orphan_candidates(cutoff.timestamp()):
                self._check_cancelled()
                self._remove_file(path, stats, source.media_directories)
            self._check_cancelled()
            self._report_capacity()
            self._remove_empty_directories()
            logger.info(
                f"[MediaCleanup] 清理完成 records={stats.removed_records} files={stats.removed_files} "
                f"freed_mb={stats.removed_bytes / 1024 / 1024:.2f} "
                f"unsafe={stats.skipped_unsafe_paths} failed={stats.failed_files}"
            )
        except _CleanupCancelled:
            stats.cancelled = True
            logger.info(
                f"[MediaCleanup] 收到退出通知，已结束本轮清理 "
                f"records={stats.removed_records} files={stats.removed_files}"
            )
        except Exception as exc:
            logger.error(f"[MediaCleanup] 清理失败：{type(exc).__name__}")
        finally:
            self._lock.release()
        return stats

    def _delete_record(self, source: MediaReferences, record: MediaRecord, stats: MediaCleanupStats) -> None:
        # 业务事务内先安全删文件，事务提交成功后才累计已删除记录数。
        """交给业务源在事务内重验并删除记录，只有成功返回后累计数据库删除数。"""
        count = source.delete_record(record, lambda path: self._remove_file(path, stats, source.media_directories))
        stats.removed_records += count

    def _orphan_candidates(self, before_timestamp: float):
        """分批核对磁盘文件的数据库引用，仅产生早于截止时间且无引用的媒体候选。"""
        candidates = sorted(self._media_files(), key=self._safe_mtime)
        for offset in range(0, len(candidates), CLEANUP_BATCH_SIZE):
            self._check_cancelled()
            batch = candidates[offset:offset + CLEANUP_BATCH_SIZE]
            referenced: set[str] = set()
            owners = {}
            for source in self._references:
                self._check_cancelled()
                paths = [path for path in batch if self._is_managed_path(path, source.media_directories)]
                if paths:
                    referenced.update(source.referenced_paths(paths))
                    owners.update((path, source) for path in paths)
            for path in batch:
                modified_at = self._safe_mtime(path)
                if str(path) not in referenced and modified_at < before_timestamp:
                    yield modified_at, owners[path], path

    def _report_capacity(self) -> None:
        """保留期限优先于容量阈值，超限提示扩容而不丢弃期限内证据。"""
        if self.max_bytes <= 0:
            return
        total_bytes = self._media_size()
        self._check_cancelled()
        if total_bytes > self.max_bytes:
            logger.warning(
                "[MediaCleanup] 媒体容量超过告警阈值，请检查存储空间；保留期内媒体不会提前删除 "
                f"current_gb={total_bytes / GIB:.2f} threshold_gb={self.max_bytes / GIB:.2f}"
            )

    def _remove_file(self, path: str | Path, stats: MediaCleanupStats, directories: tuple[str, ...]) -> bool:
        """执行受限删除并累计已释放的非零文件字节，返回文件是否已不存在。"""
        removed, size = self._remove_managed_file(path, stats, directories)
        if removed and size:
            stats.removed_files += 1
            stats.removed_bytes += size
        return removed

    def _remove_managed_file(self, raw_path: str | Path, stats: MediaCleanupStats,
                             directories: tuple[str, ...] | None = None) -> tuple[bool, int]:
        """校验根目录、扩展名与普通文件属性后删除，返回成功标志和字节数；已缺失视为成功。"""
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
        """同时校验原始路径与解析路径在授权子目录内，拒绝途经符号链接的路径。"""
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
        """遍历各业务声明的媒体目录，只产生仍满足路径边界检查的目录或文件。"""
        for source in self._references:
            for name in source.media_directories:
                self._check_cancelled()
                directory = self.data_path / name
                if not self._is_managed_path(directory) or not directory.is_dir():
                    continue
                yield directory
                for path in directory.rglob("*"):
                    self._check_cancelled()
                    if self._is_managed_path(path):
                        yield path

    def _media_files(self) -> list[Path]:
        """收集受管目录中的普通媒体文件，跳过符号链接及扫描期间无法访问的条目。"""
        files = []
        for path in self._managed_entries():
            try:
                if not path.is_symlink() and path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                    files.append(path)
            except OSError:
                continue
        return files

    def _media_size(self) -> int:
        """累计当前可读取的受管媒体文件字节数，扫描过程中消失的文件不计入。"""
        total = 0
        for path in self._media_files():
            self._check_cancelled()
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def _remove_empty_directories(self) -> None:
        """由深到浅尝试移除空目录，保留非空或无法删除的目录。"""
        directories = sorted(
            (path for path in self._managed_entries() if path.is_dir()),
            key=lambda path: len(path.parts), reverse=True,
        )
        for path in directories:
            self._check_cancelled()
            try:
                path.rmdir()
            except OSError:
                continue

    def _safe_mtime(self, path: Path) -> float:
        """读取文件修改时间，失败返回无穷大，使不确定文件不会被当作最旧候选优先删除。"""
        self._check_cancelled()
        try:
            return path.stat().st_mtime
        except OSError:
            return float("inf")
