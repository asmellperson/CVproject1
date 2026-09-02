# 文件说明：包含资源清理的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import json
import os
from pathlib import Path


from AiVision.integrations.guard_room.src.alarms import AlarmManager
from AiVision.integrations.guard_room.src.media_cleanup import cleanup_alarm_media
from AiVision.integrations.guard_room.src.types import AlarmEvent


# 功能：更新或保存 `_write_media` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
#   - `size`（int）：`size` 对应的数量或大小
#   - `modified_at`（float）：`modified_at` 对应的业务输入值
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_media_cleanup.py` 的
#         `test_cleanup_removes_expired_images_videos_and_prunes_event_index`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_media_cleanup.py` 的
#         `test_cleanup_enforces_combined_image_and_video_capacity_with_active_grace`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_media_cleanup.py` 的
#         `test_cleanup_rejects_symlinks_and_alarm_manager_prunes_memory` 调用本符号
#   - 内部调用：`path.parent.mkdir`、`path.write_bytes`、`os.utime`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _write_media(path: Path, size: int, modified_at: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (modified_at, modified_at))
    return path


# 功能：验证 `test_cleanup_removes_expired_images_videos_and_prunes_event_index` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_write_media`、`index_path.write_text`、`json.dumps`、`str`、`cleanup_alarm_media`、`old_image.exists`、`old_video.exists`、`recent_image.exists`、`json.loads`、`index_path.read_text`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_cleanup_removes_expired_images_videos_and_prunes_event_index(tmp_path):
    output_dir = tmp_path / "outputs"
    now = 1_800_000_000.0
    old_image = _write_media(output_dir / "alarms" / "old.jpg", 5, now - 8 * 86400)
    old_video = _write_media(output_dir / "alarm_clips" / "old.mp4", 7, now - 8 * 86400)
    recent_image = _write_media(output_dir / "alarms" / "recent.jpg", 11, now - 60)
    index_path = output_dir / "alarm_events.json"
    index_path.write_text(json.dumps([
        {"image_path": str(old_image), "video_path": str(old_video)},
        {"image_path": str(recent_image), "video_path": None},
    ]), encoding="utf-8")

    stats = cleanup_alarm_media(
        output_dir,
        retention_days=7,
        max_bytes=1024,
        now=now,
    )

    assert not old_image.exists()
    assert not old_video.exists()
    assert recent_image.exists()
    assert stats.removed_files == 2
    assert stats.removed_bytes == 12
    assert stats.pruned_events == 1
    assert json.loads(index_path.read_text(encoding="utf-8")) == [
        {"image_path": str(recent_image), "video_path": None}
    ]


# 功能：验证 `test_cleanup_enforces_combined_image_and_video_capacity_with_active_grace` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_write_media`、`cleanup_alarm_media`、`old_image.exists`、`old_video.exists`、`recent_video.exists`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_cleanup_enforces_combined_image_and_video_capacity_with_active_grace(tmp_path):
    output_dir = tmp_path / "outputs"
    now = 1_800_000_000.0
    old_image = _write_media(output_dir / "alarms" / "old.jpg", 8, now - 3600)
    old_video = _write_media(output_dir / "vehicle_clips" / "old.mp4", 8, now - 1800)
    recent_video = _write_media(output_dir / "alarm_clips" / "recording.mp4", 8, now - 30)

    stats = cleanup_alarm_media(
        output_dir,
        retention_days=30,
        max_bytes=10,
        now=now,
    )

    assert not old_image.exists()
    assert not old_video.exists()
    assert recent_video.exists()
    assert stats.remaining_bytes == 8


# 功能：验证 `test_cleanup_rejects_symlinks_and_alarm_manager_prunes_memory` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_write_media`、`alarms_dir.mkdir`、`(alarms_dir /
#          'outside.jpg').symlink_to`、`AlarmManager`、`manager.events.append`、`AlarmEvent`、`str`、`manager._flush`、`manager.cleanup_media`、`outside.exists`
#          等共 13 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_cleanup_rejects_symlinks_and_alarm_manager_prunes_memory(tmp_path):
    output_dir = tmp_path / "outputs"
    outside = _write_media(tmp_path / "outside.jpg", 9, 1.0)
    alarms_dir = output_dir / "alarms"
    alarms_dir.mkdir(parents=True)
    (alarms_dir / "outside.jpg").symlink_to(outside)

    manager = AlarmManager(output_dir)
    managed_image = _write_media(alarms_dir / "managed.jpg", 3, 1.0)
    manager.events.append(AlarmEvent(
        event_type="phone_use",
        timestamp_s=1.0,
        frame_index=1,
        track_id=None,
        confidence=0.9,
        reason="test",
        image_path=str(managed_image),
    ))
    manager._flush()

    stats = manager.cleanup_media(retention_days=1, max_bytes=1024, now=200_000.0)

    assert outside.exists()
    assert (alarms_dir / "outside.jpg").is_symlink()
    assert stats.skipped_unsafe_paths == 1
    assert manager.events == []
    assert json.loads((output_dir / "alarm_events.json").read_text(encoding="utf-8")) == []
