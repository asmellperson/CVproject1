"""人脸识别白名单的事业部隔离、接口授权、识别判定与离线迁移回归。"""
from datetime import datetime
from queue import Queue
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, Boolean, MetaData, create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

GENERAL = "general_electric"
ELECTRONICS = "electronics_electrician"
COMPONENTS = "electrical_components"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """只使用临时目录与内存数据库，不读取或连接部署环境数据库。"""
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test",
        "MYSQL_DB_PASSWORD": "test", "MYSQL_DB_NAME": "test",
        "DATA_PATH": str(tmp_path), "AUTO_CREATE_DB": "false",
    }.items():
        monkeypatch.setenv(key, value)


def person_values(person_id, *, active=True):
    """生成可被识别且不包含真实人员信息的资料。"""
    return {
        "id": person_id, "hik_source": "one", "hik_person_id": f"person-{person_id}",
        "person_name": f"测试人员{person_id}", "is_active": active,
        "last_synced_at": datetime(2026, 10, 16),
    }


@pytest.fixture
def library(monkeypatch):
    """替换人员服务的会话工厂，使接口、运行时和迁移共享同一隔离库。"""
    from AiVision.features.face_recognition.library import service as module
    from AiVision.features.face_recognition.library.orm import FacePerson, FacePersonAuthorization

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    FacePerson.__table__.create(engine)
    FacePersonAuthorization.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(module, "get_session", factory)
    monkeypatch.setattr(module, "session_scope", factory.begin)
    with factory.begin() as session:
        session.add_all([FacePerson(**person_values(1)), FacePerson(**person_values(2)),
                         FacePerson(**person_values(3, active=False))])
    yield module.FaceLibraryService()
    engine.dispose()


def allowed(service, department):
    """返回当前事业部列表中的允许状态，覆盖 API 使用的同一查询。"""
    return {person.id: person.is_allowed for person in service.list_persons(department=department).items}


def test_grants_and_revocations_are_independent_between_departments(library):
    """同一人可分别授权，重复操作幂等，取消一个事业部不影响另一个。"""
    assert library.update_person_allowed(1, True, department=GENERAL).is_allowed
    assert library.update_person_allowed(1, True, department=GENERAL).is_allowed
    assert allowed(library, GENERAL) == {1: True, 2: False, 3: False}
    assert allowed(library, ELECTRONICS) == {1: False, 2: False, 3: False}
    assert allowed(library, COMPONENTS) == {1: False, 2: False, 3: False}
    library.update_person_allowed(1, True, department=ELECTRONICS)
    assert not library.update_person_allowed(1, False, department=GENERAL).is_allowed
    assert not library.update_person_allowed(1, False, department=GENERAL).is_allowed
    assert not allowed(library, GENERAL)[1]
    assert allowed(library, ELECTRONICS)[1]
    assert library.update_person_allowed(999, True, department=GENERAL) is None


def test_filters_counts_and_active_runtime_ids_use_current_department(library):
    """允许筛选、分页计数及识别集合不会借用其他事业部授权，停用人员不放行。"""
    library.update_person_allowed(1, True, department=GENERAL)
    library.update_person_allowed(3, True, department=GENERAL)
    library.update_person_allowed(2, True, department=ELECTRONICS)
    page = library.list_persons(department=GENERAL, is_allowed=True, page_size=1, page=2)
    assert page.total == 2 and [person.id for person in page.items] == [3]
    assert library.list_persons(department=ELECTRONICS, is_allowed=True).total == 1
    assert [person.id for person in library.list_persons(department=GENERAL, is_allowed=False).items] == [2]
    assert library.get_allowed_person_ids(GENERAL) == {1}
    assert library.get_allowed_person_ids(ELECTRONICS) == {2}
    assert library.get_allowed_person_ids(COMPONENTS) == set()
    assert library.list_persons(department=GENERAL, keyword="测试人员1", is_allowed=True).total == 1
    for action in (
        lambda: library.list_persons(department="invalid"),
        lambda: library.update_person_allowed(1, True, department="invalid"),
        lambda: library.get_allowed_person_ids("invalid"),
    ):
        with pytest.raises(ValueError, match="unknown department"):
            action()


@pytest.fixture
def client(library):
    """只装载人脸识别接口，实际执行权限依赖与数据库读写。"""
    from auth.auth import get_current_user
    from AiVision.api.routes.face_recognition import router

    user = {"role": "admin", "departments": ["all"], "feature_access": {
        GENERAL: ["recognize_face"], ELECTRONICS: ["recognize_face"], COMPONENTS: [],
    }}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as http:
        yield http, user


def test_api_requires_department_and_returns_independent_saved_state(client):
    """缺少归属不落库，读写和筛选均针对请求指定事业部。"""
    http, _user = client
    assert http.get("/api/face-recognition/persons").status_code == 422
    assert http.patch("/api/face-recognition/persons/1", json={"is_allowed": True}).status_code == 422
    response = http.patch(f"/api/face-recognition/persons/1?department={GENERAL}", json={"is_allowed": True})
    assert response.status_code == 200 and response.json()["is_allowed"] is True
    assert http.get(f"/api/face-recognition/persons?department={GENERAL}&is_allowed=true").json()["total"] == 1
    assert http.get(f"/api/face-recognition/persons?department={ELECTRONICS}&is_allowed=true").json()["total"] == 0
    assert http.patch(f"/api/face-recognition/persons/999?department={GENERAL}", json={"is_allowed": True}).status_code == 404


@pytest.mark.parametrize("role", ["admin", "viewer"])
def test_api_enforces_department_feature_access_and_admin_writes(client, role):
    """管理员也遵守事业部功能分配，普通账号只能查看自己获准的事业部。"""
    http, user = client
    user.update(role=role, departments=[GENERAL])
    for department in (COMPONENTS, "invalid"):
        assert http.get(f"/api/face-recognition/persons?department={department}").status_code == 403
        assert http.patch(f"/api/face-recognition/persons/1?department={department}", json={"is_allowed": True}).status_code == 403
    assert http.get(f"/api/face-recognition/persons?department={GENERAL}").status_code == 200
    expected = 200 if role == "admin" else 403
    assert http.patch(f"/api/face-recognition/persons/1?department={GENERAL}", json={"is_allowed": True}).status_code == expected
    if role == "viewer":
        assert http.get(f"/api/face-recognition/persons?department={ELECTRONICS}").status_code == 403


def test_consumer_shares_department_whitelist_across_cameras_without_crossing(library, monkeypatch):
    """同部多摄像头共用名单，切换事业部与刷新撤权均不误用其他缓存。"""
    from AiVision.features.face_recognition.consumer import FaceRecognitionConsumer

    consumer = FaceRecognitionConsumer(SimpleNamespace(name="recognize_face"), {}, Queue(), {}, lambda _key: True)
    consumer.config_cache = {1: {"department": GENERAL}, 2: {"department": ELECTRONICS}, 3: {"department": GENERAL}}
    monkeypatch.setattr(consumer, "dispatch_inference_sync", lambda *args, **kwargs: {
        "status": "ok", "detections": [{"matched": True, "person_id": 1}],
    })
    library.update_person_allowed(1, True, department=GENERAL)
    assert consumer._process(None, 1)[1]["detections"][0]["is_allowed"] is True
    assert consumer._process(None, 3)[1]["detections"][0]["is_allowed"] is True
    assert consumer._process(None, 2)[1]["detections"][0]["is_allowed"] is False
    library.update_person_allowed(1, True, department=ELECTRONICS)
    consumer._authorization_refresh_at[ELECTRONICS] = 0
    assert consumer._process(None, 2)[1]["detections"][0]["is_allowed"] is True
    library.update_person_allowed(1, False, department=GENERAL)
    consumer._authorization_refresh_at[GENERAL] = 0
    assert consumer._process(None, 3)[1]["detections"][0]["is_allowed"] is False
    assert consumer._process(None, 2)[1]["detections"][0]["is_allowed"] is True
    consumer.config_cache[2]["department"] = GENERAL
    assert consumer._process(None, 2)[1]["detections"][0]["is_allowed"] is False
    consumer.config_cache[2]["department"] = None
    with pytest.raises(ValueError, match="unknown department"):
        consumer._process(None, 2)


def test_consumer_does_not_reuse_expired_permissions_when_refresh_fails(library, monkeypatch):
    """数据库刷新失败必须报告异常，不能沿用过期允许状态。"""
    from AiVision.features.face_recognition.consumer import FaceRecognitionConsumer

    consumer = FaceRecognitionConsumer(SimpleNamespace(name="recognize_face"), {}, Queue(), {}, lambda _key: True)
    consumer.config_cache = {1: {"department": GENERAL}}
    consumer._allowed_person_ids[GENERAL] = {1}
    monkeypatch.setattr(consumer, "dispatch_inference_sync", lambda *args, **kwargs: {
        "status": "ok", "detections": [{"matched": True, "person_id": 1}],
    })
    def unavailable(_department):
        """模拟数据库读取异常。"""
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(consumer.library, "get_allowed_person_ids", unavailable)
    with pytest.raises(RuntimeError, match="database unavailable"):
        consumer._process(None, 1)


@pytest.fixture
def legacy_engine():
    """复现包含全局标记的部署表，覆盖迁移前后两种真实 SQL 结构。"""
    from AiVision.features.face_recognition.library.orm import FacePerson

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    persons = FacePerson.__table__.to_metadata(MetaData())
    persons.append_column(Column("is_allowed", Boolean, nullable=False, server_default=text("0")))
    persons.create(engine)
    with engine.begin() as connection:
        connection.execute(persons.insert(), [{**person_values(1), "is_allowed": True},
                                             {**person_values(2), "is_allowed": False},
                                             {**person_values(3, active=False), "is_allowed": True}])
    yield engine
    engine.dispose()


def test_migration_is_read_only_until_applied_and_preserves_general_whitelist(legacy_engine):
    """原名单完整归通用电气，其他事业部为空，重复执行不恢复已取消的授权。"""
    from AiVision.features.face_recognition.library.orm import FacePersonAuthorization
    from AiVision.migrations.face_person_authorization_20261016 import apply, check

    assert check(legacy_engine) == {
        "needs_migration": True, "needs_authorization_table": True, "legacy_allowed_persons": 2,
    }
    assert not inspect(legacy_engine).has_table(FacePersonAuthorization.__tablename__)
    result = apply(legacy_engine, legacy_department=GENERAL)
    assert result["copied"] == 2 and not result["needs_migration"]
    table = FacePersonAuthorization.__table__
    with legacy_engine.begin() as connection:
        assert set(connection.execute(select(table.c.department, table.c.person_id))) == {(GENERAL, 1), (GENERAL, 3)}
        connection.execute(table.delete().where(table.c.person_id == 1))
    assert apply(legacy_engine, legacy_department=GENERAL)["copied"] == 0
    with legacy_engine.connect() as connection:
        assert set(connection.scalars(select(table.c.person_id))) == {3}


def test_migration_rejects_unknown_department_and_resumes_after_table_creation(legacy_engine):
    """非法归属不写库，中途仅完成建表和部分复制时可安全继续。"""
    from AiVision.features.face_recognition.library.orm import FacePersonAuthorization
    from AiVision.migrations.face_person_authorization_20261016 import apply

    table = FacePersonAuthorization.__table__
    with pytest.raises(ValueError, match="unknown department"):
        apply(legacy_engine, legacy_department="invalid")
    assert not inspect(legacy_engine).has_table(table.name)
    table.create(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(table.insert().values(department=GENERAL, person_id=1))
    assert apply(legacy_engine, legacy_department=GENERAL)["copied"] == 1
