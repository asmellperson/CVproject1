"""原生 API 使用真实数据 Service，验证授权、事务结果及运行时刷新边界。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import anyio.to_thread
import httpx
import numpy as np
import pytest
from fastapi import FastAPI

from AiVision.api.routes import guard_behavior as api
from AiVision.features.guard_behavior.state import CameraAvailability, SiteEvaluation, SiteRuleDecision
from AiVision.tests.test_guard_behavior_data import data_db, DEPARTMENT, OTHER_DEPARTMENT  # noqa: F401


@pytest.fixture
def client(data_db, monkeypatch):  # noqa: F811
    # 内存 SQLite 的连接留在同一线程；请求仍经过完整 FastAPI 校验和依赖链。
    async def inline(func, *args, **kwargs):
        return func(*args)
    monkeypatch.setattr(anyio.to_thread, "run_sync", inline)
    app = FastAPI()
    app.include_router(api.router)
    state = SimpleNamespace(user={"role": "admin"}, runtime=SimpleNamespace(
        running=False, reload_site=Mock(), get_site_status=Mock(return_value=None),
        get_site_frame=Mock(return_value=None)))
    app.dependency_overrides[api.get_current_user] = lambda: state.user
    app.dependency_overrides[api.get_guard_behavior_service] = lambda: data_db.service
    app.dependency_overrides[api.get_guard_behavior_runtime] = lambda: state.runtime

    def request(method, path, payload=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                return await http.request(method, f"/api/guard-behavior{path}", json=payload)
        return asyncio.run(run())
    state.request = request
    state.site = data_db.service.create_site("南门", DEPARTMENT)["id"]
    state.camera = data_db.camera()
    state.db = data_db
    return state


def test_site_crud_and_every_configuration_mutation_reload(client):
    c = client
    response = c.request("POST", "/sites", {"name": "北门", "department": DEPARTMENT,
                                           "enabled": False, "sort_order": 3})
    assert response.status_code == 201
    created = response.json()
    assert created["enabled"] is False and created["sort_order"] == 3
    assert len(c.db.service.list_alarm_policies(created["id"])) == 4
    c.runtime.reload_site.assert_called_once_with(created["id"])
    mutations = [
        ("PATCH", f"/sites/{c.site}", {"name": "南门更新", "sort_order": 2}),
        ("POST", f"/sites/{c.site}/cameras", {"camera_id": c.camera}),
        ("PUT", f"/sites/{c.site}/cameras/order", {"camera_ids": [c.camera]}),
        ("PUT", f"/sites/{c.site}/cameras/{c.camera}/enabled", {"enabled": False}),
        ("PATCH", f"/sites/{c.site}/policy", {"phone_seconds": 5.}),
        ("PUT", f"/sites/{c.site}/cameras/{c.camera}/roi", {"vehicle_roi_pos": [[0., 0.], [1., 0.], [1., 1.]]}),
        ("PATCH", f"/sites/{c.site}/alarm-policies/9", {"alarm_interval": 70., "sql_enable": True}),
        ("DELETE", f"/sites/{c.site}/cameras/{c.camera}", None),
        ("DELETE", f"/sites/{c.site}", None),
    ]
    for method, path, payload in mutations:
        c.runtime.reload_site.reset_mock()
        response = c.request(method, path, payload)
        assert response.status_code in (200, 201), response.text
        c.runtime.reload_site.assert_called_once_with(c.site)


READ_PATHS = ("", "/cameras", "/policy", "/cameras/{camera}/roi", "/alarm-policies", "/status", "/frame.jpg")


@pytest.mark.parametrize("suffix", READ_PATHS)
def test_read_permission_is_scoped_by_site_department(client, suffix):
    c = client
    c.db.service.add_camera(c.site, c.camera)
    path = f"/sites/{c.site}" + suffix.format(camera=c.camera)
    c.user = {"role": "viewer", "departments": [OTHER_DEPARTMENT]}
    assert c.request("GET", path).status_code == 403
    c.user = {"role": "viewer", "departments": [DEPARTMENT]}
    assert c.request("GET", path).status_code == (503 if suffix == "/frame.jpg" else 200)


@pytest.mark.parametrize("method,suffix,payload", [
    ("POST", "/sites", {"name": "新建", "department": DEPARTMENT}),
    ("PATCH", "/sites/{site}", {"name": "修改"}),
    ("DELETE", "/sites/{site}", None),
    ("POST", "/sites/{site}/cameras", {"camera_id": 1}),
    ("PUT", "/sites/{site}/cameras/order", {"camera_ids": []}),
    ("PUT", "/sites/{site}/cameras/1/enabled", {"enabled": False}),
    ("DELETE", "/sites/{site}/cameras/1", None),
    ("PATCH", "/sites/{site}/policy", {"phone_seconds": 5.}),
    ("PUT", "/sites/{site}/cameras/1/roi", {"vehicle_roi_pos": []}),
    ("PATCH", "/sites/{site}/alarm-policies/8", {"sql_enable": True}),
])
def test_all_writes_require_admin(client, method, suffix, payload):
    client.user = {"role": "viewer", "departments": [DEPARTMENT]}
    assert client.request(method, suffix.format(site=client.site), payload).status_code == 403
    client.runtime.reload_site.assert_not_called()


def test_site_list_filters_departments_and_rejects_unauthorized_query(client):
    c = client
    c.db.service.create_site("其他事业部", OTHER_DEPARTMENT)
    c.user = {"role": "viewer", "departments": [DEPARTMENT]}
    assert [site["id"] for site in c.request("GET", "/sites").json()] == [c.site]
    assert c.request("GET", f"/sites?department={OTHER_DEPARTMENT}").status_code == 403
    assert c.request("GET", "/sites?department=invalid").status_code == 400
    c.user = {"role": "viewer", "departments": []}
    assert c.request("GET", "/sites").json() == []


def test_camera_binding_uses_existing_physical_camera_and_native_validation(client):
    c = client
    path = f"/sites/{c.site}/cameras"
    assert c.request("POST", path, {"name": "私有摄像头", "rtsp": "rtsp://invalid"}).status_code == 422
    assert c.request("POST", path, {"camera_id": 9999}).status_code == 404
    other_camera = c.db.camera(OTHER_DEPARTMENT)
    assert c.request("POST", path, {"camera_id": other_camera}).status_code == 400
    assert c.request("POST", path, {"camera_id": c.camera}).status_code == 201
    assert c.request("POST", path, {"camera_id": c.camera}).status_code == 409
    assert c.request("PUT", f"{path}/{c.camera}/roi", {"vehicle_roi_pos": [[0., 0.], [100., 0.], [1., 1.]]}).status_code == 422
    assert c.request("PATCH", f"/sites/{c.site}/policy", {"vehicle_inspection_enabled": True}).status_code == 400
    assert c.request("PATCH", f"/sites/{c.site}/alarm-policies/12", {"sql_enable": True}).status_code == 400
    assert c.request("PATCH", f"/sites/{c.site}", {"department": OTHER_DEPARTMENT}).status_code == 422


@pytest.mark.parametrize("runtime_exists", [False, True])
def test_missing_runtime_data_is_explicitly_unavailable(client, runtime_exists):
    if not runtime_exists:
        client.runtime = None
    else:
        client.runtime.running = True
    result = client.request("GET", f"/sites/{client.site}/status")
    assert result.status_code == 200
    assert result.json()["status"] == "unavailable"
    assert result.json()["absence"]["state"] == "unknown"
    assert client.request("GET", f"/sites/{client.site}/frame.jpg").status_code == 503
    assert client.request("PATCH", f"/sites/{client.site}", {"name": "可配置"}).status_code == 200


def test_live_status_and_jpeg_use_injected_runtime(client):
    c = client
    decision = SiteRuleDecision("available", "normal", "正常")
    c.runtime.running = True
    c.runtime.get_site_status.return_value = SiteEvaluation(
        "healthy", {c.camera: CameraAvailability.READY}, decision, decision, decision, decision, 100.)
    c.runtime.get_site_frame.return_value = np.zeros((20, 30, 3), dtype=np.uint8)
    result = c.request("GET", f"/sites/{c.site}/status").json()
    assert result["camera_states"][str(c.camera)] == "READY" and result["running"]
    response = c.request("GET", f"/sites/{c.site}/frame.jpg")
    assert response.status_code == 200 and response.content[:2] == b"\xff\xd8"
    assert response.headers["cache-control"] == "no-store"
    assert c.request("GET", f"/sites/{c.site}/frame.jpg?quality=999").status_code == 422


def test_reload_failure_does_not_claim_transaction_was_rolled_back(client):
    client.runtime.reload_site.side_effect = RuntimeError("refresh failed")
    response = client.request("PATCH", f"/sites/{client.site}", {"name": "已保存"})
    assert response.status_code == 503 and "配置已保存" in response.json()["detail"]
    assert client.db.service.get_site(client.site)["name"] == "已保存"


def test_router_contains_no_control_endpoints():
    assert not any(route.path.endswith(("/start", "/stop", "/restart")) for route in api.router.routes)


def test_orchestrator_constructs_before_configure_and_stops_before_evidence(monkeypatch):
    from AiVision.runtime import orchestrator as module
    from AiVision.features.guard_behavior.runtime import GuardBehaviorSiteRuntime
    from AiVision.core import db
    calls = []
    evidence = Mock()
    evidence.stop.side_effect = lambda: calls.append("evidence_stop")
    dispatcher = Mock(evidence_recorder=None)
    def configure(**kwargs):
        calls.append("configure")
        dispatcher.evidence_recorder = kwargs["evidence_recorder"]
    dispatcher.configure.side_effect = configure
    service = Mock()
    service.list_runtime_site_configs.return_value = []
    def runtime(**kwargs):
        assert kwargs["dispatcher"].evidence_recorder is None
        obj = GuardBehaviorSiteRuntime(**kwargs, start_background=False)
        start, stop = obj.start, obj.stop
        def start_observed():
            calls.append("guard_start")
            start()
        def stop_observed():
            calls.append("guard_stop")
            stop()
        obj.start, obj.stop = start_observed, stop_observed
        return obj
    monkeypatch.setattr(module, "GuardBehaviorSiteRuntime", runtime)
    monkeypatch.setattr(module, "GuardBehaviorService", lambda: service)
    monkeypatch.setattr(module, "alarm_dispatcher", dispatcher)
    monkeypatch.setattr(module, "alarm_evidence_recorder", evidence)
    monkeypatch.setattr(module, "CameraRuntimeManager", lambda _: Mock())
    monkeypatch.setattr(module, "LogisticsChannelRuntime", lambda **kwargs: Mock())
    monkeypatch.setattr(module, "config_event_bus", Mock())
    monkeypatch.setattr(module, "config_cache", Mock())
    monkeypatch.setattr(module, "frame_reader_registry", Mock())
    monkeypatch.setattr(module, "violation_writer", Mock())
    monkeypatch.setattr(module, "horn_runtime_manager", Mock())
    monkeypatch.setattr(module, "camera_config_manager", Mock(list_cameras=Mock(return_value=[])))
    monkeypatch.setattr(module, "inference_runtime_manager", Mock())
    monkeypatch.setattr(module, "cleanup_aivision_residual_processes", lambda **kwargs: 0)
    monkeypatch.setattr(module.Orchestrator, "_start_consumers", lambda self: None)
    monkeypatch.setattr(db, "dispose", lambda: None)
    obj = module.Orchestrator(None)
    assert not obj.guard_behavior_runtime.running
    obj.start()
    assert obj.guard_behavior_runtime.running
    obj.stop()
    assert calls == ["configure", "guard_start", "guard_stop", "evidence_stop"]
    assert not obj.guard_behavior_runtime.running


def test_application_registers_native_router_without_registering_feature():
    from AiVision.api.app import app
    from AiVision.features.registry import all_specs
    from AiVision.alarms.types import VIOLATION_TYPE_META
    from AiVision.inference.runtime_manager import InferenceRuntimeManager
    assert any(route.path == "/api/guard-behavior/sites" for route in app.routes)
    assert "guard_behavior" not in all_specs()
    assert set(VIOLATION_TYPE_META) == set(range(1, 8))
    assert not {"yolo_guard_person_phone", "guard_uniform", "yolo_guard_pose", "yolo_vehicle"}.intersection(
        InferenceRuntimeManager()._declared_model_names())
