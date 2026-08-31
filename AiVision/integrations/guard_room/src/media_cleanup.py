# 文件说明：实现资源清理相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：一次门卫室报警证据清理的结果；输入与输出详见下方说明
# 参数：
#   - `removed_files`（int）：`removed_files` 对应的业务输入值
#   - `removed_bytes`（int）：`removed_bytes` 对应的业务输入值
#   - `pruned_events`（int）：`pruned_events` 对应的业务输入值
#   - `skipped_unsafe_paths`（int）：`skipped_unsafe_paths` 对应的业务输入值
#   - `failed_files`（int）：`failed_files` 对应的业务输入值
#   - `remaining_bytes`（int）：`remaining_bytes` 对应的业务输入值
#   - `skipped_busy`（bool）：`skipped_busy` 对应的业务输入值
# 返回：AlarmMediaCleanupStats；返回新建的 `AlarmMediaCleanupStats` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/media_cleanup.py` 的 `cleanup_alarm_media` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：定义 `_MediaFile` 类，封装资源清理相关的状态、约束与操作
# 参数：
#   - `path`（Path）：目标路径
#   - `modified_at`（float）：`modified_at` 对应的业务输入值
#   - `size`（int）：`size` 对应的数量或大小
# 返回：_MediaFile；返回新建的 `_MediaFile` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/media_cleanup.py` 的 `_collect_media` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _MediaFile:
    path: Path
    modified_at: float
    size: int


# 功能：按保存天数和容量上限清理报警图片、视频及其事件索引；输入与输出详见下方说明
# 参数：
#   - `output_dir`（str | Path）：`output_dir` 对应的业务输入值
#   - `retention_days`（int）：`retention_days` 对应的业务输入值
#   - `max_bytes`（int）：`max_bytes` 对应的业务输入值
#   - `now`（float | None）：`now` 对应的业务输入值；默认值为 `None`
# 返回：AlarmMediaCleanupStats；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/alarms.py` 的 `AlarmManager::cleanup_media`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_media_cleanup.py` 的
#         `test_cleanup_removes_expired_images_videos_and_prunes_event_index`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_media_cleanup.py` 的
#         `test_cleanup_enforces_combined_image_and_video_capacity_with_active_grace` 调用本符号
#   - 内部调用：`AlarmMediaCleanupStats`、`_CLEANUP_LOCK.acquire`、`time.time`、`float`、`Path(output_dir).expanduser().resolve`、`Path(output_dir).expanduser`、`Path`、`tuple`、`(output_root
#          / name).resolve`、`_collect_media` 等共 22 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：判断内存报警事件的已落盘证据是否仍然存在；输入与输出详见下方说明
# 参数：
#   - `event`（未显式标注）：待处理的事件对象
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/alarms.py` 的 `AlarmManager::cleanup_media` 调用本符号
#   - 内部调用：`getattr`、`Path(image_path).exists`、`Path`、`Path(video_path).exists`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def event_media_available(event) -> bool:
    """判断内存报警事件的已落盘证据是否仍然存在。"""
    image_path = getattr(event, "image_path", None)
    if image_path and not Path(image_path).exists():
        return False
    video_path = getattr(event, "video_path", None)
    if video_path and not Path(video_path).exists():
        return False
    return True


# 功能：实现 `_collect_media` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `managed_roots`（Iterable[Path]）：`managed_roots` 对应的业务输入值
#   - `stats`（AlarmMediaCleanupStats）：`stats` 对应的业务输入值
# 返回：list[_MediaFile]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/media_cleanup.py` 的 `cleanup_alarm_media` 调用本符号
#   - 内部调用：`root.exists`、`root.rglob`、`path.is_symlink`、`path.is_file`、`path.suffix.lower`、`path.resolve`、`resolved.is_relative_to`、`resolved.stat`、`media.append`、`_MediaFile`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：删除或清理 `_remove_file` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `item`（_MediaFile）：`item` 对应的业务输入值
#   - `stats`（AlarmMediaCleanupStats）：`stats` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/media_cleanup.py` 的 `cleanup_alarm_media` 调用本符号
#   - 内部调用：`item.path.unlink`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _remove_file(item: _MediaFile, stats: AlarmMediaCleanupStats) -> bool:
    try:
        item.path.unlink(missing_ok=True)
        stats.removed_files += 1
        stats.removed_bytes += item.size
        return True
    except OSError:
        stats.failed_files += 1
        return False


# 功能：删除或清理 `_prune_event_index` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `output_root`（Path）：`output_root` 对应的业务输入值
#   - `managed_roots`（tuple[Path, ...]）：`managed_roots` 对应的业务输入值
#   - `stats`（AlarmMediaCleanupStats）：`stats` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/media_cleanup.py` 的 `cleanup_alarm_media` 调用本符号
#   - 内部调用：`index_path.exists`、`json.loads`、`index_path.read_text`、`isinstance`、`_managed_reference`、`event.get`、`any`、`path.exists`、`path.stat`、`path.unlink`
#          等共 17 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：实现 `_managed_reference` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `raw_path`（未显式标注）：`raw_path` 对应的业务输入值
#   - `managed_roots`（tuple[Path, ...]）：`managed_roots` 对应的业务输入值
#   - `stats`（AlarmMediaCleanupStats）：`stats` 对应的业务输入值
# 返回：Path | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/media_cleanup.py` 的 `_prune_event_index` 调用本符号
#   - 内部调用：`Path(str(raw_path)).expanduser().resolve`、`Path(str(raw_path)).expanduser`、`Path`、`str`、`any`、`path.is_relative_to`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：实现 `_directory_size` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `managed_roots`（Iterable[Path]）：`managed_roots` 对应的业务输入值
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/media_cleanup.py` 的 `cleanup_alarm_media` 调用本符号
#   - 内部调用：`root.exists`、`root.rglob`、`path.is_symlink`、`path.is_file`、`path.suffix.lower`、`path.stat`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：删除或清理 `_remove_empty_directories` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `managed_roots`（Iterable[Path]）：`managed_roots` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`root.exists`、`sorted`、`root.rglob`、`path.is_dir`、`len`、`path.rmdir`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
