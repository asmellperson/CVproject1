"""外部数据和图片直链无需凭证，业务范围及平台登录仍按各自规则校验。"""

from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def external_api(monkeypatch, tmp_path):
    # 隔离数据库、采集和推理服务，只验证正式应用的路由、响应与访问边界。
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "tests", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "tests", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)

    from AiVision.api import deps
    from AiVision.api.app import create_app
    from AiVision.api.routes.external import security_fence, security_inspection
    from AiVision.features.security_inspection.schema import InspectionConfig
    from auth.external_store import external_client_store

    camera = {
        "id": "camera_1", "camera_id": 1, "name": "入口", "shm_name": "camera_1",
        "department": "general_electric", "enabled": True, "fps": 5, "sort_order": 0,
        "feature_sort_orders": {}, "functions": {"security_inspection": True, "security_fence": True},
    }
    other_camera = {**camera, "id": "camera_2", "camera_id": 2, "shm_name": "camera_2",
                    "department": "electronics_electrician"}
    cameras = {row["shm_name"]: row for row in (camera, other_camera)}
    catalog = Mock()
    catalog.feature_access.return_value = {
        "general_electric": ["security_inspection", "security_fence"],
        "electronics_electrician": ["security_fence"],
        "electrical_components": ["security_inspection"],
    }
    camera_manager = Mock()
    camera_manager.get_camera.side_effect = cameras.get
    camera_manager.list_cameras.return_value = list(cameras.values())
    pixels = np.zeros((48, 96, 3), dtype=np.uint8)
    orchestrator = Mock()
    orchestrator.get_camera_frame_info.return_value = (pixels, 1.0)
    inspection_service = Mock()
    inspection_service.image.return_value = (cv2.imencode(".jpg", pixels)[1].tobytes(), "image/jpeg")
    inspection_service.history.return_value = {
        "stats": {"total": 0, "compliant": 0, "non_compliant": 0, "error": 0, "cancelled": 0, "rate": 0},
        "items": [], "retention_days": 31,
    }
    config = InspectionConfig().model_dump(mode="json")
    config_response = {
        "camera": {"id": 1, "name": "入口", "shm_name": "camera_1", "enable": True},
        "feature": "security_inspection", "config": config,
    }
    config_manager = Mock()
    config_manager.get_config.return_value = config_response
    config_manager.save_config.return_value = config_response
    horns = Mock()
    horns.list_horns.return_value = [{"id": 1, "name": "入口喇叭", "enable": True}]
    fence_status = {
        "camera_id": 1, "camera_key": "camera_1", "camera_name": "入口", "department": "general_electric",
        "online": False, "state": "offline", "mode": "whitelist", "timezone": "Asia/Shanghai",
    }
    alarm = {
        "id": "1", "camera_key": "camera_1", "camera_name": "入口", "department": "general_electric",
        "reason": "unauthorized", "created_at": "2026-10-22T00:00:00+00:00", "person": None,
        "image_url": "/api/external/security-fence/alarms/1/image?department=general_electric",
    }
    image_path = tmp_path / "alarm.png"
    image_path.write_bytes(cv2.imencode(".png", pixels)[1].tobytes())
    monkeypatch.setattr(security_fence.service, "camera_status", Mock(return_value=fence_status))
    monkeypatch.setattr(security_fence.service, "history", Mock(return_value={
        "total": 1, "by_reason": {"unauthorized": 1}, "items": [alarm],
    }))
    monkeypatch.setattr(security_fence.service, "alarm_detail", Mock(return_value=alarm))
    monkeypatch.setattr(security_fence.service, "alarm_image", Mock(return_value=image_path))
    authenticate = Mock(side_effect=AssertionError("外部接口不应读取调用凭证"))
    monkeypatch.setattr(external_client_store, "authenticate", authenticate)

    app = create_app()
    app.dependency_overrides.update({
        deps.get_department_service: lambda: catalog,
        deps.get_camera_config_manager: lambda: camera_manager,
        deps.get_current_orchestrator: lambda: orchestrator,
        deps.get_optional_orchestrator: lambda: orchestrator,
        deps.get_inspection_consumer: lambda: None,
        deps.get_inspection_service: lambda: inspection_service,
        deps.get_horn_service: lambda: horns,
        security_inspection.get_config_manager: lambda: config_manager,
    })
    yield SimpleNamespace(
        client=TestClient(app), app=app, config=config, config_manager=config_manager,
        inspection_service=inspection_service, authenticate=authenticate,
    )
    authenticate.assert_not_called()


@pytest.mark.parametrize("path", [
    "security-inspection/departments", "security-inspection/cameras", "security-inspection/status",
    "security-inspection/history", "security-inspection/cameras/camera_1/config",
    "security-inspection/config-schema", "security-inspection/horns",
    "security-fence/departments", "security-fence/cameras", "security-fence/status",
    "security-fence/cameras/camera_1/status", "security-fence/history", "security-fence/alarms/1",
])
def test_external_data_without_api_key(external_api, path):
    response = external_api.client.get(f"/api/external/{path}", params={"department": "general_electric"})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path, media_type, shape", [
    ("security-inspection/cameras/camera_1/frame.jpg?max_width=32", "image/jpeg", (16, 32)),
    ("security-fence/cameras/camera_1/frame.jpg?max_width=32", "image/jpeg", (16, 32)),
    ("security-inspection/history/session-1/image.jpg", "image/jpeg", (48, 96)),
    ("security-fence/alarms/1/image", "image/png", (48, 96)),
])
def test_external_images_without_api_key(external_api, path, media_type, shape):
    url = f"/api/external/{path}"
    url += ("&" if "?" in url else "?") + "department=general_electric"
    response = external_api.client.get(url)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == media_type
    assert response.headers["cache-control"] == "no-store"
    image = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == shape


@pytest.mark.parametrize("feature, departments", [
    ("security-inspection", {"general_electric", "electrical_components"}),
    ("security-fence", {"general_electric", "electronics_electrician"}),
])
def test_external_departments_follow_platform_feature_assignment(external_api, feature, departments):
    response = external_api.client.get(f"/api/external/{feature}/departments")
    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == departments


@pytest.mark.parametrize("feature", ["security-inspection", "security-fence"])
@pytest.mark.parametrize("path, params, status", [
    ("/cameras", {}, 422),
    ("/cameras", {"department": "unknown"}, 400),
    ("/cameras", {"department": "haoda_company"}, 403),
    ("/cameras/camera_2/frame.jpg", {"department": "general_electric"}, 403),
    ("/cameras/missing/frame.jpg", {"department": "general_electric"}, 404),
])
def test_external_requests_keep_business_scope_validation(external_api, feature, path, params, status):
    response = external_api.client.get(f"/api/external/{feature}{path}", params=params)
    assert response.status_code == status, response.text


def test_external_config_save_without_api_key(external_api):
    response = external_api.client.put(
        "/api/external/security-inspection/cameras/camera_1/config",
        params={"department": "general_electric"}, json=external_api.config,
    )
    assert response.status_code == 200, response.text
    args, kwargs = external_api.config_manager.save_config.call_args
    assert args[1:] == (1, external_api.config)
    assert kwargs == {"expected_department": "general_electric"}


def test_external_openapi_does_not_require_api_key(external_api):
    schema = external_api.app.openapi()
    for path, operations in schema["paths"].items():
        if path.startswith("/api/external/"):
            for operation in operations.values():
                assert not operation.get("security"), path
                assert all(param["name"].lower() != "x-api-key" for param in operation.get("parameters", [])), path


@pytest.mark.parametrize("path", [
    "/api/cameras", "/api/security-inspection/history", "/api/security-fence/status",
    "/api/admin/external-clients",
])
def test_platform_routes_still_require_login(external_api, path):
    response = external_api.client.get(path, params={"department": "general_electric"})
    assert response.status_code == 401
