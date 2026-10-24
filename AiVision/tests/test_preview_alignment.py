"""移动、消失及慢推理场景下，检测框不能残留在不对应的视频画面。"""
from datetime import datetime, timezone
from queue import Queue
from types import SimpleNamespace

import numpy as np
import pytest


NOW = 1000.0
OLD_BOX = [20, 30, 40, 70]
NEW_BOX = [80, 30, 100, 70]
GREEN = (60, 200, 80)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "tests", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "tests", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)


def image_with_person(box, background):
    frame = np.full((96, 128, 3), background, dtype=np.uint8)
    x1, y1, x2, y2 = box
    frame[y1:y2, x1:x2] = 255
    frame.setflags(write=False)
    return frame


@pytest.fixture(params=["fence", "tailgating"])
def preview(request):
    kwargs = {"infer_dict": {}, "result_queue": Queue(), "latest_frames": {}, "is_camera_active": lambda key: True}
    if request.param == "fence":
        from AiVision.features.security_fence.consumer import FenceConsumer
        from AiVision.features.security_fence.runtime import current_mode
        from AiVision.features.security_fence.schema import FenceValue

        value = FenceValue()
        consumer = FenceConsumer(spec=SimpleNamespace(name="security_fence", alarm_types=()), **kwargs)

        def configure(camera_id, cfg):
            consumer.preview.configure(camera_id, cfg)

        def detail(box):
            return {"persons": [{"bbox": list(box), "track_id": 1, "identity": "allowed", "alarm": False}],
                    "faces": [], "mode": current_mode(value, datetime.fromtimestamp(NOW, timezone.utc)),
                    "frame_width": 128, "frame_height": 96, "updated_at_s": NOW}
    else:
        from AiVision.features.tailgating.consumer import TailgatingConsumer
        from AiVision.features.tailgating.schema import TailgatingValue

        value = TailgatingValue(roi_pos=[[0, 0], [1, 0], [1, 1], [0, 1]])
        consumer = TailgatingConsumer(spec=SimpleNamespace(name="tailgating", alarm_types=()), **kwargs)

        def configure(camera_id, cfg):
            consumer._configure_camera(camera_id)

        def detail(box):
            return {"persons": [{"bbox": list(box), "track_id": 1}], "events": [], "reason": "clear",
                    "frame_width": 128, "frame_height": 96, "updated_at_s": NOW}

    def setup(camera_id=1):
        cfg = {**value.model_dump(), "enable": True, "camera_enable": True, "shm_name": f"camera_{camera_id}"}
        consumer.config_cache[camera_id] = cfg
        configure(camera_id, cfg)

    def publish(frame, *, camera_id=1, sampled_at=NOW - .1, box=OLD_BOX, result=None):
        consumer.frame_cache[camera_id] = frame
        consumer._last_process_at[camera_id] = sampled_at
        return consumer.post_process(camera_id, (False, result if result is not None else detail(box)))

    setup()
    return SimpleNamespace(consumer=consumer, setup=setup, publish=publish, detail=detail, kind=request.param)


def test_moving_person_boxes_use_detection_source_instead_of_newer_video_frame(preview):
    source = image_with_person(OLD_BOX, 20)
    live = image_with_person(NEW_BOX, 80)
    evidence = preview.publish(source)
    rendered = preview.consumer.get_live_preview("camera_1", live, now=NOW)
    assert np.array_equal(rendered, evidence)
    assert rendered[50, 30].tolist() == [255, 255, 255]
    assert rendered[50, 90].tolist() == [20, 20, 20]
    assert rendered[50, 20].tolist() == list(GREEN)
    assert source[50, 20].tolist() == [255, 255, 255]
    assert live[50, 20].tolist() == [80, 80, 80]


@pytest.mark.parametrize("sample_age", [3.0, -1.0])
def test_late_inference_or_invalid_sample_clock_cannot_make_old_boxes_fresh(preview, sample_age):
    source = image_with_person(OLD_BOX, 20)
    live = image_with_person(NEW_BOX, 80)
    # 结果刚完成，但原图已经过期；证据保留原图，监控撤销过期的空间标注。
    evidence = preview.publish(source, sampled_at=NOW - sample_age)
    rendered = preview.consumer.get_live_preview("camera_1", live, now=NOW)
    assert evidence[50, 20].tolist() == list(GREEN)
    assert rendered[50, 20].tolist() == [80, 80, 80]
    assert rendered[50, 90].tolist() == [255, 255, 255]


def test_new_empty_observation_removes_previous_boxes_without_waiting_for_track_ttl(preview):
    source = image_with_person(OLD_BOX, 20)
    preview.publish(source)
    empty = np.full_like(source, 80)
    result = preview.detail(OLD_BOX)
    result["persons"] = []
    preview.publish(empty, result=result)
    rendered = preview.consumer.get_live_preview("camera_1", empty, now=NOW)
    assert rendered[50, 20].tolist() == [80, 80, 80]
    assert rendered[50, 30].tolist() == [80, 80, 80]


def test_resolution_or_configuration_change_clears_spatial_annotations(preview):
    preview.publish(image_with_person(OLD_BOX, 20))
    resized = np.full((120, 160, 3), 80, dtype=np.uint8)
    assert preview.consumer.get_live_preview("camera_1", resized, now=NOW)[50, 20].tolist() == [80, 80, 80]
    preview.setup()
    live = image_with_person(NEW_BOX, 80)
    assert preview.consumer.get_live_preview("camera_1", live, now=NOW)[50, 20].tolist() == [80, 80, 80]


def test_camera_sources_are_isolated_and_new_result_replaces_old_coordinates(preview):
    preview.setup(2)
    preview.publish(image_with_person(OLD_BOX, 20))
    preview.publish(image_with_person(NEW_BOX, 80), camera_id=2, box=NEW_BOX)
    live = image_with_person(NEW_BOX, 100)
    first = preview.consumer.get_live_preview("camera_1", live, now=NOW)
    second = preview.consumer.get_live_preview("camera_2", live, now=NOW)
    assert first[50, 20].tolist() == list(GREEN)
    assert second[50, 20].tolist() == [80, 80, 80]
    assert second[50, 80].tolist() == list(GREEN)
    preview.publish(live, box=NEW_BOX)
    updated = preview.consumer.get_live_preview("camera_1", live, now=NOW)
    assert updated[50, 20].tolist() == [100, 100, 100]
    assert updated[50, 80].tolist() == list(GREEN)


@pytest.mark.parametrize("feature", ["person_dwell", "face_dwell"])
@pytest.mark.parametrize("alarmed", [False, True])
def test_dwell_lost_tracks_remain_matchable_but_are_never_drawn(feature, alarmed):
    from AiVision.features._shared.dwell_consumer import DwellObservationClock
    from AiVision.features._shared.tracking import IouTracker
    from AiVision.features.face_dwell.consumer import FaceConsumer
    from AiVision.features.person_dwell.consumer import HumanConsumer

    cls = HumanConsumer if feature == "person_dwell" else FaceConsumer
    consumer = cls(spec=SimpleNamespace(name=feature, alarm_types=()), infer_dict={}, result_queue=Queue(),
                   latest_frames={}, is_camera_active=lambda key: True)
    consumer.config_cache[1] = {"shm_name": "camera_1", "roi_pos": [], "MAX_TIME": 10}
    consumer.frame_cache[1] = image_with_person(NEW_BOX, 80)
    consumer._observation_clocks[1] = DwellObservationClock(valid=True)
    tracker = consumer._trackers[1] = IouTracker(max_lost=5)
    tracks = tracker.update([{"bbox": OLD_BOX}], now=0)
    old_id = next(iter(tracks))
    tracks[old_id].alarmed = alarmed
    tracks = tracker.update([{"bbox": NEW_BOX}], now=1)
    assert tracks[old_id].lost == 1
    rendered = consumer.post_process(1, (False, None))
    assert rendered[50, 20].tolist() == [80, 80, 80]
    assert rendered[50, 80].tolist() == list(consumer.BBOX_COLOR_NORMAL)
    assert consumer.monitor_status["camera_1"]["count"] == 1
    # 重连容忍仍保留，避免为了清理残影重置轨迹编号和停留计时。
    tracker.update([{"bbox": OLD_BOX}], now=2)
    assert tracker.tracks[old_id].lost == 0
    assert tracker.tracks[old_id].alarmed is alarmed
