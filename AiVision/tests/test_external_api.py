"""外部数据和图片直链无需凭证，业务范围及平台登录仍按各自规则校验。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import time
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
        "feature_sort_orders": {},
        "functions": {"security_inspection": True, "security_fence": True, "tailgating": True},
    }
    other_camera = {**camera, "id": "camera_2", "camera_id": 2, "shm_name": "camera_2",
                    "department": "electronics_electrician"}
    cameras = {row["shm_name"]: row for row in (camera, other_camera)}
    catalog = Mock()
    catalog.feature_access.return_value = {
        "general_electric": ["security_inspection", "security_fence", "tailgating"],
        "electronics_electrician": ["security_fence"],
        "electrical_components": ["security_inspection", "tailgating"],
    }
    camera_manager = Mock()
    camera_manager.get_camera.side_effect = cameras.get
    camera_manager.get_camera_identity.side_effect = lambda key: (
        {field: cameras[key][field] for field in ("camera_id", "shm_name", "department")}
        if key in cameras else None
    )
    camera_manager.list_cameras.return_value = list(cameras.values())
    pixels = np.zeros((48, 96, 3), dtype=np.uint8)
    orchestrator = Mock()
    orchestrator.get_camera_frame_info.return_value = (pixels, 1.0)
    tailgating_event = {"id": "gate-event-1", "track_ids": [1, 2], "direction": 1, "overlap_seconds": 0.5}
    tailgating_snapshot = {
        "updated_at_s": time.time(), "reason": "tailgating", "count": 2, "alarm": True,
        "persons": [{"track_id": 1, "bbox": [1, 2, 20, 40], "in_roi": True, "direction": 1}],
        "events": [tailgating_event], "error": None, "sample_interval_seconds": 0.1,
    }
    tailgating_consumer = Mock()
    tailgating_consumer.get_monitor_status.return_value = tailgating_snapshot
    orchestrator.consumers = {"tailgating": tailgating_consumer}
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
    client = TestClient(app)
    yield SimpleNamespace(
        client=client, app=app, config=config, config_manager=config_manager, camera=camera,
        camera_manager=camera_manager, orchestrator=orchestrator, tailgating_snapshot=tailgating_snapshot,
        tailgating_event=tailgating_event,
        inspection_service=inspection_service, authenticate=authenticate,
    )
    client.close()
    authenticate.assert_not_called()


@pytest.mark.parametrize("path", [
    "security-inspection/departments", "security-inspection/cameras", "security-inspection/status",
    "security-inspection/history", "security-inspection/cameras/camera_1/config",
    "security-inspection/config-schema", "security-inspection/horns",
    "security-fence/departments", "security-fence/cameras", "security-fence/status",
    "security-fence/cameras/camera_1/status", "security-fence/history", "security-fence/alarms/1",
    "tailgating/departments", "tailgating/cameras", "tailgating/status", "tailgating/cameras/camera_1/status",
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
    ("tailgating/cameras/camera_1/frame.jpg?max_width=32", "image/jpeg", (16, 32)),
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
    ("tailgating", {"general_electric", "electrical_components"}),
])
def test_external_departments_follow_platform_feature_assignment(external_api, feature, departments):
    response = external_api.client.get(f"/api/external/{feature}/departments")
    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == departments


@pytest.mark.parametrize("feature", ["security-inspection", "security-fence", "tailgating"])
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
    assert schema["paths"]["/api/external/tailgating/alarms/{alarm_id}/image"]["get"]["responses"]["200"]["content"] == {
        "image/png": {},
    }


@pytest.mark.parametrize("path", [
    "/api/cameras", "/api/security-inspection/history", "/api/security-fence/status",
    "/api/admin/external-clients",
    "/api/tailgating/cameras/camera_1/status",
    "/api/cameras/camera_1/frame.jpg",
])
def test_platform_routes_still_require_login(external_api, path):
    response = external_api.client.get(path, params={"department": "general_electric"})
    assert response.status_code == 401


@pytest.fixture
def platform_frame_auth(external_api, monkeypatch):
    user = {
        "employee_id": "preview-user", "name": "预览测试账号", "role": "viewer",
        "departments": ["general_electric"],
        "feature_access": {"general_electric": ["security_inspection"]},
    }
    # 每次认证返回独立快照，才能发现缓存旧账号权限的问题。
    authenticate = Mock(side_effect=lambda request: deepcopy(user))
    monkeypatch.setattr("AiVision.api.app.get_current_user_from_request", authenticate)
    return SimpleNamespace(user=user, authenticate=authenticate)


def test_platform_frame_uses_identity_query_and_preserves_jpeg_and_timings(external_api, platform_frame_auth):
    external_api.camera["url"] = "rtsp://preview-user:preview-password@camera.invalid/live"
    external_api.camera_manager.get_camera.side_effect = AssertionError("取图不应读取完整摄像头配置")
    response = external_api.client.get("/api/cameras/camera_1/frame.jpg", params={
        "feature": "security_inspection", "max_width": 32,
    })
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    image = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == (16, 32)
    external_api.camera_manager.get_camera_identity.assert_called_once_with("camera_1")
    external_api.camera_manager.get_camera.assert_not_called()
    external_api.orchestrator.get_camera_frame_info.assert_called_once_with(
        "camera_1", feature="security_inspection",
    )
    platform_frame_auth.authenticate.assert_called_once()
    timings = {}
    for metric in response.headers["server-timing"].split(","):
        name, *parameters = (part.strip() for part in metric.split(";"))
        duration = float(next(value[4:] for value in parameters if value.startswith("dur=")))
        assert math.isfinite(duration) and duration >= 0, metric
        timings[name] = duration
    assert {"camera_access", "auth", "request_total", "frame_lookup", "jpeg_encode", "frame_total"} <= timings.keys()
    assert timings["request_total"] >= timings["auth"]
    assert timings["request_total"] >= timings["camera_access"]
    assert timings["request_total"] >= timings["frame_total"]
    for credential in ("rtsp://", "preview-password", "camera.invalid"):
        assert credential.encode() not in response.content
        assert credential not in str(response.headers)


@pytest.mark.parametrize("key, role, departments, features, status", [
    ("camera_2", "viewer", ["general_electric"], ["security_inspection"], 403),
    ("camera_1", "viewer", ["general_electric"], [], 403),
    ("camera_1", "admin", [], [], 403),
    ("missing", "viewer", ["general_electric"], ["security_inspection"], 404),
])
def test_platform_frame_keeps_camera_and_feature_access_checks(
    external_api, platform_frame_auth, key, role, departments, features, status,
):
    platform_frame_auth.user.update({
        "role": role, "departments": departments, "feature_access": {"general_electric": features},
    })
    response = external_api.client.get(f"/api/cameras/{key}/frame.jpg", params={
        "feature": "security_inspection",
    })
    assert response.status_code == status, response.text
    external_api.camera_manager.get_camera_identity.assert_called_once_with(key)
    external_api.camera_manager.get_camera.assert_not_called()
    external_api.orchestrator.get_camera_frame_info.assert_not_called()


@pytest.mark.parametrize("revoked", ["department", "feature"])
def test_platform_frame_rechecks_current_permissions_on_every_request(external_api, platform_frame_auth, revoked):
    url = "/api/cameras/camera_1/frame.jpg?feature=security_inspection"
    allowed = external_api.client.get(url)
    assert allowed.status_code == 200, allowed.text
    external_api.orchestrator.get_camera_frame_info.reset_mock()
    if revoked == "department":
        platform_frame_auth.user["departments"] = []
    else:
        platform_frame_auth.user["feature_access"] = {"general_electric": []}
    rejected = external_api.client.get(url)
    assert rejected.status_code == 403, rejected.text
    assert platform_frame_auth.authenticate.call_count == 2
    assert external_api.camera_manager.get_camera_identity.call_count == 2
    external_api.camera_manager.get_camera.assert_not_called()
    external_api.orchestrator.get_camera_frame_info.assert_not_called()


@pytest.fixture
def tailgating_database(external_api, monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from AiVision.alarms.records.orm import AiAlarmEvent
    from AiVision.core.db import Base
    from AiVision.features.tailgating import service

    # FastAPI 在线程池中查询，所有连接共享隔离的内存数据库。
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AiAlarmEvent.__table__])
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(service, "get_session", factory)
    started_at = datetime(2026, 10, 22, 9)
    large_id = 2**53 + 1
    image = tmp_path / "tailgating.png"
    image.write_bytes(cv2.imencode(".png", np.zeros((12, 24, 3), dtype=np.uint8))[1].tobytes())
    with factory.begin() as session:
        for alarm_id, feature, department, camera, minutes, image_path in [
            (large_id, "tailgating", "general_electric", "camera_1", 0, str(image)),
            (2, "tailgating", "general_electric", "camera_3", 1, str(image)),
            (3, "tailgating", "electronics_electrician", "camera_2", 2, str(image)),
            (4, "security_fence", "general_electric", "camera_1", 3, str(image)),
            (5, "tailgating", "general_electric", "camera_1", 2, str(tmp_path / "deleted.png")),
            (6, "tailgating", "general_electric", "camera_1", 0, str(image)),
        ]:
            session.add(AiAlarmEvent(
                id=alarm_id, violation_type=17 if feature == "tailgating" else 15,
                feature_name=feature, department=department, camera_no=camera, subject_type="camera",
                subject_id=camera, subject_name="闸机入口", reason="非法闯闸",
                event_metadata={"tailgating": external_api.tailgating_event} if alarm_id == large_id else {},
                image_path=image_path, create_time=started_at + timedelta(minutes=minutes),
            ))
    yield SimpleNamespace(api=external_api, large_id=str(large_id), started_at=started_at)
    engine.dispose()


def test_tailgating_history_filters_before_counting_and_pagination(tailgating_database):
    database = tailgating_database
    first = database.api.client.get("/api/external/tailgating/history", params={
        "department": "general_electric", "limit": 2,
    })
    second = database.api.client.get("/api/external/tailgating/history", params={
        "department": "general_electric", "limit": 2, "offset": 2,
    })
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 4
    assert [row["id"] for row in first.json()["items"]] == ["5", "2"]
    assert [row["id"] for row in second.json()["items"]] == [database.large_id, "6"]
    record = second.json()["items"][0]
    assert record["tailgating"] == database.api.tailgating_event
    assert record["image_url"] == f"/api/external/tailgating/alarms/{database.large_id}/image?department=general_electric"
    assert "image_path" not in record and "metadata" not in record
    assert datetime.fromisoformat(record["created_at"]).tzinfo is not None


def test_tailgating_history_converts_timezone_and_keeps_half_open_bounds(tailgating_database):
    database = tailgating_database
    response = database.api.client.get("/api/external/tailgating/history", params={
        "department": "general_electric", "camera_key": "camera_1",
        "start": database.started_at.astimezone(timezone.utc).isoformat(),
        "end": (database.started_at + timedelta(minutes=2)).astimezone(timezone.utc).isoformat(),
    })
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert [row["id"] for row in response.json()["items"]] == [database.large_id, "6"]


@pytest.mark.parametrize("params, status", [
    ({"start": "2026-10-22T10:00:00+08:00", "end": "2026-10-22T09:00:00+08:00"}, 400),
    ({"start": "2026-10-22T09:00:00+08:00", "end": "2026-10-22T09:00:00+08:00"}, 400),
    ({"start": "2026-10-22T09:00:00"}, 422), ({"limit": 0}, 422), ({"limit": 501}, 422), ({"offset": -1}, 422),
])
def test_tailgating_history_validates_query_without_api_key(external_api, params, status):
    response = external_api.client.get("/api/external/tailgating/history", params={
        "department": "general_electric", **params,
    })
    assert response.status_code == status, response.text


def test_tailgating_alarm_detail_and_image_direct_links(tailgating_database):
    database = tailgating_database
    detail = database.api.client.get(f"/api/external/tailgating/alarms/{database.large_id}", params={
        "department": "general_electric",
    })
    assert detail.status_code == 200
    assert detail.json()["id"] == database.large_id
    response = database.api.client.get(detail.json()["image_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR).shape[:2] == (12, 24)


@pytest.mark.parametrize("alarm_id, suffix", [(3, ""), (3, "/image"), (4, ""), (4, "/image"), (5, "/image"), (999, ""), (999, "/image")])
def test_tailgating_evidence_keeps_department_feature_and_file_scope(tailgating_database, alarm_id, suffix):
    response = tailgating_database.api.client.get(f"/api/external/tailgating/alarms/{alarm_id}{suffix}", params={
        "department": "general_electric",
    })
    assert response.status_code == 404, response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("annotated", [True, False])
def test_tailgating_frame_modes_use_shared_encoder(external_api, annotated):
    response = external_api.client.get("/api/external/tailgating/cameras/camera_1/frame.jpg", params={
        "department": "general_electric", "annotated": str(annotated).lower(), "max_height": 8,
    })
    assert response.status_code == 200
    assert cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR).shape[:2] == (8, 16)
    assert external_api.orchestrator.get_camera_frame_info.call_args.kwargs == {
        "feature": "tailgating" if annotated else None,
    }


def test_tailgating_status_and_camera_responses_follow_existing_contract(external_api):
    cameras = external_api.client.get("/api/external/tailgating/cameras", params={"department": "general_electric"})
    assert cameras.json()[0]["functions"] == {"tailgating": True}
    assert cameras.json()[0]["feature_sort_orders"] == {"tailgating": 0}
    assert "url" not in cameras.json()[0]
    status = external_api.client.get("/api/external/tailgating/cameras/camera_1/status", params={"department": "general_electric"})
    assert status.status_code == 200
    assert status.json()["state"] == "ready"
    assert status.json()["count"] == 2 and status.json()["alarm"]
    assert status.json()["events"] == [external_api.tailgating_event]
    assert 0 < status.json()["valid_for_seconds"] <= 2


@pytest.mark.parametrize("age", [2.001, 3, -0.1])
def test_tailgating_status_does_not_report_stale_events_as_current(external_api, monkeypatch, age):
    monkeypatch.setattr("AiVision.features.tailgating.service.time.time", lambda: 1000.0)
    external_api.tailgating_snapshot["updated_at_s"] = 1000.0 - age
    response = external_api.client.get("/api/external/tailgating/cameras/camera_1/status", params={"department": "general_electric"})
    assert response.status_code == 200
    assert response.json()["state"] == "stale" and response.json()["count"] is None
    assert response.json()["events"] == [] and not response.json()["alarm"]
    assert response.json()["valid_for_seconds"] == 0


@pytest.mark.parametrize("age", [0.0, 0.5, 1.9, 2.0])
def test_tailgating_status_returns_remaining_lifetime_for_both_status_routes(external_api, monkeypatch, age):
    monkeypatch.setattr("AiVision.features.tailgating.service.time.time", lambda: 1000.0)
    external_api.tailgating_snapshot["updated_at_s"] = 1000.0 - age
    for path in ("/status", "/cameras/camera_1/status"):
        response = external_api.client.get(f"/api/external/tailgating{path}", params={"department": "general_electric"})
        assert response.status_code == 200
        data = response.json()[0] if path == "/status" else response.json()
        assert data["state"] == "ready"
        assert data["valid_for_seconds"] == pytest.approx(2.0 - age)
