"""围栏实时画面不等待推理完成，过期身份和不同摄像头的状态相互隔离。"""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from AiVision.features.security_fence.preview import FencePreview
from AiVision.features.security_fence.schema import FenceValue


@pytest.fixture
def preview(monkeypatch, tmp_path):
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "test",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path), "AUTO_CREATE_DB": "false",
    }.items():
        monkeypatch.setenv(key, value)
    value = FenceValue(forbidden_start="00:00", forbidden_end="00:00", timezone="UTC")
    config = {**value.model_dump(), "enable": True, "camera_enable": True, "shm_name": "camera_80"}
    cache = FencePreview((238, 211, 34))
    cache.configure(80, config)
    detail = {
        "persons": [{"bbox": [20, 30, 60, 70], "alarm": True, "identity": "unauthorized", "track_id": 1}],
        "faces": [{"bbox": [24, 32, 34, 42]}], "mode": "forbidden", "updated_at_s": 100.0,
        "frame_width": 120, "frame_height": 100, "count": 1, "pending_count": 0,
        "alarm": True, "error": None,
    }
    return SimpleNamespace(cache=cache, config=config, detail=detail, raw=np.full((100, 120, 3), 7, dtype=np.uint8))


def test_raw_picture_keeps_updating_while_inference_has_not_finished(preview):
    first, _ = preview.cache.render("camera_80", preview.raw, now=100.0)
    second, _ = preview.cache.render("camera_80", np.full_like(preview.raw, 25), now=103.0)
    assert first is not None and second is not None
    assert first[80, 90].tolist() == [7, 7, 7]
    assert second[80, 90].tolist() == [25, 25, 25]
    assert preview.cache.status("camera_80") is None
    assert np.all(preview.raw == 7)


def test_recent_detections_overlay_the_latest_picture_and_preserve_face_boxes(preview):
    preview.cache.publish(80, preview.detail)
    frame, updated = preview.cache.render("camera_80", preview.raw, now=103.0)
    assert updated == 100.0
    assert frame[50, 20].tolist() == [0, 0, 255]
    assert frame[32, 24].tolist() == [255, 200, 0]
    assert np.all(preview.raw == 7)


@pytest.mark.parametrize("now", [106.0, 99.0])
def test_expired_or_future_identity_is_not_drawn_but_live_video_remains(preview, now):
    preview.cache.publish(80, preview.detail)
    frame, _ = preview.cache.render("camera_80", preview.raw, now=now)
    assert frame is not None
    assert frame[50, 20].tolist() == [7, 7, 7]
    assert frame[32, 24].tolist() == [7, 7, 7]


def test_resolution_or_rule_period_change_does_not_reuse_old_identity(preview):
    preview.cache.publish(80, preview.detail)
    resized, _ = preview.cache.render("camera_80", np.full((200, 240, 3), 7, dtype=np.uint8), now=101.0)
    assert resized[50, 20].tolist() == [7, 7, 7]
    changed = {**preview.detail, "mode": "whitelist"}
    preview.cache.publish(80, changed)
    frame, _ = preview.cache.render("camera_80", preview.raw, now=101.0)
    assert frame[50, 20].tolist() == [7, 7, 7]


def test_config_update_disable_and_different_cameras_clear_old_results(preview):
    preview.cache.publish(80, preview.detail)
    config = {**preview.config, "shm_name": "camera_83"}
    preview.cache.configure(83, config)
    assert preview.cache.status("camera_83") is None
    preview.cache.configure(80, {**preview.config, "roi_pos": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]})
    assert preview.cache.status("camera_80") is None
    preview.cache.configure(80, {**preview.config, "camera_enable": False})
    assert preview.cache.render("camera_80", preview.raw, now=101.0) == (None, 0.0)
    preview.cache.configure(83, None)
    assert preview.cache.render("camera_83", preview.raw, now=101.0) == (None, 0.0)


def test_status_and_published_data_are_independent_snapshots(preview):
    detail = deepcopy(preview.detail)
    preview.cache.publish(80, detail)
    detail["persons"].clear()
    status = preview.cache.status("camera_80")
    assert len(status["persons"]) == 1
    status["persons"][0]["identity"] = "allowed"
    assert preview.cache.status("camera_80")["persons"][0]["identity"] == "unauthorized"


def test_preview_and_status_do_not_wait_for_consumer_inference_lock(preview, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    from AiVision.features.security_fence.consumer import FenceConsumer

    class InferenceLock:
        def __enter__(self):
            raise AssertionError("画面和状态读取不能等待推理锁")

        def __exit__(self, *args):
            return False

    consumer = FenceConsumer.__new__(FenceConsumer)
    consumer.preview = preview.cache
    consumer._camera_state_lock = InferenceLock()
    preview.cache.publish(80, preview.detail)
    assert consumer.get_monitor_status("camera_80")["count"] == 1
    frame, _ = consumer.get_live_preview("camera_80", preview.raw, now=103.0)
    assert frame is not None


def test_orchestrator_uses_live_preview_but_still_rejects_stale_capture(preview, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    from AiVision.runtime import orchestrator as module

    preview.cache.publish(80, preview.detail)
    monkeypatch.setattr(module.time, "time", lambda: 104.0)
    monkeypatch.setattr(module.frame_reader_registry, "latest_frames", {"camera_80": preview.raw})
    monkeypatch.setattr(module.frame_reader_registry, "latest_frame_times", {"camera_80": 103.0})
    platform = module.Orchestrator.__new__(module.Orchestrator)
    platform.consumers = {"security_fence": SimpleNamespace(get_live_preview=lambda key, frame, now: preview.cache.render(key, frame, now=now))}
    frame, updated = platform.get_camera_frame_info("camera_80", feature="security_fence")
    assert frame is not None and updated == 104.0
    preview.cache.configure(80, None)
    assert platform.get_camera_frame_info("camera_80", feature="security_fence")[0] is None
    monkeypatch.setattr(module.time, "time", lambda: 114.0)
    assert platform.get_camera_frame_info("camera_80", feature="security_fence")[0] is None


def test_other_features_keep_their_existing_annotated_frame_freshness(preview, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    from AiVision.runtime import orchestrator as module

    monkeypatch.setattr(module.time, "time", lambda: 104.0)
    monkeypatch.setattr(module.frame_reader_registry, "latest_frames", {"camera_80": preview.raw})
    monkeypatch.setattr(module.frame_reader_registry, "latest_frame_times", {"camera_80": 103.0})
    consumer = SimpleNamespace(result_dict={"camera_80": preview.raw}, result_updated_at={"camera_80": 100.0})
    platform = module.Orchestrator.__new__(module.Orchestrator)
    platform.consumers = {"detect_human": consumer}
    assert platform.get_camera_frame_info("camera_80", feature="detect_human")[0] is None
    consumer.result_updated_at["camera_80"] = 103.0
    assert platform.get_camera_frame_info("camera_80", feature="detect_human")[0] is preview.raw


def test_jpeg_cache_does_not_keep_boxes_after_detection_expiry(preview, monkeypatch):
    import cv2
    from AiVision.api.routes.cameras import build_camera_frame_response
    from AiVision.runtime import orchestrator as module

    preview.cache.publish(80, preview.detail)
    monkeypatch.setattr(module.frame_reader_registry, "latest_frames", {"camera_80": preview.raw})
    monkeypatch.setattr(module.frame_reader_registry, "latest_frame_times", {"camera_80": 103.0})
    platform = module.Orchestrator.__new__(module.Orchestrator)
    platform.consumers = {"security_fence": SimpleNamespace(get_live_preview=lambda key, frame, now: preview.cache.render(key, frame, now=now))}
    pictures = []
    for now in (104.0, 106.0):
        monkeypatch.setattr(module.time, "time", lambda: now)
        response = build_camera_frame_response(key="camera_80", feature="security_fence", quality=95,
                                              max_width=None, max_height=None, orchestrator=platform)
        assert response.status_code == 200
        pictures.append(cv2.imdecode(np.frombuffer(response.body, dtype=np.uint8), cv2.IMREAD_COLOR))
    assert int(pictures[0][50, 20, 2]) > 150
    assert int(pictures[1][50, 20, 2]) < 30


def test_consumer_lifecycle_publishes_config_and_invalidates_disabled_preview(preview, monkeypatch):
    from queue import Queue
    from AiVision.core.cache import config_cache
    from AiVision.features.security_fence.consumer import FenceConsumer
    from AiVision.features.security_fence.spec import SPEC

    monkeypatch.setattr(config_cache, "get_all_function_configs", lambda: {(80, "security_fence"): preview.config})
    monkeypatch.setattr(config_cache, "get_function_config", lambda *args: preview.config)
    consumer = FenceConsumer(SPEC, {}, Queue(), {}, lambda key: True)
    monkeypatch.setattr(consumer, "_reset_alarm_cooldown", lambda camera_id: None)
    consumer._load_initial_configs()
    consumer.frame_cache[80] = preview.raw
    evidence = consumer.post_process(80, (True, preview.detail))
    assert evidence[50, 20].tolist() == [0, 0, 255]
    assert consumer.get_monitor_status("camera_80")["count"] == 1
    consumer.update_config(80)
    assert consumer.get_monitor_status("camera_80") is None
    assert consumer.get_live_preview("camera_80", preview.raw, now=103.0)[0] is not None
    consumer.update_status(80, False)
    assert consumer.get_live_preview("camera_80", preview.raw, now=103.0)[0] is None
    consumer.update_status(80, True)
    assert consumer.get_live_preview("camera_80", preview.raw, now=103.0)[0] is not None


def test_disable_during_render_does_not_return_previous_configuration(preview, monkeypatch):
    from AiVision.features.security_fence import preview as module

    preview.cache.publish(80, preview.detail)
    monkeypatch.setattr(module, "draw_fence_detections", lambda *args: preview.cache.configure(80, None))
    assert preview.cache.render("camera_80", preview.raw, now=101.0) == (None, 0.0)
