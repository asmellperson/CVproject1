"""非法闯闸的持久化、部门授权、热更新与实时预览回归。"""
from contextlib import contextmanager
from queue import Queue
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "test",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path), "AUTO_CREATE_DB": "false",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def store(monkeypatch):
    from AiVision.core.db import Base
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.features._shared import config_manager as module
    from AiVision.features.tailgating.spec import SPEC

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory.begin() as session:
        session.add_all([AiCameraConfig(id=number, name=f"通道{number}", shm_name=f"camera_{number}",
                                       department=department, url="private-camera-source", enable=True)
                         for number, department in [(1, "general_electric"), (2, "electronics_electrician")]])

    @contextmanager
    def transaction():
        with factory.begin() as session:
            yield session

    calls = []
    monkeypatch.setattr(module, "get_session", factory)
    monkeypatch.setattr(module, "session_scope", transaction)
    monkeypatch.setattr(module.config_cache, "reload", lambda: calls.append("reload"))
    monkeypatch.setattr(module.config_event_bus, "publish", lambda event: calls.append(event))
    yield SimpleNamespace(manager=module.FeatureConfigManager(), spec=SPEC, factory=factory, calls=calls)
    engine.dispose()


def test_database_isolation_and_commit_before_cache_events(store):
    config = store.spec.config_schema().model_dump()
    config["enable"] = True
    store.manager.save_config(store.spec, "camera_1", config)
    config["value"]["overlap_seconds"] = 0.6
    store.manager.save_config(store.spec, "camera_2", config)
    assert store.manager.get_config(store.spec, "camera_1")["config"]["value"]["overlap_seconds"] == 0.3
    assert store.manager.get_config(store.spec, "camera_2")["config"]["value"]["overlap_seconds"] == 0.6
    assert store.calls[0] == "reload"
    assert store.calls[1].change_type == "tailgating_config_updated"
    assert store.calls[2].change_type == "tailgating_enabled"
    assert store.calls[1].camera_id == 1 and store.calls[4].camera_id == 2
    from AiVision.features._shared.config_manager import FeatureCameraScopeConflict
    with pytest.raises(FeatureCameraScopeConflict):
        store.manager.save_config(store.spec, "camera_1", config, expected_department="electronics_electrician")
    assert store.manager.get_config(store.spec, "camera_1")["config"]["value"]["overlap_seconds"] == 0.3


@pytest.mark.parametrize("role", ["admin", "viewer"])
def test_config_frame_and_status_cannot_borrow_other_department_access(store, role):
    from auth.auth import get_current_user
    from AiVision.api import deps
    from AiVision.api.routes.cameras import router as camera_router
    from AiVision.api.routes.features import create_features_router
    from AiVision.api.routes.tailgating import router as tailgating_router

    cameras = {f"camera_{number}": {"camera_id": number, "shm_name": f"camera_{number}", "name": f"通道{number}",
               "department": department, "enabled": True, "functions": {"tailgating": True}, "url": "private"}
               for number, department in [(1, "general_electric"), (2, "electronics_electrician")]}
    camera_manager = SimpleNamespace(get_camera=lambda key: cameras.get(key))
    user = {"role": role, "departments": ["general_electric", "electronics_electrician"],
            "feature_access": {"general_electric": ["tailgating"], "electronics_electrician": []}}
    orchestrator = SimpleNamespace(camera_runtime_manager=SimpleNamespace(is_running=lambda key: True), consumers={})
    app = FastAPI()
    app.include_router(create_features_router(store.manager, camera_manager))
    app.include_router(camera_router)
    app.include_router(tailgating_router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[deps.get_camera_config_manager] = lambda: camera_manager
    app.dependency_overrides[deps.get_current_orchestrator] = lambda: orchestrator
    app.dependency_overrides[deps.get_optional_orchestrator] = lambda: orchestrator
    with TestClient(app) as client:
        assert client.get("/api/features/tailgating/configs/camera_1").status_code == 200
        assert client.get("/api/tailgating/cameras/camera_1/status").status_code == 200
        for path in ("/api/features/tailgating/configs/camera_2", "/api/cameras/camera_2/frame.jpg?feature=tailgating",
                     "/api/tailgating/cameras/camera_2/status"):
            assert client.get(path).status_code == 403
        if role == "viewer":
            assert client.put("/api/features/tailgating/configs/camera_1", json=store.spec.config_schema().model_dump()).status_code == 403


@pytest.fixture
def consumer(monkeypatch):
    from AiVision.core.cache import config_cache
    from AiVision.features.tailgating.consumer import TailgatingConsumer
    from AiVision.features.tailgating.spec import SPEC
    from AiVision.features.tailgating.schema import TailgatingValue

    value = TailgatingValue(roi_pos=[[0.05, 0.05], [0.95, 0.05], [0.95, 0.95], [0.05, 0.95]],
                           line_points=[[0.1, 0.5], [0.9, 0.5]], foot_ratio=1.0)
    configs = {number: {**value.model_dump(), "enable": True, "camera_enable": True, "shm_name": f"camera_{number}",
                       "department": department, "name": f"通道{number}", "sql_enable": True}
               for number, department in [(1, "general_electric"), (2, "electronics_electrician")]}
    monkeypatch.setattr(config_cache, "get_all_function_configs", lambda: {(key, "tailgating"): cfg for key, cfg in configs.items()})
    monkeypatch.setattr(config_cache, "get_function_config", lambda camera_id, feature: configs.get(camera_id))
    result = TailgatingConsumer(SPEC, {}, Queue(), {}, lambda key: True)
    result._load_initial_configs()
    return SimpleNamespace(value=result, configs=configs)


def test_live_frames_status_and_hot_updates_are_camera_local(consumer):
    camera = consumer.value
    raw = np.full((200, 200, 3), 7, dtype=np.uint8)
    camera.frame_cache[1] = raw
    detail = {"persons": [], "events": [], "count": 0, "alarm": False, "reason": "clear", "error": None,
              "sample_interval_seconds": 0.2, "frame_width": 200, "frame_height": 200, "updated_at_s": 100.0}
    camera.post_process(1, (False, detail))
    detail["count"] = 99
    assert camera.get_monitor_status("camera_1")["count"] == 0
    assert camera.get_monitor_status("camera_2") is None
    camera.update_config(2)
    assert camera.get_monitor_status("camera_1")["count"] == 0
    camera.update_config(1)
    assert camera.get_monitor_status("camera_1") is None
    assert camera.get_live_preview("camera_1", raw, now=100.0)[160, 150].tolist() == [7, 7, 7]
    camera.update_status(1, False)
    assert camera.get_live_preview("camera_1", raw, now=100.0) is None
    assert camera.get_live_preview("camera_2", raw, now=100.0) is not None
    camera.update_status(1, True)
    camera.remove_camera(1, "camera_1")
    assert camera.get_live_preview("camera_1", raw, now=100.0) is None


def test_physical_camera_disable_clears_preview_without_affecting_other_cameras(consumer):
    camera = consumer.value
    consumer.configs[1]["camera_enable"] = False
    camera.update_config(1)
    assert camera.get_live_preview("camera_1", np.zeros((200, 200, 3), dtype=np.uint8), now=100.0) is None
    assert 1 not in camera.runtimes and 2 in camera.runtimes
    consumer.configs[1]["camera_enable"] = True
    camera.update_config(1)
    assert camera.get_live_preview("camera_1", np.zeros((200, 200, 3), dtype=np.uint8), now=100.0) is not None


def test_preview_and_status_do_not_wait_for_inference_lock(consumer):
    class InferenceLock:
        def __enter__(self):
            raise AssertionError("实时画面和状态不能等待推理锁")

        def __exit__(self, *args):
            return False

    camera = consumer.value
    camera._camera_state_lock = InferenceLock()
    assert camera.get_monitor_status("camera_1") is None
    assert camera.get_live_preview("camera_1", np.zeros((200, 200, 3), dtype=np.uint8), now=100.0) is not None


def test_each_pair_dispatches_once_and_departments_are_preserved(consumer, monkeypatch):
    from AiVision.features.tailgating import consumer as module

    camera = consumer.value
    requests = []
    monkeypatch.setattr(module.alarm_dispatcher, "maybe_dispatch", lambda request, **kwargs: requests.append(request) or True)
    for camera_id in (1, 2):
        state = camera.runtimes[camera_id]
        for now, y in [(0.0, 0.4), (0.2, 0.45), (0.4, 0.55)]:
            detections = [{"bbox": [x - 12, y * 200 - 70, x + 12, y * 200]} for x in (60, 140)]
            detail = state.update(detections, (200, 200, 3), now=now)
        camera._handle_alarm(camera_id, (True, detail), None)
        camera._handle_alarm(camera_id, (True, detail), None)
    assert len(requests) == 2
    assert [request.department for request in requests] == ["general_electric", "electronics_electrician"]
    assert [request.camera_id for request in requests] == [1, 2]
    assert all(request.feature_name == "tailgating" and request.violation_type == 17 for request in requests)
    assert requests[0].cooldown_subject_id != requests[1].cooldown_subject_id


def test_inference_failure_clears_pending_evidence_and_duplicate_frames_are_skipped(consumer, monkeypatch):
    from AiVision.features.tailgating import consumer as module

    camera = consumer.value
    clock = SimpleNamespace(time=lambda: 100.0, monotonic=lambda: 1.0)
    monkeypatch.setattr(module, "time", clock)
    monkeypatch.setattr(camera, "dispatch_inference_sync", lambda *args, **kwargs: {"status": "timeout", "error_message": "模型等待超时"})
    raw = np.zeros((200, 200, 3), dtype=np.uint8)
    camera.latest_frames["camera_1"] = raw
    assert camera._should_process_now(1, consumer.configs[1])
    alarm, detail = camera._process(raw, 1)
    assert not alarm and detail["count"] is None and detail["reason"] == "inference_error"
    assert not camera._should_process_now(1, consumer.configs[1])
    assert camera.runtimes[1].last_frame_at is None
    camera.latest_frames["camera_1"] = raw.copy()
    assert camera._should_process_now(1, consumer.configs[1])


def test_unconfigured_camera_keeps_live_preview_without_running_inference(consumer, monkeypatch):
    camera = consumer.value
    consumer.configs[1]["line_points"] = []
    camera.update_config(1)
    monkeypatch.setattr(camera, "dispatch_inference_sync", lambda *args, **kwargs: pytest.fail("未配置计数线不应运行模型"))
    raw = np.zeros((200, 200, 3), dtype=np.uint8)
    assert camera._process(raw, 1)[1]["reason"] == "unconfigured"
    assert camera.get_live_preview("camera_1", raw, now=100.0) is not None


def test_preview_expiry_changes_boxes_but_keeps_capturing_latest_picture(consumer):
    camera = consumer.value
    raw = np.full((200, 200, 3), 7, dtype=np.uint8)
    camera.frame_cache[1] = raw
    detail = {"persons": [{"track_id": 1, "bbox": [20, 20, 60, 60], "in_roi": True, "direction": 1}],
              "events": [], "count": 1, "alarm": False, "reason": "clear", "error": None,
              "sample_interval_seconds": 0.2, "frame_width": 200, "frame_height": 200, "updated_at_s": 100.0}
    camera.post_process(1, (False, detail))
    assert camera.get_live_preview("camera_1", raw, now=100.5)[40, 20].tolist() == [60, 200, 80]
    assert camera.get_live_preview("camera_1", np.full_like(raw, 25), now=102.0)[40, 20].tolist() == [25, 25, 25]


def test_config_removed_during_render_cannot_publish_an_old_preview(consumer, monkeypatch):
    from AiVision.features.tailgating import consumer as module

    camera = consumer.value
    raw = np.zeros((200, 200, 3), dtype=np.uint8)
    def disable(frame, entry, *, now):
        camera.update_status(1, False)
        return frame
    monkeypatch.setattr(module, "render_preview", disable)
    assert camera.get_live_preview("camera_1", raw, now=100.0) is None


def test_status_expiry_and_failure_never_report_clear_passage(consumer, monkeypatch):
    from AiVision.features.tailgating import service

    camera = consumer.value
    info = {"shm_name": "camera_1", "name": "通道1", "department": "general_electric", "enabled": True,
            "functions": {"tailgating": True}}
    orchestrator = SimpleNamespace(camera_runtime_manager=SimpleNamespace(is_running=lambda key: True), consumers={"tailgating": camera})
    monkeypatch.setattr(service, "time", SimpleNamespace(time=lambda: 100.0))
    assert service.camera_status(info, orchestrator).state == "waiting"
    raw = np.zeros((200, 200, 3), dtype=np.uint8)
    camera.frame_cache[1] = raw
    detail = {"persons": [], "events": [], "count": None, "alarm": False, "reason": "inference_error",
              "error": "模型不可用", "sample_interval_seconds": None, "frame_width": 200, "frame_height": 200, "updated_at_s": 100.0}
    camera.post_process(1, (False, detail))
    assert service.camera_status(info, orchestrator).state == "error"
    monkeypatch.setattr(service, "time", SimpleNamespace(time=lambda: 103.0))
    stale = service.camera_status(info, orchestrator)
    assert stale.state == "stale" and stale.count is None and not stale.alarm


def test_camera_restart_event_also_refreshes_feature_state(consumer):
    from AiVision.core.events import ConfigChangeEvent
    from AiVision.runtime.orchestrator import Orchestrator

    platform = Orchestrator.__new__(Orchestrator)
    platform.consumers = {"tailgating": consumer.value}
    platform.logistics_channel_runtime = SimpleNamespace(refresh_camera_all=lambda camera_id: None)
    platform.refresh_guard_camera = lambda camera_id: None
    platform._camera_update_requires_restart = lambda event: True
    restarted = []
    platform._restart_or_stop_camera = restarted.append
    consumer.configs[1]["camera_enable"] = False
    platform._handle_runtime_config_change(ConfigChangeEvent(change_type="camera_updated", camera_id=1, camera_name="camera_1"))
    assert restarted == ["camera_1"]
    assert consumer.value.get_live_preview("camera_1", np.zeros((200, 200, 3), dtype=np.uint8), now=100.0) is None
    assert 2 in consumer.value.runtimes


def test_third_person_joining_the_same_active_event_does_not_repeat_notification(consumer, monkeypatch):
    from AiVision.features.tailgating import consumer as module

    camera = consumer.value
    requests = []
    monkeypatch.setattr(module.alarm_dispatcher, "maybe_dispatch", lambda request, **kwargs: requests.append(request) or True)
    state = camera.runtimes[1]
    first_id = None
    for now, heights in [(0.0, [0.4, 0.4]), (0.2, [0.45, 0.45]), (0.4, [0.55, 0.55]),
                         (0.6, [0.6, 0.6, 0.4]), (0.8, [0.65, 0.65, 0.45]), (1.0, [0.7, 0.7, 0.55])]:
        detections = [{"bbox": [x - 12, y * 200 - 70, x + 12, y * 200]} for x, y in zip((40, 100, 160), heights)]
        detail = state.update(detections, (200, 200, 3), now=now)
        camera._handle_alarm(1, (bool(detail["events"]), detail), None)
        if now == 0.4:
            first_id = detail["events"][0]["id"]
    assert len(requests) == 1
    assert detail["events"][0]["id"] == first_id
    assert len(detail["events"][0]["track_ids"]) == 3


def test_registered_app_and_overview_expose_the_same_feature_catalog():
    from AiVision.api.app import app
    from AiVision.features.registry import all_specs
    from AiVision.runtime.overview import FEATURE_PAGES

    schema = app.openapi()
    assert "/api/tailgating/cameras/{key}/status" in schema["paths"]
    assert "TailgatingStatus" in schema["components"]["schemas"]
    assert set(all_specs()) == set(FEATURE_PAGES)
    assert all_specs()["tailgating"].alarm_types == (17,)
