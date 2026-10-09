"""外部安检接口的真实认证、权限隔离、配置持久化和平台接口回归。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BASE = "/api/external/security-inspection"
DEPARTMENT = "general_electric"
OTHER_DEPARTMENT = "research_institute"


@pytest.fixture
def env(monkeypatch, tmp_path):
    # 配置、数据库和运行时均独立，测试不会启动摄像头、模型或通知服务。
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1",
        "MYSQL_DB_USER": "test",
        "MYSQL_DB_PASSWORD": "test",
        "MYSQL_DB_NAME": "test",
        "DATA_PATH": str(tmp_path),
        "AUTO_CREATE_DB": "false",
        "AUTH_SECRET": "external-api-test-secret-with-32-characters",
        "AUTH_TOKEN_EXPIRE_HOURS": "1",
    }.items():
        monkeypatch.setenv(key, value)

    from AiVision.api.app import create_app
    from AiVision.api import deps
    from AiVision.cameras import config_manager as camera_module
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.core import db
    from AiVision.departments.department_registry import DEPARTMENT_SPECS
    from AiVision.departments.orm import DepartmentFeatureAccess
    from AiVision.departments.service import DepartmentService
    from AiVision.features._shared import config_manager
    from AiVision.features.security_inspection.orm import InspectionCameraConfig, InspectionSession
    from AiVision.features.security_inspection.spec import SPEC
    from AiVision.alarms.devices.orm import AiHornConfig
    from auth import auth
    from auth.external import get_external_client_store
    from auth.external_schema import ExternalClientCreate, INSPECTION_WRITE
    from auth.external_store import ExternalClientStore
    from auth.orm import AuthUser, ExternalClient
    from auth.user_store import UserStore

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for model in (
        AiCameraConfig,
        AiHornConfig,
        InspectionCameraConfig,
        InspectionSession,
        DepartmentFeatureAccess,
        AuthUser,
        ExternalClient,
    ):
        model.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "_session_factory", factory)
    monkeypatch.setattr(camera_module, "all_specs", lambda: {SPEC.name: SPEC})
    monkeypatch.setattr(auth, "_user_store", UserStore(factory))
    department_service = DepartmentService(factory)
    from AiVision.departments import service as department_module

    monkeypatch.setattr(department_module, "department_service", department_service)
    events = []
    reloads = []
    monkeypatch.setattr(config_manager.config_cache, "reload", lambda: reloads.append(True))
    monkeypatch.setattr(config_manager.config_event_bus, "publish", events.append)

    with factory.begin() as session:
        session.add_all(
            [DepartmentFeatureAccess(department=name, features=[SPEC.name], revision=1) for name in DEPARTMENT_SPECS]
        )
        session.add_all(
            [
                AiCameraConfig(
                    id=1,
                    name="安检一",
                    shm_name="inspection_a",
                    url="private-video-source",
                    department=DEPARTMENT,
                    enable=True,
                    sort_order=1,
                ),
                AiCameraConfig(
                    id=2,
                    name="其他事业部",
                    shm_name="inspection_b",
                    url="private-video-source",
                    department=OTHER_DEPARTMENT,
                    enable=True,
                    sort_order=0,
                ),
                AiCameraConfig(
                    id=3,
                    name="待启用",
                    shm_name="inspection_c",
                    url="private-video-source",
                    department=DEPARTMENT,
                    enable=True,
                    sort_order=0,
                ),
                InspectionCameraConfig(camera_id=1, enable=True, sort_order=0),
                InspectionCameraConfig(camera_id=2, enable=True, sort_order=0),
                AiHornConfig(
                    id=1,
                    name="测试喇叭",
                    url="private-device-source",
                    username="test",
                    password="unused-test-value",
                    enable=True,
                ),
                AuthUser(
                    employee_id="admin",
                    name="测试管理员",
                    role="admin",
                    departments=["all"],
                    password_hash="unused-test-value",
                ),
                AuthUser(
                    employee_id="viewer",
                    name="测试用户",
                    role="viewer",
                    departments=[DEPARTMENT],
                    password_hash="unused-test-value",
                ),
            ]
        )
        for index, state in enumerate(["compliant", "non_compliant", "error", "cancelled"]):
            session.add(
                InspectionSession(
                    session_id=f"session-{index}",
                    camera_id=1,
                    camera_name="安检一",
                    department=DEPARTMENT,
                    roi_name="security_staff_1",
                    started_at=datetime(2026, 1, 1, 10, index),
                    ended_at=datetime(2026, 1, 1, 10, index, 10),
                    status=state,
                    verdict={"compliant": state == "compliant", "confidence": 0.9, "reason": "测试判定"}
                    if state in {"compliant", "non_compliant"}
                    else None,
                )
            )
        session.add(
            InspectionSession(
                session_id="private-session",
                camera_id=2,
                camera_name="其他事业部",
                department=OTHER_DEPARTMENT,
                roi_name="private",
                started_at=datetime(2026, 1, 1),
                ended_at=datetime(2026, 1, 1),
                status="error",
            )
        )

    store = ExternalClientStore(factory)
    payload = ExternalClientCreate(
        name="测试大屏",
        departments=[DEPARTMENT],
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    reader = store.create(payload, "admin")
    writer = store.create(payload.model_copy(update={"scopes": [*payload.scopes, INSPECTION_WRITE]}), "admin")
    app = create_app()
    app.dependency_overrides[get_external_client_store] = lambda: store
    app.dependency_overrides[deps.get_department_service] = lambda: department_service
    app.dependency_overrides[deps.get_inspection_consumer] = lambda: None
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            app=app,
            store=store,
            reader=reader,
            writer=writer,
            factory=factory,
            events=events,
            reloads=reloads,
            payload=payload,
        )
    engine.dispose()


def headers(credential):
    return {"X-API-Key": credential.api_key}


def config_url(camera="inspection_a", department=DEPARTMENT):
    return f"{BASE}/cameras/{camera}/config?department={department}"


def login_as(env, employee_id):
    """使用真实 JWT 验证已有人员认证，数据库用户状态仍参与校验。"""
    from auth.auth import COOKIE_NAME, create_token, get_user_store

    env.client.cookies.set(COOKIE_NAME, create_token(get_user_store().get_user_record(employee_id)))


def test_external_requires_header_and_does_not_accept_personnel_cookie(env):
    url = f"{BASE}/status?department={DEPARTMENT}"
    assert env.client.get(url).status_code == 401
    assert env.client.get(url, headers={"X-API-Key": "invalid"}).status_code == 401
    assert env.client.get(url + f"&api_key={env.reader.api_key}").status_code == 401
    login_as(env, "admin")
    assert env.client.get(url).status_code == 401
    assert env.client.get(url, headers=headers(env.reader)).status_code == 200
    response = env.client.get(url, headers=[("X-API-Key", env.reader.api_key), ("X-API-Key", env.writer.api_key)])
    assert response.status_code == 401


def test_keys_are_hashed_revocable_and_rotatable(env):
    from auth.orm import ExternalClient
    from auth.external_store import ExternalCredentialError

    with env.factory() as session:
        digest = session.get(ExternalClient, env.reader.client.id).key_digest
    assert len(digest) == 64 and digest != env.reader.api_key
    assert env.reader.api_key not in str(env.store.list_clients())
    rotated = env.store.rotate(env.reader.client.id)
    with pytest.raises(ExternalCredentialError):
        env.store.authenticate(env.reader.api_key)
    assert env.store.authenticate(rotated.api_key).id == env.reader.client.id
    env.store.set_enabled(rotated.client.id, False)
    with pytest.raises(ExternalCredentialError):
        env.store.authenticate(rotated.api_key)
    env.store.set_enabled(rotated.client.id, True)
    with env.factory.begin() as session:
        session.get(ExternalClient, rotated.client.id).expires_at = datetime(2000, 1, 1)
    with pytest.raises(ExternalCredentialError):
        env.store.authenticate(rotated.api_key)


def test_departments_and_cameras_preserve_frontend_fields_without_private_sources(env):
    response = env.client.get(f"{BASE}/departments", headers=headers(env.reader))
    assert response.json() == [{"name": DEPARTMENT, "display_name": "通用电气事业部"}]
    response = env.client.get(f"{BASE}/cameras?department={DEPARTMENT}", headers=headers(env.reader))
    assert response.status_code == 200
    assert [item["camera_id"] for item in response.json()] == [1, 3]
    assert "private-video-source" not in response.text and '"url"' not in response.text
    assert all(set(item["functions"]) == {"security_inspection"} for item in response.json())
    response = env.client.get(f"{BASE}/cameras?department={DEPARTMENT}&enabled_only=true", headers=headers(env.reader))
    assert [item["camera_id"] for item in response.json()] == [1]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["cameras", "history", "status", "cameras/inspection_b/config"])
def test_cross_department_is_denied(env, path):
    response = env.client.get(f"{BASE}/{path}?department={OTHER_DEPARTMENT}", headers=headers(env.writer))
    assert response.status_code == 403


def test_camera_cannot_borrow_query_department_or_use_alias(env):
    assert env.client.get(config_url("inspection_b"), headers=headers(env.writer)).status_code == 403
    assert env.client.get(config_url("1"), headers=headers(env.writer)).status_code == 404
    assert env.client.get(config_url("missing"), headers=headers(env.writer)).status_code == 404


def test_revoked_feature_assignment_immediately_blocks_external_client(env):
    from AiVision.departments.orm import DepartmentFeatureAccess

    with env.factory.begin() as session:
        session.get(DepartmentFeatureAccess, DEPARTMENT).features = []
    assert env.client.get(f"{BASE}/departments", headers=headers(env.reader)).json() == []
    assert env.client.get(config_url(), headers=headers(env.writer)).status_code == 403


def test_history_statistics_are_department_scoped_and_independent_of_pagination(env):
    response = env.client.get(f"{BASE}/history?department={DEPARTMENT}&limit=1&offset=1", headers=headers(env.reader))
    assert response.status_code == 200
    assert response.json()["stats"] == {
        "total": 4,
        "compliant": 1,
        "non_compliant": 1,
        "error": 1,
        "cancelled": 1,
        "rate": 50.0,
    }
    assert response.json()["items"][0]["session_id"] == "session-2"
    assert len(response.json()["items"]) == 1
    response = env.client.get(f"{BASE}/history?department={DEPARTMENT}&camera_id=2", headers=headers(env.reader))
    assert response.json()["stats"]["total"] == 0 and response.json()["items"] == []


def test_external_and_platform_status_have_identical_contract(env):
    login_as(env, "viewer")
    external = env.client.get(f"{BASE}/status?department={DEPARTMENT}", headers=headers(env.reader))
    platform = env.client.get(f"/api/security-inspection/status?department={DEPARTMENT}")
    assert external.status_code == platform.status_code == 200
    assert external.json() == platform.json()
    assert external.json()["running"] is False and external.json()["error"]


def test_configuration_write_is_scoped_persisted_and_publishes_events(env):
    read = env.client.get(config_url(), headers=headers(env.reader))
    assert read.status_code == 200
    config = read.json()["config"]
    config["value"]["conf"] = 0.45
    config["value"]["staff_rois"] = {"工位一": [[0.1, 0.1], [0.8, 0.1], [0.8, 0.9], [0.1, 0.9]]}
    assert env.client.put(config_url(), headers=headers(env.reader), json=config).status_code == 403
    assert env.client.put(config_url("inspection_b"), headers=headers(env.writer), json=config).status_code == 403
    saved = env.client.put(config_url(), headers=headers(env.writer), json=config)
    assert saved.status_code == 200, saved.text
    assert saved.json()["config"] == config
    assert env.reloads == [True]
    assert [event.change_type for event in env.events] == ["security_inspection_config_updated"]
    login_as(env, "admin")
    platform = env.client.get("/api/features/security_inspection/configs/inspection_a")
    assert platform.json()["config"] == config
    config["enable"] = False
    assert env.client.put(config_url(), headers=headers(env.writer), json=config).status_code == 200
    assert env.events[-1].change_type == "security_inspection_disabled"


@pytest.mark.parametrize("invalid", ["partial", "missing_parameter", "unknown", "roi", "string_number", "horn"])
def test_invalid_config_does_not_change_database(env, invalid):
    original = env.client.get(config_url(), headers=headers(env.writer)).json()["config"]
    import copy

    config = copy.deepcopy(original)
    if invalid == "partial":
        config = {"enable": False}
    elif invalid == "missing_parameter":
        del config["value"]["conf"]
    elif invalid == "unknown":
        config["value"]["legacy_field"] = 1
    elif invalid == "roi":
        config["value"]["staff_rois"] = {"工位": [[100, 100], [500, 100], [500, 300]]}
    elif invalid == "string_number":
        config["value"]["conf"] = "0.5"
    else:
        config["alarm"]["horn"] = {"enable": True, "parm": {"horn_id": 999, "horn_event_id": 1}}
    response = env.client.put(config_url(), headers=headers(env.writer), json=config)
    assert response.status_code == (400 if invalid == "horn" else 422)
    assert env.client.get(config_url(), headers=headers(env.writer)).json()["config"] == original
    assert env.events == [] and env.reloads == []


def test_department_change_during_save_is_rejected(env, monkeypatch):
    from AiVision.api.routes.external.security_inspection import get_config_manager
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.features._shared.config_manager import feature_config_manager

    config = env.client.get(config_url(), headers=headers(env.writer)).json()["config"]

    def moved_manager():
        with env.factory.begin() as session:
            session.get(AiCameraConfig, 1).department = OTHER_DEPARTMENT
        return feature_config_manager

    env.app.dependency_overrides[get_config_manager] = moved_manager
    response = env.client.put(config_url(), headers=headers(env.writer), json=config)
    assert response.status_code == 409
    assert env.events == [] and env.reloads == []


def test_schema_and_horn_choices_are_usable_and_redacted(env):
    schema = env.client.get(f"{BASE}/config-schema", headers=headers(env.reader))
    assert schema.status_code == 200
    assert "staff_rois" in schema.json()["config_schema"]["$defs"]["InspectionValue"]["properties"]
    assert (
        env.client.put(
            config_url("inspection_c"), headers=headers(env.writer), json=schema.json()["default_config"]
        ).status_code
        == 200
    )
    url = f"{BASE}/horns?department={DEPARTMENT}"
    assert env.client.get(url, headers=headers(env.reader)).status_code == 403
    assert env.client.get(url, headers=headers(env.writer)).json() == [{"id": 1, "name": "测试喇叭", "enable": True}]


def test_jpeg_raw_and_annotated_frames_use_existing_pipeline(env):
    import numpy as np
    import cv2
    from AiVision.api.deps import get_current_orchestrator

    calls = []

    def get_frame(key, feature):
        calls.append((key, feature))
        return np.zeros((60, 80, 3), dtype=np.uint8), 1.0

    env.app.dependency_overrides[get_current_orchestrator] = lambda: SimpleNamespace(get_camera_frame_info=get_frame)
    for annotated, feature in [("true", "security_inspection"), ("false", None)]:
        response = env.client.get(
            f"{BASE}/cameras/inspection_a/frame.jpg?department={DEPARTMENT}&annotated={annotated}&max_width=40",
            headers=headers(env.reader),
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "no-store"
        assert cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR).shape[:2] == (30, 40)
        assert calls[-1] == ("inspection_a", feature)
    env.app.dependency_overrides[get_current_orchestrator] = lambda: SimpleNamespace(
        get_camera_frame_info=lambda *args, **kwargs: (None, 1.0),
    )
    assert (
        env.client.get(
            f"{BASE}/cameras/inspection_a/frame.jpg?department={DEPARTMENT}", headers=headers(env.reader)
        ).status_code
        == 503
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/users",
        "/api/security-inspection/settings",
        "/api/features/security_inspection/configs/inspection_a",
        "/api/cameras",
    ],
)
def test_external_credential_does_not_grant_platform_access(env, path):
    assert env.client.get(path, headers=headers(env.writer)).status_code == 401


def test_credential_admin_lifecycle_and_metadata_secrecy(env):
    url = "/api/admin/external-clients"
    assert env.client.get(url, headers=headers(env.writer)).status_code == 401
    login_as(env, "viewer")
    assert env.client.get(url).status_code == 403
    login_as(env, "admin")
    created = env.client.post(url, json=env.payload.model_dump(mode="json"))
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    client_id = created.json()["client"]["id"]
    api_key = created.json()["api_key"]
    listing = env.client.get(url)
    assert api_key not in listing.text and "key_digest" not in listing.text
    assert env.client.put(f"{url}/{client_id}/enabled", json={"enabled": False}).status_code == 200
    assert env.client.get(f"{BASE}/departments", headers={"X-API-Key": api_key}).status_code == 401
    rotated = env.client.post(f"{url}/{client_id}/rotate")
    assert rotated.status_code == 200 and rotated.json()["api_key"] != api_key
    assert rotated.json()["client"]["enabled"] is False
    payload = {**env.payload.model_dump(mode="json"), "enabled": True, "departments": [OTHER_DEPARTMENT]}
    assert env.client.put(f"{url}/{client_id}", json=payload).status_code == 200
    response = env.client.get(f"{BASE}/departments", headers={"X-API-Key": rotated.json()["api_key"]})
    assert [item["name"] for item in response.json()] == [OTHER_DEPARTMENT]
    assert env.client.post(f"{url}/missing/rotate").status_code == 404
    assert env.client.post(f"{url}/不存在/rotate").status_code == 404


@pytest.mark.parametrize(
    "field,value",
    [
        ("departments", ["all"]),
        ("departments", [DEPARTMENT, DEPARTMENT]),
        ("scopes", ["admin"]),
        ("scopes", ["security_inspection:config:write"]),
        ("expires_at", "2000-01-01T00:00:00Z"),
        ("expires_at", "2099-01-01T00:00:00"),
    ],
)
def test_credential_scope_and_expiration_validation(env, field, value):
    login_as(env, "admin")
    payload = {**env.payload.model_dump(mode="json"), field: value}
    assert env.client.post("/api/admin/external-clients", json=payload).status_code == 422


def test_openapi_describes_external_header_and_full_contract(env):
    schema = env.client.get("/openapi.json").json()
    path = schema["paths"][f"{BASE}/cameras/{{shm_name}}/config"]
    assert {"ExternalApiKey": []} in path["put"]["security"]
    assert schema["components"]["securitySchemes"]["ExternalApiKey"]["name"] == "X-API-Key"
    assert "/api/external/v1/security-inspection/status" not in schema["paths"]
    assert f"{BASE}/settings" not in schema["paths"]
