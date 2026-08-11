import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alarms import AlarmManager
from src.media_cleanup import cleanup_alarm_media
from src.types import AlarmEvent


def _write_media(path: Path, size: int, modified_at: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (modified_at, modified_at))
    return path


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
