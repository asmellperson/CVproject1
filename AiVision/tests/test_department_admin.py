"""部门管理员的账号约束、API 越权边界与助手权限回归；不连接现场服务。"""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest


OWN = "general_electric"
OTHER = "electronics_electrician"
FEATURES = ["detect_door", "security_fence", "recognize_face", "guard_behavior", "detect_logistics_single_person"]


@pytest.fixture
def environment(monkeypatch, tmp_path):
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "department_test",
        "MYSQL_DB_PASSWORD": "department_test", "MYSQL_DB_NAME": "department_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "department-test-signing-key-00000000",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def api(environment):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth import api as auth_api, external_api
    from auth.auth import get_current_user
    from AiVision.api import deps
    from AiVision.api.routes import cameras, departments, features, guard_behavior, horns, logistics_channels, models
    from AiVision.api.routes import security_inspection, assistant, exception_alerts
    from AiVision.departments.department_registry import DEPARTMENT_SPECS
    from AiVision.features.registry import get_spec

    user = {"employee_id": "d001", "name": "部门管理员", "role": "department_admin", "departments": [OWN],
            "auth_version": 1, "feature_access": {OWN: FEATURES, OTHER: FEATURES}}
    camera_rows = {i: {"camera_id": i, "id": f"camera_{i}", "shm_name": f"camera_{i}", "name": f"相机{i}",
                      "department": OWN if i == 1 else OTHER, "enabled": True, "fps": 5,
                      "url": f"rtsp://192.0.2.{i}/stream", "functions": {feature: True for feature in FEATURES}}
                   for i in (1, 2)}

    def find_camera(key):
        value = str(key).removeprefix("camera_")
        return deepcopy(camera_rows.get(int(value))) if value.isdigit() else None

    manager = Mock()
    manager.get_camera.side_effect = find_camera
    manager.list_cameras.side_effect = lambda department: [deepcopy(row) for row in camera_rows.values() if row["department"] == department]
    manager.create_camera.side_effect = lambda values: {**camera_rows[1], **values}
    manager.update_camera.side_effect = lambda key, values, **kwargs: {**find_camera(key), **values}
    manager.delete_camera.return_value = True
    manager.create_camera_for_feature.side_effect = lambda feature, values: {**camera_rows[1], **values}
    config = get_spec("detect_door").config_schema().model_dump()
    configs = Mock()
    configs.get_config.side_effect = lambda spec, key: {"camera": find_camera(key), "feature": spec.name, "config": config}
    configs.save_config.side_effect = lambda spec, key, values, **kwargs: {"camera": find_camera(key), "feature": spec.name, "config": values}

    channel_rows = {i: {"id": i, "name": f"通道{i}", "department": OWN if i == 1 else OTHER,
                       "feature_name": "detect_logistics_single_person", "enabled": True, "sort_order": 0,
                       "config": {}, "members": []} for i in (1, 2)}
    channels = Mock()
    channels.get_channel.side_effect = lambda feature, key: deepcopy(channel_rows.get(key))
    channels.create_channel.side_effect = lambda feature, name, department: {**channel_rows[1], "name": name, "department": department}
    channels.update_channel_and_config.side_effect = lambda feature, key, values, config: {**channel_rows[key], **values}
    channels.delete_channel.return_value = True
    guard_rows = {i: {"id": i, "name": f"保安室{i}", "department": OWN if i == 1 else OTHER,
                     "enabled": True, "sort_order": 0, "created_at": datetime(2026, 11, 11),
                     "updated_at": datetime(2026, 11, 11)} for i in (1, 2)}
    guards = Mock()
    guards.get_site.side_effect = lambda key: deepcopy(guard_rows[key])
    guards.create_site.side_effect = lambda **values: {**guard_rows[1], **values}
    guards.update_site.side_effect = lambda key, values: {**guard_rows[key], **values}
    horn_service = Mock()
    horn_service.list_horns.return_value = []
    horn_service.get_horn.side_effect = lambda key: {"id": key, "department": OWN if key == 1 else OTHER}
    horn_runtime = Mock()
    department_service = Mock()
    department_service.list_departments.return_value = list(DEPARTMENT_SPECS.values())
    app = FastAPI()
    for router in (cameras.router, features.create_features_router(configs, manager), departments.router,
                   logistics_channels.router, guard_behavior.router, horns.router, models.router,
                   security_inspection.router, assistant.router, exception_alerts.router, auth_api.router, external_api.router):
        app.include_router(router)
    for dependency, value in {
        get_current_user: user, deps.get_camera_config_manager: manager,
        deps.get_department_service: department_service, deps.get_logistics_channel_service: channels,
        deps.get_guard_behavior_service: guards, deps.get_optional_orchestrator: None,
        deps.get_horn_service: horn_service, deps.get_horn_runtime_manager: horn_runtime,
    }.items():
        def override(value):
            return lambda: value
        app.dependency_overrides[dependency] = override(value)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, user=user, manager=manager, configs=configs, config=config,
                              channels=channels, guards=guards, horns=horn_service, horn_runtime=horn_runtime)


def test_department_admin_reads_only_own_department(api):
    assert api.client.get(f"/api/cameras?department={OWN}").status_code == 200
    assert api.client.get(f"/api/cameras?department={OTHER}").status_code == 403
    assert api.client.get("/api/cameras/camera_2").status_code == 403
    assert [item["name"] for item in api.client.get("/api/departments").json()] == [OWN]
    assert api.client.get("/api/cameras/camera_1").json()["url"].startswith("rtsp://")
    api.user["role"] = "viewer"
    assert "url" not in api.client.get("/api/cameras/camera_1").json()


def test_own_camera_and_feature_configuration_can_be_saved(api):
    assert api.client.patch("/api/cameras/camera_1", json={"name": "本部门相机"}).status_code == 200
    assert api.manager.update_camera.call_args.kwargs == {"expected_department": OWN}
    assert api.client.post("/api/cameras", json={"name": "新增", "url": "rtsp://192.0.2.3/live", "department": OWN}).status_code == 201
    path = "/api/features/detect_door/configs/camera_1"
    assert api.client.put(path, json=api.config).status_code == 200
    assert api.configs.save_config.call_args.kwargs == {"expected_department": OWN}
    assert api.client.post("/api/features/detect_door/cameras", json={"name": "新增", "url": "rtsp://192.0.2.3/live", "department": OWN}).status_code == 200
    assert api.client.put("/api/features/detect_door/cameras/order", json={"department": OWN, "camera_ids": [1]}).status_code == 204
    assert api.client.delete("/api/cameras/camera_1").status_code == 200


@pytest.mark.parametrize("method,path,payload", [
    ("POST", "/api/cameras", {"name": "越权", "url": "rtsp://192.0.2.3/live", "department": OTHER}),
    ("PATCH", "/api/cameras/camera_2", {"name": "越权"}),
    ("PATCH", "/api/cameras/camera_1", {"department": OTHER}),
    ("PATCH", "/api/cameras/camera_1", {"department": None}),
    ("DELETE", "/api/cameras/camera_2", None),
    ("POST", "/api/features/detect_door/cameras", {"name": "越权", "url": "rtsp://192.0.2.3/live", "department": OTHER}),
    ("PUT", "/api/features/detect_door/cameras/order", {"department": OTHER, "camera_ids": [2]}),
    ("PUT", "/api/features/detect_door/configs/camera_2", {}),
    ("PUT", "/api/features/detect_phone/configs/camera_1", {}),
    ("POST", "/api/logistics-channels/detect_logistics_single_person", {"name": "越权", "department": OTHER}),
    ("PATCH", "/api/logistics-channels/detect_logistics_single_person/2", {"name": "越权"}),
    ("DELETE", "/api/logistics-channels/detect_logistics_single_person/2", None),
    ("POST", "/api/logistics-channels/detect_logistics_single_person/1/cameras", {"camera_id": 2}),
    ("PUT", "/api/logistics-channels/detect_logistics_single_person/1/cameras/2", None),
    ("POST", "/api/guard-behavior/sites", {"name": "越权", "department": OTHER}),
    ("PATCH", "/api/guard-behavior/sites/2", {"name": "越权"}),
    ("POST", "/api/guard-behavior/sites/1/cameras", {"camera_id": 2}),
    ("GET", f"/api/horns?department={OTHER}", None),
    ("GET", "/api/horns?unassigned=true", None),
    ("PATCH", f"/api/horns/2?department={OWN}", {"name": "越权"}),
    ("PATCH", f"/api/horns/1?department={OWN}", {"department": OTHER}),
])
def test_cross_department_requests_do_not_write(api, method, path, payload):
    response = api.client.request(method, path, **({"json": payload} if payload is not None else {}))
    assert response.status_code in {403, 404}, response.text
    for service, methods in (
        (api.manager, ("create_camera", "create_camera_for_feature", "update_camera", "delete_camera")),
        (api.configs, ("save_config", "reorder_cameras")),
        (api.channels, ("create_channel", "update_channel_and_config", "delete_channel", "add_existing_camera", "move_camera")),
        (api.guards, ("create_site", "update_site", "add_camera")),
        (api.horns, ("update_horn",)),
    ):
        for name in methods:
            getattr(service, name).assert_not_called()


def test_department_admin_can_configure_own_channels_sites_and_horns(api):
    path = "/api/logistics-channels/detect_logistics_single_person"
    assert api.client.post(path, json={"name": "本部门通道", "department": OWN}).status_code == 201
    assert api.client.patch(path + "/1", json={"name": "本部门通道"}).status_code == 200
    assert api.client.delete(path + "/1").status_code == 200
    assert api.client.post("/api/guard-behavior/sites", json={"name": "本部门保安室", "department": OWN}).status_code == 201
    assert api.client.patch("/api/guard-behavior/sites/1", json={"name": "本部门保安室"}).status_code == 200
    assert api.client.get(f"/api/horns?department={OWN}").json() == []
    api.user["feature_access"] = {}
    assert api.client.patch(path + "/1", json={"name": "撤权后"}).status_code == 403
    assert api.client.post("/api/guard-behavior/sites", json={"name": "撤权后", "department": OWN}).status_code == 403


@pytest.mark.parametrize("path", [
    "/api/admin/users", "/api/admin/external-clients", "/api/departments/feature-settings", "/api/models",
    "/api/security-inspection/settings", "/api/assistant/settings", "/api/horns/sip-server",
    "/api/exception-alert",
])
def test_global_management_remains_system_admin_only(api, path):
    assert api.client.get(path).status_code == 403


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/admin/users"), ("POST", "/api/admin/external-clients"),
    ("PUT", "/api/departments/feature-settings"), ("PATCH", "/api/models/yolo/path"),
    ("PUT", "/api/security-inspection/settings"), ("PUT", "/api/assistant/settings"),
    ("PUT", "/api/exception-alert"), ("PUT", "/api/horns/sip-server"),
    ("POST", "/api/horns/audio"), ("DELETE", "/api/horns/audio/1"),
])
def test_department_admin_cannot_modify_global_configuration(api, method, path):
    assert api.client.request(method, path, json={}).status_code == 403


@pytest.mark.parametrize("method,path,payload", [
    ("PATCH", "/api/cameras/camera_1", {"name": "不能保存"}),
    ("PUT", "/api/features/detect_door/configs/camera_1", {}),
    ("POST", "/api/logistics-channels/detect_logistics_single_person", {"name": "不能创建", "department": OWN}),
    ("PATCH", "/api/guard-behavior/sites/1", {"name": "不能保存"}),
    ("GET", f"/api/horns?department={OWN}", None),
])
def test_viewer_remains_read_only(api, method, path, payload):
    api.user["role"] = "viewer"
    assert api.client.request(method, path, **({"json": payload} if payload else {})).status_code == 403


def test_user_store_accepts_scoped_role_and_preserves_last_system_admin(environment, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from auth.orm import AuthUser
    from auth.user_store import UserStore, UserValidationError, UserConflictError
    from auth import auth
    from AiVision.departments.service import department_service
    from starlette.requests import Request

    engine = create_engine("sqlite://")
    AuthUser.__table__.create(engine)
    store = UserStore(sessionmaker(bind=engine))
    try:
        store.create_user(employee_id="root", name="系统管理员", role="admin", departments=None, password_hash="test-hash")
        created = store.create_user(employee_id="dept", name="部门管理员", role="department_admin", departments=[OWN, OWN], password_hash=auth.hash_password("department-test-password"))
        assert created["role"] == "department_admin" and created["departments"] == [OWN]
        monkeypatch.setattr(auth, "_user_store", store)
        monkeypatch.setattr(department_service, "feature_access", lambda: {OWN: FEATURES, OTHER: FEATURES})
        public_user = auth.verify_login("dept", "department-test-password")
        assert public_user["role"] == "department_admin" and set(public_user["feature_access"]) == {OWN}
        token = auth.create_token(public_user)
        request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})
        assert auth.get_current_user_from_request(request)["role"] == "department_admin"
        for departments in (None, [], ["all"], ["invalid"]):
            with pytest.raises(UserValidationError):
                store.create_user(employee_id="bad", name="无效账号", role="department_admin", departments=departments, password_hash="test-hash")
        with pytest.raises(UserConflictError):
            store.update_user("root", actor_employee_id="root", name="系统管理员", role="department_admin", departments=[OWN], enabled=True)
        changed = store.update_user("dept", actor_employee_id="root", name="部门管理员", role="viewer", departments=[OWN], enabled=True)
        assert changed["auth_version"] == created["auth_version"] + 1
        with pytest.raises(auth.AuthError, match="登录状态已失效"):
            auth.get_current_user_from_request(request)
        changed_again = store.update_user("dept", actor_employee_id="root", name="部门管理员", role="viewer", departments=[OTHER], enabled=True)
        assert changed_again["auth_version"] == changed["auth_version"] + 1
    finally:
        engine.dispose()


def test_assistant_and_alarm_scope_follow_the_same_role_boundary(api):
    from fastapi import HTTPException
    from auth.alarm_permissions import allowed_alarm_event_types
    from AiVision.alarms.records.queries import alarm_departments
    from AiVision.assistant.resources import ConfigurationCatalog
    from AiVision.assistant.global_resources import find_global_resources
    from AiVision.assistant.tools import AssistantTools
    from AiVision.assistant.service import scope_visible

    catalog = ConfigurationCatalog(api.user, None)
    assert catalog.departments == [OWN] and catalog.capabilities()["can_modify"]
    assert allowed_alarm_event_types(api.user, [OWN])
    assert alarm_departments(api.user) == [OWN]
    with pytest.raises(HTTPException):
        alarm_departments(api.user, OTHER)
    for kind in ("department_features", "model_path", "inspection_settings", "assistant_settings", "exception_alerts", "horn_sip"):
        with pytest.raises(HTTPException):
            find_global_resources(catalog, kind, [OWN])
    with pytest.raises(HTTPException):
        catalog.require_department(OTHER)
    tools = AssistantTools(turn_id="turn", session_id="session", department=OWN, load_user=lambda: api.user,
                           sources=None, orchestrator=None, check_cancel=lambda: None)
    assert tools.catalog(write=True).departments == [OWN]
    previous = {"role": "department_admin", "departments": [OWN], "feature_access": {OWN: FEATURES}}
    api.user["role"] = "viewer"
    with pytest.raises(HTTPException):
        tools.catalog(write=True)
    assert not scope_visible(previous, {**previous, "role": "viewer"})


def test_role_migration_preserves_enum_order_and_is_idempotent(environment, monkeypatch):
    from sqlalchemy import Enum
    from sqlalchemy.dialects.mysql import dialect
    from AiVision.migrations import department_admin_20261111 as migration

    engine = Mock()
    engine.dialect = dialect()
    connection = MagicMock()
    connection.dialect = engine.dialect
    engine.connect.return_value = MagicMock(__enter__=Mock(return_value=connection))
    engine.begin.return_value = MagicMock(__enter__=Mock(return_value=connection))
    inspector = Mock()
    inspector.has_table.return_value = True
    inspector.get_columns.side_effect = [
        [{"name": "role", "type": Enum("admin", "viewer")}],
        [{"name": "role", "type": Enum("admin", "viewer", "department_admin")}],
        [{"name": "role", "type": Enum("admin", "viewer", "department_admin")}],
        [{"name": "role", "type": Enum("admin", "viewer", "department_admin")}],
    ]
    monkeypatch.setattr(migration, "inspect", lambda _: inspector)
    validated_roles = []
    monkeypatch.setattr(migration, "assert_table_matches", lambda _, table: validated_roles.append(table.c.role.type.enums))
    assert migration.apply(engine) == {"state": "ready", "needs_upgrade": False}
    assert validated_roles[:2] == [["admin", "viewer"], ["admin", "viewer", "department_admin"]]
    statement = connection.exec_driver_sql.call_args.args[0]
    assert "MODIFY COLUMN `role` ENUM('admin','viewer','department_admin') NOT NULL" in statement
    assert migration.apply(engine)["state"] == "ready"
    connection.exec_driver_sql.assert_called_once()
