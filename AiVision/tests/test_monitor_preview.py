"""原始预览保留授权，当前检测结果与报警证据相互独立。"""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock
import time
from threading import Event, Thread

import numpy as np
import pytest


@pytest.fixture
def modules(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "preview_test",
        "MYSQL_DB_PASSWORD": "preview_test", "MYSQL_DB_NAME": "preview_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "preview-test-signing-key-00000000",
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.api.routes import cameras, preview_stream
    from AiVision.features.registry import get_spec
    from AiVision.runtime.orchestrator import Orchestrator
    return cameras, preview_stream, get_spec, Orchestrator


def user(features):
    return {"role": "viewer", "departments": ["general_electric"],
            "feature_access": {"general_electric": features}}


@pytest.mark.parametrize("raw", [True, False])
def test_raw_preview_keeps_feature_authorization(modules, monkeypatch, raw):
    cameras, _, _, _ = modules
    manager = SimpleNamespace(get_camera_identity=lambda key: {
        "shm_name": key, "department": "general_electric", "enabled": True,
    })
    response = Mock(return_value="jpeg")
    monkeypatch.setattr(cameras, "build_camera_frame_response", response)
    args = dict(key="camera_1", feature="detect_phone", raw=raw, quality=85,
                max_width=1280, max_height=None, camera_config_manager=manager, orchestrator=object())
    with pytest.raises(cameras.HTTPException) as error:
        cameras.get_camera_frame_jpg(user=user([]), **args)
    assert error.value.status_code == 403
    response.assert_not_called()
    assert cameras.get_camera_frame_jpg(user=user(["detect_phone"]), **args) == "jpeg"
    assert response.call_args.kwargs["feature"] == (None if raw else "detect_phone")


def test_raw_video_covers_other_features_and_preserves_inspection_policy(modules, monkeypatch):
    _, preview, get_spec, _ = modules
    monkeypatch.setattr(preview.settings.preview, "camera_key", "")
    source = {"shm_name": "camera_2", "url": "rtsp://camera.example.test/live", "enabled": True}
    features = ["blocks", "detect_door", "detect_face", "detect_human", "detect_phone", "recognize_face",
                "guard_behavior", "detect_logistics_single_person", "agv_person_check", "security_fence",
                "tailgating", "visual_language_detection"]
    for feature in features:
        assert get_spec(feature) is not None
        assert preview._preview_enabled(source, feature)
    assert not preview._preview_enabled(source, "security_inspection")
    monkeypatch.setattr(preview.settings.preview, "camera_key", "camera_2")
    monkeypatch.setattr(preview.settings.preview, "feature", "security_inspection")
    assert preview._preview_enabled(source, "security_inspection")
    assert not preview._preview_enabled(source, None)
    assert not preview._preview_enabled({**source, "enabled": False}, "blocks")
    assert not preview._preview_enabled({**source, "url": "/local/video.mp4"}, "blocks")


@pytest.mark.parametrize("feature", ["blocks", "detect_door", "detect_phone"])
def test_current_results_publish_from_processed_frames(modules, feature):
    _, _, get_spec, _ = modules
    spec = get_spec(feature)
    frame = np.zeros((100, 160, 3), dtype=np.uint8)
    consumer = spec.consumer_cls(spec=spec, infer_dict={}, result_queue=Queue(),
        latest_frames={"camera_1": frame}, latest_frame_times={"camera_1": time.time()}, is_camera_active=lambda key: True)
    config = spec.config_schema().value.model_dump()
    consumer.config_cache[1] = {**config, "shm_name": "camera_1", "camera_enable": True,
                                "enable": True, "department": "general_electric"}
    if feature == "blocks":
        consumer.config_cache[1]["line_points"] = [[0.5, 0.0], [0.5, 1.0]]
    consumer.dispatch_inference_sync = Mock(return_value={"status": "ok", "detections": []})
    # 这里保留门状态的双阶段计时，但不发送外部通知。
    consumer._handle_alarm = lambda camera_id, result, frame: consumer._should_alarm(camera_id, result, consumer.config_cache[camera_id])
    consumer._after_process = lambda *args: setattr(consumer, "running", False)
    consumer.running = True
    consumer._run()
    result = consumer.get_monitor_status("camera_1")
    assert result is not None and result["updated_at_s"] > 0
    assert not result["alarm"]
    assert result["reason"] == ("background_initializing" if feature == "detect_door" else "normal")
    assert consumer.result_dict["camera_1"].shape == frame.shape
    consumer.update_status(1, False)
    assert consumer.get_monitor_status("camera_1") is None
    consumer._clear_camera_state(1, "camera_1")
    assert consumer.get_monitor_status("camera_1") is None


def test_phone_failure_is_unknown_instead_of_empty(modules):
    _, _, get_spec, _ = modules
    spec = get_spec("detect_phone")
    consumer = spec.consumer_cls(spec=spec, infer_dict={}, result_queue=Queue(), latest_frames={}, is_camera_active=lambda key: True)
    consumer.config_cache[1] = spec.config_schema().value.model_dump()
    consumer.dispatch_inference_sync = Mock(return_value={"status": "timeout", "detections": []})
    result = consumer._process(np.zeros((10, 10, 3), dtype=np.uint8), 1)
    snapshot = consumer._build_monitor_snapshot(1, result)
    assert snapshot["count"] is None
    assert snapshot["reason"] == "inference_error"
    assert not snapshot["alarm"]


def test_dwell_details_only_include_visible_tracks(modules):
    from AiVision.features._shared.dwell_consumer import build_dwell_monitor_snapshot
    from AiVision.features._shared.tracking import Track
    tracker = SimpleNamespace(tracks={1: Track([0, 0, 5, 10], 10, 12), 2: Track([0, 0, 5, 10], 0, 30, lost=1, alarmed=True)})
    snapshot = build_dwell_monitor_snapshot({1: tracker}, camera_id=1, threshold_seconds=10)
    assert snapshot["count"] == 1 and not snapshot["alarm"]
    assert snapshot["details"] == [{"label": "轨迹 1", "duration_seconds": 2, "state": "normal"}]


def test_door_card_distinguishes_confirmation_from_alarm(modules, monkeypatch):
    _, _, get_spec, _ = modules
    from AiVision.features.door_state import consumer as door_module
    door = object.__new__(get_spec("detect_door").consumer_cls)
    door._alarm_state = {}
    door.config_cache = {1: {"first_alarm": 10}}
    result = (True, {"stable": True, "ratio": 0.6, "hits": 3})
    monkeypatch.setattr(door_module.time, "time", lambda: 100)
    assert not door._should_alarm(1, result, door.config_cache[1])
    assert door._build_monitor_snapshot(1, result)["reason"] == "door_changed"
    monkeypatch.setattr(door_module.time, "time", lambda: 111)
    assert door._should_alarm(1, result, door.config_cache[1])
    snapshot = door._build_monitor_snapshot(1, result)
    assert snapshot["reason"] == "door_alarm" and snapshot["alarm"]
    assert snapshot["duration_seconds"] == 11


def test_dwell_status_read_does_not_wait_for_inference_lock(modules):
    _, _, get_spec, _ = modules
    spec = get_spec("detect_human")
    consumer = spec.consumer_cls(spec=spec, infer_dict={}, result_queue=Queue(), latest_frames={}, is_camera_active=lambda key: True)
    consumer.monitor_status["camera_1"] = {"count": 1, "alarm": False}
    completed = Event()
    result = []

    def read_status():
        result.append(consumer.get_monitor_status("camera_1"))
        completed.set()

    with consumer._camera_state_lock:
        reader = Thread(target=read_status)
        reader.start()
        ready_while_processing = completed.wait(0.2)
    reader.join(1)
    assert ready_while_processing
    assert result == [{"count": 1, "alarm": False}]


@pytest.mark.parametrize("age,online,enabled", [(0.2, True, True), (3, True, True), (0.2, False, True), (0.2, True, False), (-1, True, True)])
def test_status_expiration_and_lifecycle(modules, age, online, enabled):
    _, _, _, orchestrator_type = modules
    consumer = SimpleNamespace(running=enabled, config_cache={1: {"shm_name": "camera_1", "camera_enable": True}},
        get_monitor_status=lambda key: {"updated_at_s": time.time() - age, "count": 1, "alarm": True,
                                      "reason": "intrusion", "details": [{"label": "人员 1"}]})
    runtime = SimpleNamespace(consumers={"blocks": consumer}, camera_runtime_manager=SimpleNamespace(list_running=lambda: ["camera_1"] if online else []))
    snapshot = orchestrator_type.get_feature_monitor_status(runtime, "camera_1", "blocks")
    if online and enabled and 0 <= age < 2:
        assert snapshot["count"] == 1 and snapshot["alarm"]
        assert 0 < snapshot["valid_for_seconds"] <= 2
    else:
        assert snapshot["count"] is None and not snapshot["alarm"] and snapshot["details"] == []
