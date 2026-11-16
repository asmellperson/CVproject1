"""烟雾设备接口的资源授权、真实配置与连接状态回归，不访问现场设备。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def api(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "smoke_test",
        "MYSQL_DB_PASSWORD": "smoke_test", "MYSQL_DB_NAME": "smoke_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "smoke-test-signing-key-0000000000",
    }.items():
        monkeypatch.setenv(name, value)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth.auth import get_current_user
    from AiVision.api.routes import smoke_detection as routes
    from AiVision.features.smoke_detection.schema import SmokeConfigSchema

    user = {"role": "admin", "feature_access": {"general_electric": ["smoke_detection"]}}
    camera = {"camera_id": 1, "shm_name": "camera_1", "name": "烟雾摄像头", "enabled": True,
              "department": "general_electric", "url": "rtsp://test:fake-secret@192.0.2.10/Streaming/Channels/101"}
    config = SmokeConfigSchema().model_dump()
    lookup = Mock(return_value={"camera": camera, "config": config})
    monkeypatch.setattr(routes.feature_config_manager, "get_config", lookup)
    manager = SimpleNamespace(get_camera=Mock(return_value=camera))
    parameters = {"supported": True, "channel_id": 1, "parameters": []}
    shields = {"supported": False, "channel_id": 1}
    service = SimpleNamespace(parameters=Mock(return_value=parameters), save_parameters=Mock(return_value=parameters),
                              shields=Mock(return_value=shields), save_shields=Mock(return_value=shields),
                              picture=Mock(return_value=b"test-picture"))
    consumer = SimpleNamespace(running=True, get_monitor_status=Mock(return_value={
        "connection_state": "connected", "alarm_state": "unknown", "alarm": False,
        "valid_for_seconds": 20, "message": "已连接，等待设备事件",
    }))
    runtime = SimpleNamespace(consumers={"smoke_detection": consumer},
                              camera_runtime_manager=SimpleNamespace(list_running=lambda: ["camera_1"]))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[routes.get_camera_config_manager] = lambda: manager
    app.dependency_overrides[routes.get_smoke_device_service] = lambda: service
    app.dependency_overrides[routes.get_current_orchestrator] = lambda: runtime
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, user=user, camera=camera, config=config, lookup=lookup,
                              manager=manager, service=service, runtime=runtime, consumer=consumer, routes=routes)


def url(resource, department="general_electric"):
    return f"/api/smoke/camera_1/{resource}?department={department}"


@pytest.mark.parametrize("resource", ["parameters", "shields", "picture"])
def test_viewer_cannot_access_device_configuration(api, resource):
    api.user.update(role="viewer", departments=["general_electric"])
    assert api.client.get(url(resource)).status_code == 403
    getattr(api.service, resource).assert_not_called()


def test_department_admin_can_only_access_own_assigned_camera(api):
    api.user.update(role="department_admin", departments=["general_electric"])
    assert api.client.get(url("parameters")).status_code == 200
    api.service.parameters.reset_mock()
    api.camera["department"] = "electronics_electrician"
    api.user["feature_access"]["electronics_electrician"] = ["smoke_detection"]
    assert api.client.get(url("parameters", "electronics_electrician")).status_code == 403
    assert api.client.get(url("parameters")).status_code == 403
    api.service.parameters.assert_not_called()


def test_department_disabled_and_missing_resources_stop_before_device_access(api):
    assert api.client.get(url("parameters", "electronics_electrician")).status_code == 403
    api.camera["enabled"] = False
    assert api.client.get(url("parameters")).status_code == 409
    api.camera["enabled"] = True
    api.lookup.return_value = None
    assert api.client.get(url("parameters")).status_code == 404
    api.manager.get_camera.return_value = None
    assert api.client.get(url("parameters")).status_code == 404
    api.service.parameters.assert_not_called()


def test_parameters_use_database_target_and_never_return_credentials(api):
    result = api.client.put(url("parameters"), json={"values": {"sensitivity": 75}})
    assert result.status_code == 200
    assert "fake-secret" not in result.text and "192.0.2.10" not in result.text
    camera, config, update = api.service.save_parameters.call_args.args
    assert camera is api.camera and config is api.config and update.values == {"sensitivity": 75}
    assert api.client.put(url("parameters"), json={"values": {"sensitivity": 75}, "url": "http://other.test"}).status_code == 422


def test_safe_device_failure_is_reported_without_claiming_saved(api):
    from AiVision.features.smoke_detection.device import SmokeDeviceError
    api.service.save_parameters.side_effect = SmokeDeviceError("设备参数回读未确认", 409)
    result = api.client.put(url("parameters"), json={"values": {"sensitivity": 75}})
    assert result.status_code == 409 and result.json()["detail"] == "设备参数回读未确认"


def test_device_picture_uses_configured_channel_and_is_not_cached(api):
    result = api.client.get(url("picture"))
    assert result.status_code == 200 and result.content == b"test-picture"
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["content-type"] == "image/jpeg"
    assert api.service.picture.call_args.args == (api.camera, api.config)


def test_monitor_viewer_can_read_status_without_equating_waiting_with_clear(api):
    api.user.update(role="viewer", departments=["general_electric"])
    result = api.client.get(url("status"))
    assert result.status_code == 200
    assert result.json()["connection_state"] == "connected"
    assert result.json()["alarm"] is None and result.json()["alarm_state"] == "unknown"
    assert result.json()["online"] is True
    api.service.parameters.assert_not_called()


@pytest.mark.parametrize("connection,expected", [("connected", True), ("disconnected", None), ("error", None)])
def test_alarm_state_is_unknown_when_device_connection_fails(api, connection, expected):
    api.consumer.get_monitor_status.return_value = {"connection_state": connection, "alarm_state": "active", "alarm": True}
    state = api.client.get(url("status")).json()
    assert state["alarm"] is expected
    assert state["alarm_state"] == ("active" if connection == "connected" else "unknown")


def test_unstarted_consumer_is_disabled_and_does_not_connect_to_device(api):
    api.runtime.consumers.clear()
    state = api.client.get(url("status")).json()
    assert state["connection_state"] == "disabled" and state["alarm"] is None
    assert state["valid_for_seconds"] == 0
    api.service.parameters.assert_not_called()
