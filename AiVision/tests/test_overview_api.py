"""总览批量读取、事业部权限与无模型能力的长期回归，不连接现场服务。"""
from types import SimpleNamespace
from unittest.mock import Mock
from threading import Event, Thread

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
    from AiVision.features.guard_behavior.orm import GuardBehaviorSite, GuardBehaviorSiteCamera
    from AiVision.features.registry import all_specs

    specs = all_specs()
    departments = list(DEPARTMENT_SPECS)
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[AiCameraConfig.__table__, GuardBehaviorSite.__table__,
                                             GuardBehaviorSiteCamera.__table__,
                                             *(spec.orm_class.__table__ for spec in specs.values())])
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
    guards = SimpleNamespace(list_overview_sites=Mock(return_value=[]))
    runtime = SimpleNamespace(
        consumers={}, guard_behavior_runtime=None,
        runtime_summary=lambda: {"started": True, "running_cameras": [f"camera_{i}" for i in range(1, len(departments) + 1)],
                                "running_consumers": ["smoke_detection"], "running_models": []},
    )
    app = FastAPI()
    app.include_router(routes.router)
    for dependency, value in {
        get_current_user: user, routes.get_camera_config_manager: manager,
        routes.get_logistics_channel_service: logistics, routes.get_guard_behavior_service: guards,
        routes.get_optional_orchestrator: runtime,
    }.items():
        def override(value):
            return lambda: value
        app.dependency_overrides[dependency] = override(value)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, user=user, manager=manager, departments=departments,
                              selects=selects, specs=specs, logistics=logistics, guards=guards,
                              runtime=runtime, sessions=sessions)
    engine.dispose()


def test_overview_queries_camera_and_all_feature_tables_in_two_round_trips(api):
    result = api.client.get("/api/overview")
    assert result.status_code == 200
    data = result.json()
    assert data["inventory_complete"] is True
    assert [camera["department"] for camera in data["cameras"]] == api.departments
    assert data["summary"]["camera_total"] == len(api.departments)
    assert len(api.selects) == 2
    assert all(spec.orm_class.__tablename__ in api.selects[1] for spec in api.specs.values())
    api.guards.list_overview_sites.assert_called_once_with(api.departments)


@pytest.mark.parametrize("role", ["viewer", "department_admin"])
def test_scoped_users_only_receive_owned_departments_and_assigned_features(api, role):
    own = api.departments[0]
    api.user.update(role=role, departments=[own], feature_access={own: ["smoke_detection"]})
    data = api.client.get("/api/overview").json()
    assert [camera["department"] for camera in data["cameras"]] == [own]
    assert list(data["cameras"][0]["aivision_camera"]["functions"]) == ["smoke_detection"]
    assert ("url" in data["cameras"][0]["aivision_camera"]) is (role == "department_admin")
    assert [item["id"] for item in data["capabilities"]] == ["smoke-detection"]
    assert len(api.selects) == 2
    api.guards.list_overview_sites.assert_called_once_with([])


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


def test_overview_loads_scoped_guard_sites_and_members_in_one_query(api, monkeypatch):
    from AiVision.api.routes import overview as routes
    from AiVision.features.guard_behavior import service as module
    from AiVision.features.guard_behavior.orm import GuardBehaviorSite, GuardBehaviorSiteCamera

    own, other = api.departments[:2]
    api.user["feature_access"][other].remove("guard_behavior")
    monkeypatch.setattr(module.db, "get_session", api.sessions)
    api.client.app.dependency_overrides[routes.get_guard_behavior_service] = module.GuardBehaviorService
    with api.sessions.begin() as session:
        session.add_all([
            GuardBehaviorSite(id=1, department=own, name="有成员", sort_order=2),
            GuardBehaviorSite(id=2, department=own, name="空保安室", sort_order=1, enabled=False),
            GuardBehaviorSite(id=3, department=other, name="未获授权"),
        ])
        session.add_all([GuardBehaviorSiteCamera(site_id=1, camera_id=1, enabled=False),
                         GuardBehaviorSiteCamera(site_id=3, camera_id=2)])

    response = api.client.get("/api/overview")
    assert response.status_code == 200
    data = response.json()
    assert [site["id"] for site in data["guard_behavior_sites"]] == [2, 1]
    assert data["cameras"][0]["site_id"] == 1
    assert data["cameras"][1]["site_id"] is None
    assert len(api.selects) == 3
    assert "LEFT OUTER JOIN" in api.selects[-1]


def test_overview_does_not_collect_consumer_or_worker_diagnostics(api, monkeypatch):
    from AiVision.runtime import orchestrator as module
    from AiVision.api.routes import overview as routes

    worker_details = Mock(side_effect=AssertionError("总览不需要等待Worker详细诊断"))
    consumer_details = Mock(side_effect=AssertionError("总览不需要等待Consumer推理统计"))
    monkeypatch.setattr(module, "inference_runtime_manager", SimpleNamespace(
        list_running=lambda: [], runtime_status=worker_details,
    ))
    instance = object.__new__(module.Orchestrator)
    instance._started = True
    instance.camera_runtime_manager = SimpleNamespace(list_running=lambda: ["camera_1"])
    instance.consumers = {"smoke_detection": SimpleNamespace(
        running=True, spec=api.specs["smoke_detection"], inference_status=consumer_details,
    )}
    instance.guard_behavior_runtime = None
    api.client.app.dependency_overrides[routes.get_optional_orchestrator] = lambda: instance
    response = api.client.get("/api/overview")
    assert response.status_code == 200
    assert response.json()["cameras"][0]["online"] is True
    worker_details.assert_not_called()
    consumer_details.assert_not_called()
    worker_details.side_effect = consumer_details.side_effect = None
    worker_details.return_value = {"models": []}
    consumer_details.return_value = {"totals": {}, "targets": []}
    details = instance.runtime_status()
    assert details["inference"]["workers"] == {"models": []}
    assert details["inference"]["consumers"]["smoke_detection"]["targets"] == []
    worker_details.assert_called_once()
    consumer_details.assert_called_once()


@pytest.fixture
def guard_runtime(api):
    from AiVision.features.guard_behavior.runtime import GuardBehaviorSiteRuntime
    from AiVision.features.guard_behavior.schema import (
        GuardBehaviorRuntimeAlarmPolicy, GuardBehaviorRuntimeMember,
        GuardBehaviorRuntimePolicy, GuardBehaviorRuntimeSiteConfig,
    )
    config = GuardBehaviorRuntimeSiteConfig(
        site_id=1, site_name="测试保安室", department=api.departments[0], enabled=True,
        members=(GuardBehaviorRuntimeMember(camera_id=1, camera_name="摄像头1", shm_name="camera_1",
                 member_enabled=True, physical_enabled=True, feature_enabled=True, sort_order=0),),
        policy=GuardBehaviorRuntimePolicy(),
        alarm_policies=tuple(GuardBehaviorRuntimeAlarmPolicy(violation_type=kind, alarm_interval=60.)
                             for kind in (8, 9, 10, 11)),
    )
    evidence = Mock()
    service = SimpleNamespace(list_runtime_site_configs=lambda: [config], get_runtime_site_config=lambda key: config)
    runtime = GuardBehaviorSiteRuntime(service=service, dispatcher=SimpleNamespace(evidence_recorder=evidence),
                                      evidence_recorder=evidence, is_camera_active=lambda key: True,
                                      start_background=False)
    runtime.start()
    yield runtime
    runtime.stop()


def test_guard_status_does_not_wait_for_slow_alarm_dispatch(guard_runtime, monkeypatch):
    runtime = guard_runtime
    monkeypatch.setattr(runtime, "_dispatch_evaluation", lambda *args: None)
    initial = runtime.evaluate_after_camera_update(1)
    assert initial is not None
    entered, release, received = Event(), Event(), Event()
    values = []

    def slow_dispatch(*args):
        entered.set()
        assert release.wait(3)

    def read_status():
        values.append(runtime.get_site_status(1))
        received.set()

    monkeypatch.setattr(runtime, "_dispatch_evaluation", slow_dispatch)
    evaluation = Thread(target=runtime.evaluate_after_camera_update, args=(1,))
    reader = Thread(target=read_status)
    evaluation.start()
    try:
        assert entered.wait(1)
        reader.start()
        assert received.wait(.5), "读取总览状态被告警分发持有的保安室锁阻塞"
        assert values[0].status == initial.status
        values[0].camera_states.clear()
        assert runtime.get_site_status(1).camera_states
    finally:
        release.set()
        evaluation.join(2)
        if reader.ident is not None:
            reader.join(2)


def test_guard_published_status_clears_when_site_is_reloaded_or_removed(guard_runtime, monkeypatch):
    monkeypatch.setattr(guard_runtime, "_dispatch_evaluation", lambda *args: None)
    assert guard_runtime.evaluate_after_camera_update(1) is not None
    guard_runtime.reload_site(1)
    assert guard_runtime.get_site_status(1) is None
    assert guard_runtime.evaluate_after_camera_update(1) is not None
    guard_runtime.remove_site(1)
    assert guard_runtime.get_site_status(1) is None


def test_guard_published_status_expires_without_new_evaluation(guard_runtime, monkeypatch):
    monkeypatch.setattr(guard_runtime, "_dispatch_evaluation", lambda *args: None)
    monkeypatch.setattr(guard_runtime, "_clock", lambda: 1000.)
    guard_runtime.evaluate_after_camera_update(1)
    assert guard_runtime.get_site_status(1) is not None
    monkeypatch.setattr(guard_runtime, "_clock", lambda: 2000.)
    assert guard_runtime.get_site_status(1) is None


def test_overview_returns_while_guard_alarm_dispatch_is_blocked(api, guard_runtime, monkeypatch):
    api.runtime.guard_behavior_runtime = guard_runtime
    api.guards.list_overview_sites.return_value = [{
        "id": 1, "name": "测试保安室", "department": api.departments[0], "enabled": True,
        "members": [{"camera_id": 1, "member_enabled": True}],
    }]
    entered, release, received = Event(), Event(), Event()
    responses, failures = [], []

    def slow_dispatch(*args):
        entered.set()
        assert release.wait(3)

    def read_overview():
        try:
            responses.append(api.client.get("/api/overview"))
        except Exception as exc:
            failures.append(exc)
        finally:
            received.set()

    monkeypatch.setattr(guard_runtime, "_dispatch_evaluation", slow_dispatch)
    evaluation = Thread(target=guard_runtime.evaluate_after_camera_update, args=(1,))
    reader = Thread(target=read_overview)
    evaluation.start()
    try:
        assert entered.wait(1)
        reader.start()
        assert received.wait(1), "保安室告警阻塞时整个总览请求没有返回"
        assert not failures, str(failures)
        assert responses[0].status_code == 200
        data = responses[0].json()
        assert data["inventory_complete"] is True
        assert len(data["cameras"]) == len(api.departments)
        assert data["cameras"][0]["site_id"] == 1
    finally:
        release.set()
        evaluation.join(2)
        if reader.ident is not None:
            reader.join(2)
