"""原始预览保留授权，当前检测结果与报警证据相互独立。"""
from queue import Queue
from datetime import datetime
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


@pytest.mark.parametrize("feature,full_blur", [("blocks", False), ("detect_door", True)])
def test_full_roi_blur_is_only_used_by_door_state(modules, monkeypatch, feature, full_blur):
    import cv2

    _, _, get_spec, _ = modules
    spec = get_spec(feature)
    consumer = spec.consumer_cls(spec=spec, infer_dict={}, result_queue=Queue(), latest_frames={},
                                 is_camera_active=lambda key: True)
    image = np.zeros((60, 100, 3), dtype=np.uint8)
    blur = Mock(wraps=cv2.GaussianBlur)
    monkeypatch.setattr(cv2, "GaussianBlur", blur)
    assert consumer._frame_changed(1, image)
    assert not consumer._frame_changed(1, image)
    assert sum(call.args[0].shape == image.shape for call in blur.call_args_list) == int(full_blur)


def test_capture_process_limits_own_opencv_threads(modules, monkeypatch):
    from AiVision.cameras import runtime

    calls = []
    if hasattr(runtime.os, "setsid"):
        monkeypatch.setattr(runtime.os, "setsid", lambda: None)
    monkeypatch.setattr(runtime.signal, "signal", lambda *_: None)
    monkeypatch.setattr(runtime.cv2, "setNumThreads", lambda count: calls.append(("threads", count)))
    camera = SimpleNamespace(_process_group_ready=Event(),
                             _capture_loop=lambda *args: calls.append(("capture", args)))
    runtime.CameraRuntime._capture_entry(camera, "active-index", "frame-seq")
    assert calls == [("threads", 1), ("capture", ("active-index", "frame-seq"))]


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


@pytest.mark.parametrize("feature", ["blocks", "security_fence", "tailgating"])
def test_status_elapsed_header_stops_before_sampling_validity(modules, monkeypatch, feature):
    from datetime import timezone

    from fastapi.testclient import TestClient
    from AiVision.api import app as app_module, deps
    from AiVision.api.status_timing import STATUS_ELAPSED_HEADER
    from AiVision.features.security_fence import service as fence_service
    from AiVision.features.security_fence.schema import FenceConfig
    from AiVision.features.tailgating import service as tailgating_service
    from AiVision.runtime import orchestrator as orchestrator_module

    elapsed_ns = 0
    origin = "https://monitor.example.test"
    now = time.time()
    camera = {"camera_id": 1, "shm_name": "camera_1", "name": "摄像头1", "enabled": True,
              "department": "general_electric", "functions": {feature: True}}

    def authenticate(_request):
        nonlocal elapsed_ns
        elapsed_ns += 230_500_000
        return user([feature])

    def read_camera(key, requested_feature, *, include_feature_config=False):
        nonlocal elapsed_ns
        assert requested_feature == feature
        assert include_feature_config is (feature == "security_fence")
        elapsed_ns += 90_400_000
        if key == "missing":
            return None
        result = dict(camera)
        if key == "outside":
            result["department"] = "electronics_electrician"
        if include_feature_config:
            result["feature_config"] = None if key == "unconfigured" else fence_config.model_dump()
        return result

    fence_config = FenceConfig(enable=True)

    def read_fence_config(_spec, _camera_id):
        nonlocal elapsed_ns
        elapsed_ns += 110_800_000
        return {"config": fence_config.model_dump()}

    def read_snapshot(key):
        nonlocal elapsed_ns
        assert key == "camera_1"
        elapsed_ns += 25_900_000
        return {"updated_at_s": now - 0.1, "count": 1, "pending_count": 0, "alarm": False,
                "persons": [], "events": [], "reason": "clear", "sample_interval_seconds": 0.1,
                "frame_width": 1920, "frame_height": 1080, "error": None,
                "mode": fence_service.current_mode(fence_config.value, datetime.now(timezone.utc))}

    def sample_validity():
        nonlocal elapsed_ns
        elapsed_ns += 200_000_000
        return now

    consumer = SimpleNamespace(running=True, config_cache={1: {"shm_name": "camera_1"}}, get_monitor_status=read_snapshot)
    orchestrator = object.__new__(modules[3])
    orchestrator.camera_runtime_manager = SimpleNamespace(is_running=lambda _key: True, list_running=lambda: ["camera_1"])
    orchestrator.consumers = {feature: consumer}
    service_module = {"blocks": orchestrator_module, "security_fence": fence_service, "tailgating": tailgating_service}[feature]
    monkeypatch.setattr(service_module, "time", SimpleNamespace(time=sample_validity))
    old_fence_lookup = Mock(side_effect=read_fence_config)
    monkeypatch.setattr(fence_service.feature_config_manager, "get_config", old_fence_lookup)
    monkeypatch.setattr(app_module, "get_current_user_from_request", authenticate)
    monkeypatch.setattr(app_module.time, "monotonic_ns", lambda: elapsed_ns)
    monkeypatch.setattr(app_module.settings.api, "cors_origins", [origin])
    app = app_module.create_app()
    lookup = Mock(side_effect=read_camera)
    old_camera_lookup = Mock(return_value=camera)
    app.dependency_overrides[deps.get_camera_config_manager] = lambda: SimpleNamespace(
        get_camera_for_status=lookup, get_camera=old_camera_lookup,
    )
    app.dependency_overrides[deps.get_current_orchestrator] = lambda: orchestrator
    app.dependency_overrides[deps.get_optional_orchestrator] = lambda: orchestrator
    app.dependency_overrides[deps.get_department_service] = lambda: SimpleNamespace(
        feature_access=lambda: {"general_electric": [feature]},
    )
    path = {"blocks": "features/blocks", "security_fence": "security-fence", "tailgating": "tailgating"}[feature]
    client = TestClient(app)
    try:
        response = client.get(f"/api/{path}/cameras/安检点位/status", headers={"Origin": origin})
        assert response.status_code == 200, response.text
        lookup.assert_called_once_with("安检点位", feature, include_feature_config=feature == "security_fence")
        assert response.headers[STATUS_ELAPSED_HEADER] == "346"
        assert response.headers["Cache-Control"] == "no-store"
        assert STATUS_ELAPSED_HEADER in response.headers["Access-Control-Expose-Headers"]
        result = response.json()
        assert result["camera_key"] == "camera_1" and result["online"] and result["count"] == 1
        assert result["valid_for_seconds"] == pytest.approx(4.9 if feature == "security_fence" else 1.9)
        assert client.get(f"/api/{path}/cameras/missing/status").status_code == 404
        assert client.get(f"/api/{path}/cameras/outside/status").status_code == 403
        if feature == "security_fence":
            disabled = client.get(f"/api/{path}/cameras/unconfigured/status")
            assert disabled.status_code == 200 and disabled.json()["state"] == "disabled"
            assert disabled.json()["valid_for_seconds"] == 0
        old_camera_lookup.assert_not_called()
        old_fence_lookup.assert_not_called()
        if feature == "security_fence":
            external = client.get("/api/external/security-fence/cameras/camera_1/status?department=general_electric")
            assert external.status_code == 200, external.text
            assert external.json() == result
            assert STATUS_ELAPSED_HEADER not in external.headers
            old_camera_lookup.assert_called_once_with("camera_1")
            assert old_fence_lookup.call_args.args[1] == 1

        monkeypatch.setattr(app_module, "get_current_user_from_request", lambda _request: user([]))
        denied = client.get(f"/api/{path}/cameras/camera_1/status")
        assert denied.status_code == 403
        assert STATUS_ELAPSED_HEADER not in denied.headers
    finally:
        client.close()


@pytest.mark.parametrize("phase,enabled,hour,weekdays,suppressed", [
    ("initial", True, 12, [4], False),
    ("initial", False, 12, [4], True),
    ("initial", True, 21, [4], True),
    ("evaluated", True, 12, [4], False),
    ("gated", False, 12, [4], True),
    ("gated", True, 7, [4], True),
    ("gated", True, 21, [4], True),
    ("gated", True, 12, [], True),
    ("gated", True, 12, [0], True),
])
def test_logistics_status_without_results_and_outside_schedule(
    modules, monkeypatch, phase, enabled, hour, weekdays, suppressed,
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth.auth import get_current_user
    from AiVision.api import deps
    from AiVision.api.routes import logistics_channels
    from AiVision.features.logistics_channel.runtime import LogisticsChannelRuntime
    from AiVision.features.logistics_channel.schema import LogisticsChannelDetailResponse
    from AiVision.features.logistics_channel.schedule import is_scheduled_time

    feature = "detect_logistics_single_person"
    now = datetime.fromisoformat(f"2026-11-13T{hour:02d}:00:00+08:00")
    channel = LogisticsChannelDetailResponse.model_validate({
        "id": 5, "name": "通道5", "feature_name": feature, "department": "general_electric",
        "enabled": enabled, "sort_order": 0, "config": {"schedule": {"weekdays": weekdays}},
        "members": [{"id": 1, "channel_id": 5, "camera_id": 11, "enabled": True, "sort_order": 0}],
    }).model_dump()
    service = Mock()
    service.get_channel.return_value = channel
    service.list_channels.return_value = {"items": [channel]}
    runtime = LogisticsChannelRuntime(
        channel_service=service, dispatcher=Mock(), camera_provider=lambda key: {"name": "相机11"},
        wall_time_provider=lambda: now, clock_provider=lambda: now.timestamp(), start_background=False,
    )
    if phase == "evaluated":
        runtime.evaluate(feature, 5)
    elif phase == "gated":
        # Consumer 的时段检查会覆盖汇总状态，轮询必须能直接读取该状态。
        runtime.evaluate(feature, 5)
        assert not runtime.camera_should_run(feature, 11)

    orchestrator = object.__new__(modules[3])
    orchestrator.logistics_channel_runtime = runtime
    monkeypatch.setattr(logistics_channels, "is_scheduled_time", lambda schedule: is_scheduled_time(schedule, now))
    app = FastAPI()
    app.include_router(logistics_channels.router)
    app.dependency_overrides[get_current_user] = lambda: user([feature])
    app.dependency_overrides[deps.get_logistics_channel_service] = lambda: service
    app.dependency_overrides[deps.get_current_orchestrator] = lambda: orchestrator
    with TestClient(app) as client:
        response = client.get(f"/api/logistics-channels/{feature}/5/status")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["reason"] == ("inactive" if phase == "gated" else "unknown")
    assert value["alarm"] is False
    assert value["alarm_suppressed"] is suppressed
    assert value["channel_id"] == 5 and value["department"] == "general_electric"
    assert value["duration_seconds"] == (0.0 if phase == "evaluated" else None)
    assert value["threshold_seconds"] is None


def test_logistics_snapshots_keep_updating_while_evidence_composition_is_slow(modules):
    from AiVision.features.logistics_channel.runtime import LogisticsChannelRuntime
    from AiVision.features.logistics_channel.schema import LogisticsChannelDetailResponse
    from AiVision.features.logistics_channel.state import CameraSnapshot

    feature = "detect_logistics_single_person"
    now = datetime.fromisoformat("2026-11-13T12:00:00+08:00")
    channel = LogisticsChannelDetailResponse.model_validate({
        "id": 5, "name": "通道5", "feature_name": feature, "department": "general_electric",
        "enabled": True, "sort_order": 0,
        "config": {"schedule": {"weekdays": [4]}, "multi_grace_seconds": 0},
        "members": [
            {"id": index, "channel_id": 5, "camera_id": index, "enabled": True, "sort_order": index}
            for index in (1, 2)
        ],
    }).model_dump()
    service = Mock()
    service.get_channel.return_value = channel
    service.list_channels.return_value = {"items": [channel]}
    composing = Event()
    release_compositor = Event()
    evidence_counts = Queue()

    def compose(tiles):
        composing.set()
        if not release_compositor.wait(5):
            raise RuntimeError("等待测试解除取证阻塞超时")
        evidence_counts.put((tuple(tile.person_count for tile in tiles), tiles[0].frame[0, 0, 0]))
        return np.zeros((10, 10, 3), dtype=np.uint8)

    evidence = Mock()
    evidence.should_sample.return_value = True
    dispatched = Queue()
    dispatcher = Mock()

    def dispatch(request, *, alarm_interval):
        dispatched.put(request)
        return True

    dispatcher.maybe_dispatch.side_effect = dispatch
    runtime = LogisticsChannelRuntime(
        channel_service=service, dispatcher=dispatcher, camera_provider=lambda key: {"name": f"相机{key}"},
        wall_time_provider=lambda: now, clock_provider=lambda: now.timestamp(),
        evidence_recorder=evidence, compositor=compose,
    )
    frame = np.full((10, 10, 3), 8, dtype=np.uint8)
    first_published = Event()

    def publish(camera_id, count):
        snapshot = CameraSnapshot(camera_id, count, now.timestamp(), camera_name=f"相机{camera_id}")
        runtime.update_camera_snapshot(feature, snapshot, frame)
        runtime.evaluate_after_camera_update(feature, camera_id)

    def publish_first():
        publish(1, 1)
        first_published.set()

    producer = Thread(target=publish_first, daemon=True)
    runtime.start()
    producer.start()
    try:
        assert composing.wait(2)
        assert first_published.wait(0.5), "取证阻塞了同一个检测线程"
        frame.fill(9)
        publish(2, 1)
        publish(2, 2)
        assert runtime.get_channel_status(feature, 5)["camera_counts"] == {"1": 1, "2": 2}
        dispatcher.maybe_dispatch.assert_not_called()
        release_compositor.set()
        assert evidence_counts.get(timeout=2) == ((1, None), 8)
        assert evidence_counts.get(timeout=2) == ((1, 2), 8)
        alarm = dispatched.get(timeout=2)
        assert alarm.metadata["camera_counts"] == {"1": 1, "2": 2}
        assert alarm.metadata["offending_camera_ids"] == [2]
    finally:
        release_compositor.set()
        producer.join(2)
        runtime.stop()

    assert runtime.get_channel_status(feature, 5) is None


def test_logistics_pipelines_participating_cameras_and_retires_changed_policy(modules):
    from dataclasses import replace
    from AiVision.features.logistics_channel.state import LogisticsDetectionConfig

    feature = "detect_logistics_single_person"
    spec = modules[2](feature)
    first_policy = LogisticsDetectionConfig(0.5, 0.55, 8, 0.1, 3.0, 0.2)
    policies = {1: first_policy, 2: first_policy, 3: first_policy}
    runtime = Mock()
    runtime.camera_should_run.side_effect = lambda _feature, camera_id: camera_id != 3
    runtime.detection_config_for_camera.side_effect = lambda _feature, camera_id: policies[camera_id]
    captured_at = time.time() - 0.1
    frames = {f"camera_{camera_id}": np.full((16, 16, 3), camera_id, dtype=np.uint8) for camera_id in (1, 2, 3)}
    consumer = spec.consumer_cls(
        spec=spec, infer_dict={}, result_queue=Queue(), latest_frames=frames,
        latest_frame_times={key: captured_at for key in frames}, is_camera_active=lambda _key: True,
        logistics_runtime=runtime,
    )
    for camera_id in (1, 2, 3):
        consumer.config_cache[camera_id] = {"shm_name": f"camera_{camera_id}", "roi_pos": []}
    old_requests = [Mock(), Mock()]
    replacement = Mock()
    consumer.submit_inference = Mock(side_effect=(*old_requests, replacement))
    consumer.cancel_inference = Mock()
    consumer.resolve_inference = Mock(return_value={"status": "ok", "detections": []})
    consumer.running = True

    consumer._before_camera_round()
    assert [call.args[0] for call in consumer.submit_inference.call_args_list] == [1, 2]
    consumer.resolve_inference.assert_not_called()
    frame, sample_time = consumer._processing_frame(1, "camera_1")
    frames["camera_1"] = np.zeros_like(frame)
    consumer.frame_cache[1], consumer._frame_sampled_at[1] = frame, sample_time
    result = consumer._process(consumer._get_roi(1, frame), 1)
    consumer.post_process(1, result)
    snapshot = runtime.update_camera_snapshot.call_args.args[1]
    assert snapshot.count == 0 and snapshot.updated_at == captured_at
    assert consumer.frame_cache[1][0, 0, 0] == 1
    assert consumer.resolve_inference.call_args.args == (old_requests[0],)

    frames["camera_1"] = frame
    policies[2] = replace(first_policy, confidence_threshold=0.7)
    consumer._before_camera_round()
    consumer.cancel_inference.assert_called_once_with(old_requests[1])
    assert consumer._samples[2].request is replacement
    assert consumer.submit_inference.call_args.args[3] == {"conf": 0.7, "iou": 0.55}
