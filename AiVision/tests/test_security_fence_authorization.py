"""摄像头围栏授权、接口边界和离线迁移回归；只使用内存数据库。"""
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def database(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "fence_test",
        "MYSQL_DB_PASSWORD": "fence_test", "MYSQL_DB_NAME": "fence_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "fence-test-signing-key-0000000000",
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.features.face_recognition.library import service
    from AiVision.features.face_recognition.library.orm import FacePersonAuthorization
    from AiVision.migrations import security_fence_camera_authorization_20261105 as migration

    engines = []

    def make(*, legacy=False, authorizations=True):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        engines.append(engine)
        config, authorization, _ = migration._tables()
        metadata = config.metadata
        persons = metadata.tables["ai_face_person"]
        cameras = metadata.tables["ai_camera_config"]
        metadata.create_all(engine, tables=[persons, cameras, metadata.tables["ai_horn_config"], config])
        FacePersonAuthorization.__table__.create(engine)
        stored = migration._authorization_table() if legacy else authorization
        if authorizations:
            stored.create(engine)
        with engine.begin() as connection:
            connection.execute(persons.insert(), [
                {"id": person_id, "hik_source": "one", "hik_person_id": str(person_id),
                 "person_name": f"人员{person_id}", "is_active": person_id != 789,
                 "last_synced_at": datetime(2026, 11, 5)}
                for person_id in (123, 456, 789)
            ])
            connection.execute(cameras.insert(), [
                {"id": camera_id, "name": f"摄像头{camera_id}", "shm_name": f"camera_{camera_id}",
                 "url": "rtsp://camera.example.test/live",
                 "department": "electronics_electrician" if camera_id == 3 else "general_electric"}
                for camera_id in (1, 2, 3, 4)
            ])
            connection.execute(config.insert(), [{"camera_id": camera_id, "enable": camera_id != 2}
                                                for camera_id in (1, 2, 3)])

        @contextmanager
        def session_scope():
            with Session(engine, expire_on_commit=False) as session:
                with session.begin():
                    yield session

        monkeypatch.setattr(service, "get_session", lambda: Session(engine))
        monkeypatch.setattr(service, "session_scope", session_scope)
        return SimpleNamespace(engine=engine, config=config, authorization=authorization, stored=stored,
                               cameras=cameras, persons=persons, migration=migration)

    yield make
    for engine in engines:
        engine.dispose()


def test_camera_grants_filters_and_face_permissions_are_independent(database):
    database()
    from AiVision.features.security_fence.service import person_library as fence
    from AiVision.features.face_recognition.library.service import FaceLibraryService

    face = FaceLibraryService()
    assert fence.update_person_allowed(123, True, camera_id=1).is_allowed
    assert fence.get_allowed_person_ids(camera_id=1) == {123}
    assert fence.get_allowed_person_ids(camera_id=2) == set()
    assert fence.list_persons(camera_id=1, is_allowed=True).total == 1
    assert fence.list_persons(camera_id=2, is_allowed=False).total == 3
    assert fence.list_persons(camera_id=1, is_allowed=False, keyword="456").items[0].id == 456
    assert face.get_allowed_person_ids("general_electric") == set()
    assert face.update_person_allowed(456, True, department="general_electric").is_allowed
    assert face.get_allowed_person_ids("general_electric") == {456}
    assert face.get_allowed_person_ids("electronics_electrician") == set()
    assert fence.get_allowed_person_ids(camera_id=1) == {123}
    assert fence.update_person_allowed(123, True, camera_id=2).is_allowed
    assert not fence.update_person_allowed(123, False, camera_id=1).is_allowed
    assert fence.get_allowed_person_ids(camera_id=2) == {123}
    assert fence.update_person_allowed(789, True, camera_id=1).is_allowed
    assert fence.get_allowed_person_ids(camera_id=1) == set()
    assert fence.update_person_allowed(999, True, camera_id=1) is None


def test_batch_camera_authorizations_use_one_select_and_preserve_empty_scopes(database):
    db = database()
    from AiVision.features.security_fence.service import person_library

    with db.engine.begin() as connection:
        connection.execute(db.authorization.insert(), [
            {"camera_id": 1, "person_id": 123}, {"camera_id": 2, "person_id": 456},
            {"camera_id": 3, "person_id": 789},
        ])
    statements, lifecycle = [], []
    event.listen(db.engine, "before_cursor_execute",
                 lambda connection, cursor, statement, parameters, context, many: statements.append(statement))
    event.listen(db.engine, "checkin", lambda *_: lifecycle.append("checkin"))
    assert person_library.get_allowed_person_ids_by_camera(
        [2, 1, 3, 4, 1], on_sampled=lambda: lifecycle.append("sampled"),
    ) == {
        1: {123}, 2: {456}, 3: set(), 4: set(),
    }
    assert len(statements) == 1 and statements[0].lstrip().upper().startswith("SELECT")
    assert lifecycle == ["sampled", "checkin"]
    assert person_library.get_allowed_person_ids_by_camera([]) == {}
    assert len(statements) == 1


@pytest.mark.parametrize("camera_ids", [[0], [True], ["1"]])
def test_batch_camera_authorizations_reject_invalid_scopes(database, camera_ids):
    database()
    from AiVision.features.security_fence.service import person_library
    from AiVision.features.face_recognition.library.service import FaceLibraryService

    with pytest.raises(ValueError, match="摄像头"):
        person_library.get_allowed_person_ids_by_camera(camera_ids)
    with pytest.raises(ValueError, match="摄像头"):
        FaceLibraryService().get_allowed_person_ids_by_camera([1])


@pytest.mark.parametrize("scope", [{}, {"department": "general_electric"}, {"camera_id": 0},
                                 {"camera_id": True}, {"camera_id": 1, "department": "general_electric"}])
def test_fence_service_requires_camera_scope(database, scope):
    database()
    from AiVision.features.security_fence.service import person_library

    with pytest.raises(ValueError, match="摄像头"):
        person_library.list_persons(**scope)


def test_deleting_camera_only_clears_its_own_grants(database):
    db = database()
    from AiVision.features.security_fence.service import person_library

    for camera_id in (1, 2):
        person_library.update_person_allowed(123, True, camera_id=camera_id)
    with db.engine.begin() as connection:
        connection.execute(db.cameras.delete().where(db.cameras.c.id == 1))
    assert person_library.get_allowed_person_ids(camera_id=1) == set()
    assert person_library.get_allowed_person_ids(camera_id=2) == {123}


def test_migration_is_read_only_until_applied_and_does_not_restore_revocations(database):
    db = database(legacy=True)
    with db.engine.begin() as connection:
        connection.execute(db.stored.insert(), [
            {"department": "general_electric", "person_id": 123},
            {"department": "electronics_electrician", "person_id": 456},
        ])
    before = set(inspect(db.engine).get_table_names())
    state = db.migration.check(db.engine)
    assert state["needs_migration"] and state["camera_authorizations"] == {"1": 1, "2": 1, "3": 1}
    assert set(inspect(db.engine).get_table_names()) == before
    assert db.migration.apply(db.engine)["copied"] == 3
    assert db.migration.check(db.engine)["authorization_scope"] == "camera"
    from AiVision.features.security_fence.service import person_library

    assert person_library.get_allowed_person_ids(camera_id=1) == {123}
    assert person_library.get_allowed_person_ids(camera_id=2) == {123}
    assert person_library.get_allowed_person_ids(camera_id=3) == {456}
    assert person_library.get_allowed_person_ids(camera_id=4) == set()
    person_library.update_person_allowed(123, False, camera_id=1)
    assert db.migration.apply(db.engine)["copied"] == 0
    assert person_library.get_allowed_person_ids(camera_id=1) == set()
    assert person_library.get_allowed_person_ids(camera_id=2) == {123}
    with db.engine.connect() as connection:
        assert len(connection.exec_driver_sql(f"SELECT * FROM {db.migration.BACKUP_TABLE}").all()) == 2


def test_migration_creates_missing_authorization_table(database):
    db = database(authorizations=False)
    assert db.migration.check(db.engine)["needs_authorization_table"]
    assert not db.migration.apply(db.engine)["needs_authorization_table"]


def test_camera_without_department_does_not_inherit_grants(database):
    db = database(legacy=True)
    with db.engine.begin() as connection:
        connection.execute(db.stored.insert(), {"department": "general_electric", "person_id": 123})
        connection.execute(db.cameras.update().where(db.cameras.c.id == 3).values(department=None))
    assert db.migration.check(db.engine)["camera_authorizations"] == {"1": 1, "2": 1}
    assert db.migration.apply(db.engine)["copied"] == 2
    from AiVision.features.security_fence.service import person_library

    assert person_library.get_allowed_person_ids(camera_id=3) == set()


def test_migration_keeps_source_if_copy_fails_then_can_retry(database, monkeypatch):
    db = database(legacy=True)
    with db.engine.begin() as connection:
        connection.execute(db.stored.insert(), {"department": "general_electric", "person_id": 123})
    original = db.migration._camera_rows
    monkeypatch.setattr(db.migration, "_camera_rows", lambda *args: [(999, 123, datetime(2026, 11, 5))])
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db.migration.apply(db.engine)
    assert "department" in {column["name"] for column in inspect(db.engine).get_columns(db.stored.name)}
    monkeypatch.setattr(db.migration, "_camera_rows", original)
    assert db.migration.apply(db.engine)["copied"] == 2


@pytest.mark.parametrize("role", ["admin", "department_admin"])
def test_camera_person_routes_preserve_access_control(database, role):
    database()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth.auth import get_current_user
    from AiVision.api.deps import get_camera_config_manager
    from AiVision.api.routes.security_fence import router

    cameras = {f"camera_{camera_id}": {
        "camera_id": camera_id, "shm_name": f"camera_{camera_id}", "name": f"相机{camera_id}",
        "department": "electronics_electrician" if camera_id == 3 else "general_electric",
        "functions": {"security_fence": True}, "enabled": True,
    } for camera_id in (1, 2, 3)}
    current_user = {"role": role, "departments": ["general_electric"],
                    "feature_access": {"general_electric": ["security_fence"]}}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_camera_config_manager] = lambda: SimpleNamespace(get_camera=cameras.get)
    with TestClient(app) as client:
        path = "/api/security-fence/cameras/camera_1/persons"
        assert client.patch(f"{path}/123", json={"is_allowed": True}).json()["is_allowed"]
        assert client.get(path, params={"is_allowed": True}).json()["total"] == 1
        assert client.get(path.replace("camera_1", "camera_2"), params={"is_allowed": True}).json()["total"] == 0
        assert client.patch(f"{path}/999", json={"is_allowed": True}).status_code == 404
        assert client.get(path.replace("camera_1", "missing")).status_code == 404
        assert client.get(path.replace("camera_1", "camera_3")).status_code == 403
        assert client.patch(path.replace("camera_1", "camera_3") + "/123", json={"is_allowed": True}).status_code == 403
        assert client.get("/api/security-fence/persons?department=general_electric").status_code == 404
        current_user["role"] = "viewer"
        assert client.get(path).status_code == 200
        assert client.patch(f"{path}/123", json={"is_allowed": False}).status_code == 403
        current_user["feature_access"] = {}
        assert client.get(path).status_code == 403
