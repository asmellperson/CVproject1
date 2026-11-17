"""总览批量读取、事业部权限与无模型能力的长期回归，不连接现场服务。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def api(monkeypatch, tmp_path):
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "overview_test",
        "MYSQL_DB_PASSWORD": "overview_test", "MYSQL_DB_NAME": "overview_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "overview-test-signing-key-00000000",
    }.items():
        monkeypatch.setenv(key, value)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from auth.auth import get_current_user
    from AiVision.api.routes import overview as routes
    from AiVision.cameras import config_manager
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.core.db import Base
    from AiVision.departments.department_registry import DEPARTMENT_SPECS
    from AiVision.features.registry import all_specs

    specs = all_specs()
    departments = list(DEPARTMENT_SPECS)
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[AiCameraConfig.__table__, *(spec.orm_class.__table__ for spec in specs.values())])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(config_manager, "get_session", sessions)
    with sessions.begin() as session:
        for index, department in enumerate([*departments, None], 1):
            session.add(AiCameraConfig(id=index, name=f"摄像头{index}", shm_name=f"camera_{index}",
                                      url="rtsp://192.0.2.1/stream", department=department, enable=True))
            session.add(specs["smoke_detection"].orm_class(camera_id=index, enable=True))

    selects = []

    @event.listens_for(engine, "before_cursor_execute")
    def count_queries(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    user = {"role": "admin", "departments": departments,
            "feature_access": {department: list(specs) for department in departments}}
    manager = config_manager.CameraConfigManager()
    logistics = SimpleNamespace(camera_inventory_status=Mock(return_value=[]))
    guards = SimpleNamespace(list_sites=Mock(return_value=[]))
    runtime = SimpleNamespace(
        consumers={}, guard_behavior_runtime=None,
        runtime_status=lambda: {"started": True, "running_cameras": [f"camera_{i}" for i in range(1, len(departments) + 1)],
                                "running_consumers": ["smoke_detection"], "running_models": []},
    )
    app = FastAPI()
    app.include_router(routes.router)
    for dependency, value in {
        get_current_user: user, routes.get_camera_config_manager: manager,
        routes.get_logistics_channel_service: logistics, routes.get_guard_behavior_service: guards,
        routes.get_optional_orchestrator: runtime,
    }.items():
        app.dependency_overrides[dependency] = lambda value=value: value
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, user=user, manager=manager, departments=departments,
                              selects=selects, specs=specs, logistics=logistics, guards=guards, runtime=runtime)
    engine.dispose()


def test_overview_queries_each_feature_once_across_all_departments(api):
    result = api.client.get("/api/overview")
    assert result.status_code == 200
    data = result.json()
    assert data["inventory_complete"] is True
    assert [camera["department"] for camera in data["cameras"]] == api.departments
    assert data["summary"]["camera_total"] == len(api.departments)
    assert len(api.selects) == 1 + len(api.specs)


@pytest.mark.parametrize("role", ["viewer", "department_admin"])
def test_scoped_users_only_receive_owned_departments_and_assigned_features(api, role):
    own = api.departments[0]
    api.user.update(role=role, departments=[own], feature_access={own: ["smoke_detection"]})
    data = api.client.get("/api/overview").json()
    assert [camera["department"] for camera in data["cameras"]] == [own]
    assert list(data["cameras"][0]["aivision_camera"]["functions"]) == ["smoke_detection"]
    assert ("url" in data["cameras"][0]["aivision_camera"]) is (role == "department_admin")
    assert [item["id"] for item in data["capabilities"]] == ["smoke-detection"]
    assert len(api.selects) == 1 + len(api.specs)


def test_user_without_departments_does_not_query_camera_tables(api):
    api.user.update(role="viewer", departments=[])
    data = api.client.get("/api/overview").json()
    assert data["cameras"] == []
    assert data["capabilities"] == []
    assert not api.selects


def test_smoke_capability_uses_registered_consumer_without_model_dependency(api):
    data = api.client.get("/api/overview").json()
    smoke = next(item for item in data["capabilities"] if item["id"] == "smoke-detection")
    assert len(data["capabilities"]) == len(api.specs)
    assert smoke["camera_count"] == len(api.departments)
    assert smoke["running"] is True
    assert smoke["model_ready"] is True
    assert data["cameras"][0]["running_capabilities"] == ["smoke-detection"]


def test_camera_list_keeps_single_department_contract_and_empty_scope(api):
    own = api.departments[0]
    assert [camera["department"] for camera in api.manager.list_cameras(own)] == [own]
    api.selects.clear()
    assert api.manager.list_cameras(departments=[]) == []
    assert not api.selects
    with pytest.raises(ValueError):
        api.manager.list_cameras(own, departments=[own])
    with pytest.raises(ValueError):
        api.manager.list_cameras(departments=["not-a-department"])
