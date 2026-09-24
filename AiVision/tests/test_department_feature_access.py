"""功能分配的持久化、并发冲突、部门隔离与接口授权回归。"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    # 测试只使用内存数据库，不读取或连接部署环境的 MySQL。
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test",
        "MYSQL_DB_PASSWORD": "test", "MYSQL_DB_NAME": "test",
        "DATA_PATH": str(tmp_path), "AUTO_CREATE_DB": "false",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def service(isolated_settings):
    from AiVision.departments.department_registry import DEPARTMENT_SPECS
    from AiVision.departments.orm import DepartmentFeatureAccess
    from AiVision.departments.service import DepartmentService

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    DepartmentFeatureAccess.__table__.create(engine)
    factory = sessionmaker(engine)
    with factory.begin() as session:
        session.add_all([DepartmentFeatureAccess(department=name, features=["recognize_face"], revision=1)
                         for name in DEPARTMENT_SPECS])
    yield DepartmentService(factory)
    engine.dispose()


def viewer():
    return {
        "role": "viewer", "departments": ["general_electric", "research_institute"],
        "feature_access": {"general_electric": ["detect_door"], "research_institute": ["detect_phone"]},
    }


def test_save_empty_assignment_and_atomic_conflict(service):
    from AiVision.departments.service import FeatureAssignmentConflict

    original = service.assignments()
    changed = [item.model_copy(deep=True) for item in original]
    changed[0].features = []
    result = service.save_feature_settings(changed)
    assert result.assignments[0].features == []
    assert result.assignments[0].revision == 2
    assert result.assignments[1].revision == 1
    original[1].features = ["detect_phone"]
    with pytest.raises(FeatureAssignmentConflict):
        service.save_feature_settings(original)
    assert service.assignments()[1].features == ["recognize_face"]


@pytest.mark.parametrize("invalid", ["unknown_feature", "duplicate_feature", "missing_department", "duplicate_department"])
def test_reject_invalid_assignment_without_partial_write(service, invalid):
    assignments = service.assignments()
    if invalid == "unknown_feature":
        assignments[0].features = ["invalid"]
    elif invalid == "duplicate_feature":
        assignments[0].features = ["recognize_face", "recognize_face"]
    elif invalid == "missing_department":
        assignments.pop()
    else:
        assignments.append(assignments[0])
    with pytest.raises(ValueError):
        service.save_feature_settings(assignments)
    assert all(item.revision == 1 and item.features == ["recognize_face"] for item in service.assignments())


def test_missing_database_assignment_does_not_grant_all(service):
    from AiVision.departments.orm import DepartmentFeatureAccess

    with service._session_factory.begin() as session:
        session.delete(session.get(DepartmentFeatureAccess, "general_electric"))
    with pytest.raises(RuntimeError, match="数据不完整"):
        service.feature_access()


@pytest.mark.parametrize("role", ["viewer", "admin"])
def test_exact_department_permission_for_all_roles(role):
    from auth.feature_permissions import feature_departments, require_feature_access

    user = viewer()
    user["role"] = role
    if role == "admin":
        user["departments"] = ["all"]
    assert feature_departments(user, "detect_phone") == ["research_institute"]
    require_feature_access(user, "detect_phone", "research_institute")
    with pytest.raises(HTTPException) as error:
        require_feature_access(user, "detect_phone", "general_electric")
    assert error.value.status_code == 403


def test_settings_api_admin_only_and_revision_conflict(service):
    from auth.auth import get_current_user
    from AiVision.api.deps import get_department_service
    from AiVision.api.routes.departments import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_department_service] = lambda: service
    app.dependency_overrides[get_current_user] = viewer
    client = TestClient(app)
    assert client.get("/api/departments/feature-settings").status_code == 403
    assignments = [item.model_dump() for item in service.assignments()]
    assert client.put("/api/departments/feature-settings", json={"assignments": assignments}).status_code == 403
    response = client.get("/api/departments/feature-access")
    assert response.json() == viewer()["feature_access"]
    assert response.headers["cache-control"] == "no-store"
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    assert client.get("/api/departments/feature-settings").status_code == 200
    assignments[0]["features"] = []
    assert client.put("/api/departments/feature-settings", json={"assignments": assignments}).status_code == 200
    assert client.put("/api/departments/feature-settings", json={"assignments": assignments}).status_code == 409


@pytest.mark.parametrize("role", ["viewer", "admin"])
def test_camera_and_specialized_routes_reject_cross_department(role):
    from AiVision.api.routes.cameras import camera_response_for_user, get_camera_frame_jpg
    from AiVision.api.routes.features import get_feature_status
    from AiVision.api.routes.security_inspection import department_access
    from AiVision.api.routes.logistics_channels import _query_departments
    from AiVision.api.routes.guard_behavior import _departments
    from AiVision.api.routes.visual_language_detection import scoped_camera

    user = viewer()
    user["role"] = role
    camera = {"department": "general_electric", "functions": {"detect_door": True, "detect_phone": True}, "url": "private"}
    result = camera_response_for_user(camera, user)
    assert result["functions"] == {"detect_door": True}
    assert ("url" in result) == (role == "admin")
    manager = SimpleNamespace(get_camera=lambda key: camera)
    for action in [
        lambda: get_feature_status("detect_phone", "camera", user, manager, None),
        lambda: get_camera_frame_jpg("camera", "detect_phone", 85, None, None, user, manager, None),
        lambda: department_access("general_electric", user),
        lambda: _query_departments(user, "general_electric"),
        lambda: scoped_camera("camera", "general_electric", user, manager),
    ]:
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code == 403
    assert _departments(user) == ()


def test_overview_filters_features_counts_and_resource_links():
    from AiVision.runtime.overview import build_overview

    queried = []
    logistics = SimpleNamespace(camera_inventory_status=lambda departments, orchestrator: queried.append(departments) or [])
    guards = SimpleNamespace(list_sites=lambda department: pytest.fail("未分配保安功能时不应查询保安室"))
    cameras = [{"camera_id": 1, "name": "测试", "department": "general_electric", "shm_name": "test",
                "enabled": True, "functions": {"detect_phone": True, "detect_door": True}}]
    access = {"general_electric": ["detect_door"], "research_institute": ["detect_phone"]}
    result = build_overview(list(access), cameras, logistics, guards, None, access)
    assert result.cameras[0].capabilities == ["door-detection"]
    assert result.summary.capability_total == 2
    assert result.department_summaries["general_electric"].capability_total == 1
    assert queried == [[]]


@pytest.mark.parametrize("role", ["viewer", "admin"])
def test_runtime_targets_do_not_borrow_other_department_permission(role):
    from AiVision.api.routes.runtime import runtime_status

    cameras = [
        {"camera_id": 1, "shm_name": "a", "department": "general_electric", "functions": {"detect_phone": True}},
        {"camera_id": 2, "shm_name": "b", "department": "research_institute", "functions": {"detect_phone": True}},
    ]
    status = {"running_cameras": ["a", "b"], "running_consumers": ["detect_phone"], "inference": {
        "consumers": {"detect_phone": {"targets": [
            {"camera_id": 1, "counts": {"person": 10}}, {"camera_id": 2, "counts": {"person": 1}},
        ]}},
    }}
    user = {**viewer(), "role": role}
    result = runtime_status(SimpleNamespace(runtime_status=lambda: status), user,
                            SimpleNamespace(list_cameras=lambda: cameras))
    assert result["inference"]["consumers"]["detect_phone"]["totals"] == {"person": 1}


def test_admin_assignment_save_updates_overview_and_keeps_full_catalog(service):
    from auth.auth import get_current_user
    from AiVision.api.deps import get_department_service
    from AiVision.api.routes.departments import router
    from AiVision.api.routes.overview import overview
    from AiVision.features.registry import all_specs

    def admin():
        return {"role": "admin", "departments": ["all"], "feature_access": service.feature_access()}

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_department_service] = lambda: service
    app.dependency_overrides[get_current_user] = admin
    client = TestClient(app)
    cameras = SimpleNamespace(list_cameras=lambda department: [])
    logistics = SimpleNamespace(camera_inventory_status=lambda departments, orchestrator: [])
    guards = SimpleNamespace(list_sites=lambda department: [])
    # 清空分配后管理员仍能取得完整目录，并重新给事业部添加功能。
    for enabled in (False, True, False):
        settings = client.get("/api/departments/feature-settings").json()
        assert {item["name"] for item in settings["features"]} == set(all_specs())
        for assignment in settings["assignments"]:
            assignment["features"] = ["detect_phone"] if enabled and assignment["department"] == "general_electric" else []
        assert client.put("/api/departments/feature-settings", json={"assignments": settings["assignments"]}).status_code == 200
        result = overview(admin(), cameras, logistics, guards, None)
        assert result.summary.capability_total == int(enabled)
        assert result.department_summaries["general_electric"].capability_total == int(enabled)
        assert result.department_summaries["research_institute"].capability_total == 0
        assert client.get("/api/departments/feature-access").json()["general_electric"] == (["detect_phone"] if enabled else [])
