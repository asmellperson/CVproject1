"""围栏事业部授权、运行时撤销和历史名单迁移的隔离回归验证。"""
from datetime import datetime, timezone
import json
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


A = "general_electric"
B = "electronics_electrician"
NOW = datetime(2026, 10, 22, 4, tzinfo=timezone.utc)


def memory_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture
def backend(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "tests", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "tests", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.core import db
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.alarms.devices.orm import AiHornConfig
    from AiVision.features.face_recognition.library import service as library_service
    from AiVision.features.face_recognition.library.orm import FacePerson, FacePersonAuthorization
    from AiVision.features.security_fence import consumer, service
    from AiVision.features.security_fence.orm import FenceConfigORM, FencePersonAuthorization
    from AiVision.features.security_fence.runtime import FenceRuntime
    from AiVision.features.security_fence.schema import FenceValue
    from AiVision.migrations import security_fence_authorization_20261022 as migration

    engine = memory_engine()
    parents = [AiCameraConfig.__table__, AiHornConfig.__table__, FacePerson.__table__, FacePersonAuthorization.__table__]
    db.Base.metadata.create_all(engine, tables=[*parents, FenceConfigORM.__table__, FencePersonAuthorization.__table__])
    factory = sessionmaker(engine, expire_on_commit=False)
    for module in (db, library_service, service):
        monkeypatch.setattr(module, "get_session", factory)
    with factory.begin() as session:
        session.add_all([FacePerson(
            id=person_id, hik_source="one" if person_id < 3 else "two", hik_person_id=f"person-{person_id}",
            person_name=f"员工{person_id}", job_no=f"job-{person_id}", person_code=f"code-{person_id}",
            org_index_code="org", pic_uri=f"photo-{person_id}", server_index_code="server",
            is_active=person_id != 3, last_synced_at=NOW.replace(tzinfo=None),
        ) for person_id in (1, 2, 3)])
    yield SimpleNamespace(
        engine=engine, session=factory, parents=parents, camera=AiCameraConfig, person=FacePerson,
        face_authorization=FacePersonAuthorization, authorization=FencePersonAuthorization,
        config=FenceConfigORM, value=FenceValue, runtime=FenceRuntime, consumer=consumer,
        service=service, library_service=library_service, migration=migration,
    )
    engine.dispose()


@pytest.fixture
def api(backend):
    from auth.auth import get_current_user
    from AiVision.api.routes import security_fence, face_recognition

    user = {"role": "admin", "departments": [A, B],
            "feature_access": {A: ["security_fence", "recognize_face"], B: ["security_fence", "recognize_face"]}}
    app = FastAPI()
    app.include_router(security_fence.router)
    app.include_router(face_recognition.router)
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, user=user)


def test_department_permissions_are_saved_without_any_camera_and_default_to_denied(backend, api):
    path = "/api/security-fence/persons"
    result = api.client.get(path, params={"department": A}).json()
    assert result["total"] == 3
    assert all(not person["is_allowed"] for person in result["items"])
    saved = api.client.patch(f"{path}/1", params={"department": A}, json={"is_allowed": True})
    assert saved.status_code == 200
    assert saved.json()["is_allowed"] is True
    assert backend.service.person_library.get_allowed_person_ids(A) == {1}
    assert backend.service.person_library.get_allowed_person_ids(B) == set()
    assert api.client.get(path, params={"department": B, "is_allowed": True}).json()["total"] == 0
    allowed = api.client.get(path, params={"department": A, "is_allowed": True, "keyword": "job-1"}).json()
    assert allowed["total"] == 1
    assert allowed["items"][0]["id"] == 1
    for _ in range(2):
        assert api.client.patch(f"{path}/1", params={"department": A}, json={"is_allowed": False}).status_code == 200
    assert backend.service.person_library.get_allowed_person_ids(A) == set()


def test_fence_and_face_recognition_keep_independent_department_permissions(backend, api):
    fence = backend.service.person_library
    face = backend.library_service.FaceLibraryService()
    fence.update_person_allowed(1, True, department=A)
    face.update_person_allowed(2, True, department=A)
    assert face.get_allowed_person_ids(A) == {2}
    assert fence.get_allowed_person_ids(A) == {1}
    for feature, expected in [("security-fence", 1), ("face-recognition", 2)]:
        result = api.client.get(f"/api/{feature}/persons", params={"department": A, "is_allowed": True}).json()
        assert [person["id"] for person in result["items"]] == [expected]
    fence.update_person_allowed(1, False, department=A)
    assert face.get_allowed_person_ids(A) == {2}


def test_inactive_people_are_excluded_from_runtime_and_filters_count_the_same_rows(backend, api):
    backend.service.person_library.update_person_allowed(3, True, department=A)
    assert backend.service.person_library.get_allowed_person_ids(A) == set()
    result = api.client.get("/api/security-fence/persons", params={
        "department": A, "source": "two", "is_active": False, "is_allowed": True, "page_size": 1,
    }).json()
    assert result["total"] == 1
    assert [person["id"] for person in result["items"]] == [3]


def test_person_sync_keeps_existing_fence_authorizations_and_denies_new_people(backend):
    from AiVision.connectors.hikvision import HikvisionPerson

    backend.service.person_library.update_person_allowed(1, True, department=A)
    counts = backend.library_service.FaceLibraryService().apply_snapshot("one", [
        HikvisionPerson(personId=f"person-{person_id}", personName=f"同步员工{person_id}")
        for person_id in (1, 2, 4)
    ])
    assert counts.inserted == 1
    assert backend.service.person_library.get_allowed_person_ids(A) == {1}
    people = backend.service.person_library.list_persons(department=A)
    added = next(person for person in people.items if person.hik_person_id == "person-4")
    assert added.is_allowed is False


def test_read_access_is_separate_from_administrator_write_access(backend, api):
    path = "/api/security-fence/persons"
    api.user["role"] = "viewer"
    assert api.client.get(path, params={"department": A}).status_code == 200
    assert api.client.patch(f"{path}/1", params={"department": A}, json={"is_allowed": True}).status_code == 403
    api.user["role"] = "admin"
    api.user["feature_access"][B] = ["recognize_face"]
    assert api.client.get(path, params={"department": B}).status_code == 403
    assert api.client.patch(f"{path}/1", params={"department": B}, json={"is_allowed": True}).status_code == 403
    assert api.client.get(path).status_code == 422


@pytest.mark.parametrize("payload", [{"is_allowed": 1}, {"is_allowed": True, "department": B}])
def test_permission_payload_is_strict_and_cannot_override_department(api, payload):
    assert api.client.patch("/api/security-fence/persons/1", params={"department": A}, json=payload).status_code == 422


def test_missing_person_is_rejected_and_camera_payload_cannot_set_permissions(backend, api):
    assert api.client.patch("/api/security-fence/persons/99", params={"department": A}, json={"is_allowed": True}).status_code == 404
    with pytest.raises(ValidationError):
        backend.value.model_validate({"allowed_person_ids": [1]})


def test_deleting_a_camera_keeps_department_authorizations_but_deleting_a_person_cleans_them(backend):
    with backend.session.begin() as session:
        session.add(backend.camera(id=1, name="入口", url="unused", shm_name="camera_1", department=A))
    backend.service.person_library.update_person_allowed(1, True, department=A)
    with backend.session.begin() as session:
        session.delete(session.get(backend.camera, 1))
    assert backend.service.person_library.get_allowed_person_ids(A) == {1}
    with backend.session.begin() as session:
        session.delete(session.get(backend.person, 1))
    assert backend.service.person_library.get_allowed_person_ids(A) == set()


def observation():
    return [{"bbox": [0., 0., 100., 200.]}], [{
        "bbox": [20., 20., 80., 80.], "matched": True, "person_id": 1,
        "person_name": "员工1", "job_no": "job-1", "org_index_code": "org", "similarity": .95,
    }]


def test_runtime_uses_current_department_permissions_and_revocation_keeps_identity(backend):
    runtime = backend.runtime(backend.value(confirmation_frames=2))
    people, faces = observation()

    def update(moment, allowed=()):
        return runtime.update(people, faces, (240, 320, 3), now=NOW, monotonic=moment, allowed_person_ids=allowed)[0]

    assert update(0).identity == "pending"
    assert update(.2).identity == "unauthorized"
    assert update(.4, {1}).identity == "allowed"
    revoked = update(.6)
    assert revoked.person_id == 1
    assert revoked.identity == "unauthorized"
    assert revoked.reason == "unauthorized"


def test_consumer_shares_permissions_within_department_and_refreshes_revocation(backend, monkeypatch):
    consumer = backend.consumer.FenceConsumer.__new__(backend.consumer.FenceConsumer)
    consumer.library = Mock(wraps=backend.service.person_library)
    consumer._allowed_person_ids, consumer._authorization_refresh_at = {}, {}
    clock = [10.]
    monkeypatch.setattr(backend.consumer.time, "monotonic", lambda: clock[0])
    backend.service.person_library.update_person_allowed(1, True, department=A)
    assert consumer._department_allowed_people(A) == {1}
    assert consumer._department_allowed_people(A) == {1}
    assert consumer.library.get_allowed_person_ids.call_count == 1
    assert consumer._department_allowed_people(B) == set()
    backend.service.person_library.update_person_allowed(1, False, department=A)
    clock[0] += backend.consumer.AUTHORIZATION_REFRESH_SECONDS + .01
    assert consumer._department_allowed_people(A) == set()
    assert consumer.library.get_allowed_person_ids.call_count == 3


@pytest.mark.parametrize("forbidden", [False, True])
def test_authorization_read_failure_removes_old_allowance_and_publishes_an_error(backend, monkeypatch, forbidden):
    consumer = backend.consumer.FenceConsumer.__new__(backend.consumer.FenceConsumer)
    value = backend.value(confirmation_frames=2, forbidden_start="00:00", forbidden_end="00:00" if forbidden else "00:01")
    consumer.config_cache = {1: {**value.model_dump(), "department": A, "shm_name": "camera_1"}}
    consumer.runtimes, consumer.processed_frames = {}, {}
    consumer._allowed_person_ids, consumer._authorization_refresh_at = {A: {1}}, {A: 0.}
    consumer.library = Mock()
    consumer.library.get_allowed_person_ids.side_effect = RuntimeError("sensitive parameters")
    people, faces = observation()
    consumer.dispatch_inference_sync = lambda camera, model, frame, **kwargs: {
        "status": "ok", "detections": people if model == "yolo_human" else faces,
    }
    monkeypatch.setattr(backend.consumer, "datetime", SimpleNamespace(now=lambda zone: NOW))
    alarm, result = consumer._process(np.zeros((240, 320, 3), dtype=np.uint8), 1)
    assert result["persons"][0]["identity"] == "pending"
    assert "白名单读取失败" in result["error"]
    assert "sensitive" not in result["error"]
    assert A not in consumer._allowed_person_ids
    assert alarm is forbidden


@pytest.fixture
def monitor_status(backend, monkeypatch):
    value = backend.value(forbidden_start="00:00", forbidden_end="00:00")
    config = {"enable": True, "value": value.model_dump()}
    camera = {"camera_id": 1, "shm_name": "camera_1", "name": "围栏入口", "department": A,
              "enabled": True, "functions": {"security_fence": True}}
    snapshot = {"updated_at_s": 1000.0, "mode": "forbidden", "error": None,
                "count": 2, "pending_count": 1, "alarm": False, "persons": [],
                "frame_width": 320, "frame_height": 240}
    consumer = SimpleNamespace(running=True, get_monitor_status=lambda key: snapshot)
    manager = Mock()
    manager.list_running.return_value = ["camera_1"]
    orchestrator = SimpleNamespace(consumers={"security_fence": consumer}, camera_runtime_manager=manager)
    monkeypatch.setattr(backend.service.feature_config_manager, "get_config", lambda *args: {"config": config})
    monkeypatch.setattr(backend.service.time, "time", lambda: 1000.0)
    return SimpleNamespace(camera=camera, config=config, snapshot=snapshot, consumer=consumer,
                           orchestrator=orchestrator, service=backend.service)


@pytest.mark.parametrize("age", [0., .5, 4.9, 5.])
def test_status_reports_server_remaining_lifetime_and_keeps_all_card_values(monitor_status, age):
    monitor = monitor_status
    monitor.snapshot["updated_at_s"] = 1000.0 - age
    result = monitor.service.camera_status(monitor.camera, monitor.orchestrator)
    assert result.state == "ready"
    assert result.mode == "forbidden"
    assert result.count == 2 and result.pending_count == 1
    assert result.valid_for_seconds == pytest.approx(5.0 - age)


@pytest.mark.parametrize("condition", ["expired", "future", "mode", "disabled", "offline", "stopped", "missing"])
def test_invalid_status_has_no_lifetime_or_old_counts(monitor_status, condition):
    monitor = monitor_status
    if condition == "expired":
        monitor.snapshot["updated_at_s"] = 994.9
    elif condition == "future":
        monitor.snapshot["updated_at_s"] = 1001.0
    elif condition == "mode":
        monitor.snapshot["mode"] = "whitelist"
    elif condition == "disabled":
        monitor.config["enable"] = False
    elif condition == "offline":
        monitor.orchestrator.camera_runtime_manager.list_running.return_value = []
    elif condition == "stopped":
        monitor.consumer.running = False
    else:
        monitor.orchestrator.consumers.clear()
    result = monitor.service.camera_status(monitor.camera, monitor.orchestrator)
    assert result.valid_for_seconds == 0
    assert result.state != "ready"
    assert result.count is None and result.pending_count is None
    assert result.alarm is None and result.persons == []


def test_model_error_retains_its_error_and_remaining_lifetime(monitor_status):
    monitor = monitor_status
    monitor.snapshot.update(error="人体检测不可用", updated_at_s=998.0, count=None, pending_count=None)
    result = monitor.service.camera_status(monitor.camera, monitor.orchestrator)
    assert result.state == "error"
    assert result.error == "人体检测不可用"
    assert result.alarm is None
    assert result.valid_for_seconds == 3.0


def test_platform_and_external_status_routes_return_the_same_lifetime(api, monitor_status):
    from AiVision.api import deps
    from AiVision.api.routes.external import security_fence

    monitor = monitor_status
    monitor.snapshot["updated_at_s"] = 998.0
    app = api.client.app
    app.include_router(security_fence.router, prefix="/api/external")
    app.dependency_overrides.update({
        deps.get_camera_config_manager: lambda: SimpleNamespace(
            get_camera=lambda key: monitor.camera, list_cameras=lambda **kwargs: [monitor.camera],
        ),
        deps.get_optional_orchestrator: lambda: monitor.orchestrator,
        deps.get_department_service: lambda: SimpleNamespace(feature_access=lambda: {A: ["security_fence"]}),
    })
    for path in ("/api/security-fence/cameras/camera_1/status",
                 "/api/external/security-fence/cameras/camera_1/status", "/api/external/security-fence/status"):
        response = api.client.get(path, params={"department": A})
        assert response.status_code == 200, response.text
        data = response.json()[0] if path.endswith("/security-fence/status") else response.json()
        assert data["state"] == "ready"
        assert data["mode"] == "forbidden"
        assert data["count"] == 2 and data["pending_count"] == 1
        assert data["valid_for_seconds"] == 3.0


@pytest.fixture
def legacy(backend):
    engine = memory_engine()
    backend.parents[0].metadata.create_all(engine, tables=backend.parents)
    config = backend.migration._config_table(legacy=True)
    config.create(engine)
    with backend.engine.connect() as connection:
        people = list(connection.execute(select(backend.person.__table__)).mappings())
    with engine.begin() as connection:
        connection.execute(backend.person.__table__.insert(), [dict(person) for person in people])
        connection.execute(backend.camera.__table__.insert(), [
            {"id": number, "name": f"入口{number}", "url": "unused", "shm_name": f"camera_{number}",
             "department": A if number < 3 else B} for number in (1, 2, 3)
        ])
        connection.execute(config.insert(), [
            {"camera_id": 1, "allowed_person_ids": [1, 2], "threshold": .83},
            {"camera_id": 2, "allowed_person_ids": [1, 3], "threshold": .83},
            {"camera_id": 3, "allowed_person_ids": [2], "threshold": .83},
        ])
    yield engine, config
    engine.dispose()


def test_migration_is_read_only_until_apply_and_merges_camera_lists_by_department(backend, legacy):
    engine, config = legacy
    state = backend.migration.check(engine)
    assert state["department_authorizations"] == {A: 3, B: 1}
    assert state["camera_whitelists"] == 3
    assert "allowed_person_ids" in {column["name"] for column in inspect(engine).get_columns(config.name)}
    assert not inspect(engine).has_table(backend.authorization.__tablename__)
    state = backend.migration.apply(engine)
    assert state["copied"] == 4
    assert not state["needs_migration"]
    with engine.connect() as connection:
        rows = set(connection.execute(select(backend.authorization.department, backend.authorization.person_id)).tuples())
        assert rows == {(A, 1), (A, 2), (A, 3), (B, 2)}
        assert list(connection.scalars(select(backend.config.threshold))) == [.83, .83, .83]
    assert "allowed_person_ids" not in {column["name"] for column in inspect(engine).get_columns(config.name)}
    with engine.begin() as connection:
        connection.execute(backend.authorization.__table__.delete().where(
            backend.authorization.department == A, backend.authorization.person_id == 1,
        ))
    assert backend.migration.apply(engine)["copied"] == 0
    with engine.connect() as connection:
        assert connection.scalar(select(backend.authorization.person_id).where(
            backend.authorization.department == A, backend.authorization.person_id == 1,
        )) is None


@pytest.mark.parametrize("problem", ["unknown_department", "missing_person", "invalid_ids"])
def test_migration_preserves_original_lists_if_references_are_invalid(backend, legacy, problem):
    engine, config = legacy
    with engine.begin() as connection:
        if problem == "unknown_department":
            connection.execute(backend.camera.__table__.update().where(backend.camera.id == 1).values(department="unknown"))
        else:
            connection.execute(config.update().where(config.c.camera_id == 1).values(
                allowed_person_ids=[99] if problem == "missing_person" else [True],
            ))
    with pytest.raises(ValueError):
        backend.migration.apply(engine)
    assert "allowed_person_ids" in {column["name"] for column in inspect(engine).get_columns(config.name)}
    assert not inspect(engine).has_table(backend.authorization.__tablename__)


def test_migration_can_resume_after_authorizations_have_been_partially_copied(backend, legacy):
    engine, _ = legacy
    backend.authorization.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(backend.authorization.__table__.insert(), {"department": A, "person_id": 1})
    assert backend.migration.apply(engine)["copied"] == 3


def test_empty_database_is_left_for_normal_bootstrap(backend):
    engine = memory_engine()
    try:
        assert backend.migration.apply(engine)["config_table_present"] is False
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("authorization_exists", [False, True])
def test_migration_cli_uses_fresh_processes_before_and_after_apply(backend, legacy, tmp_path, authorization_exists):
    engine, _ = legacy
    if authorization_exists:
        # 主程序在发现摄像头旧列前可能已经创建授权表，迁移也必须能处理此状态。
        backend.authorization.__table__.create(engine)
    database = tmp_path / "fence.sqlite"
    with engine.connect() as source, sqlite3.connect(database) as destination:
        source.connection.driver_connection.backup(destination)

    # 每次都运行真正的 CLI 入口，避免父进程预先导入 ORM 掩盖外键依赖遗漏。
    script = """
import runpy
import sys
import sqlalchemy

engine = sqlalchemy.create_engine(sys.argv[1])
sqlalchemy.create_engine = lambda *args, **kwargs: engine
sys.argv = ["AiVision.migrations.security_fence_authorization_20261022", *sys.argv[2:]]
runpy.run_module(sys.argv[0], run_name="__main__")
"""

    def invoke(*args):
        result = subprocess.run([
            sys.executable, "-c", script, f"sqlite:///{database}", *args,
        ], capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    for args in ((), ("--check",)):
        state = invoke(*args)
        assert state["needs_migration"] is True
        assert state["needs_authorization_table"] is not authorization_exists
        assert state["department_authorizations"] == {A: 3, B: 1}
    assert invoke("--apply", "--offline")["copied"] == 4
    state = invoke("--check")
    assert state["needs_migration"] is False
    assert state["needs_authorization_table"] is False
    assert invoke("--apply", "--offline")["copied"] == 0


def test_migration_cli_refuses_apply_without_explicit_offline_confirmation():
    result = subprocess.run([
        sys.executable, "-m", "AiVision.migrations.security_fence_authorization_20261022", "--apply",
    ], capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 2
    assert "--offline" in result.stderr
