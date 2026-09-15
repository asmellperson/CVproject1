"""真实 SQLite 事务和管理员路由；设备 HTTP 全部替换为测试响应。"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from auth.auth import get_current_user
from AiVision.api.deps import get_horn_service, get_horn_runtime_manager
from AiVision.api.routes.horns import router
from AiVision.core.db import Base
from AiVision.features.registry import all_specs
from AiVision.alarms.devices.orm import AiHornConfig
from AiVision.alarms.devices.runtime_manager import HornRuntimeManager
from AiVision.alarms.devices.service import HornService, HornInUseError
from AiVision.cameras.orm import AiCameraConfig
from AiVision.features.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera


@pytest.fixture
def backend(tmp_path, monkeypatch):
    import AiVision.core.db as db_module
    import AiVision.alarms.devices.service as service_module

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'horn.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    tables = [AiHornConfig.__table__, AiCameraConfig.__table__, LogisticsChannel.__table__,
              LogisticsChannelCamera.__table__, *(spec.orm_class.__table__ for spec in all_specs().values())]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db_module, "get_session", factory)
    monkeypatch.setattr(service_module, "get_session", factory)
    notifications = []

    def sync(horn_id):
        # 独立连接此时必须看得到提交后的数据。
        with factory() as session:
            row = session.get(AiHornConfig, horn_id)
            notifications.append((horn_id, row.enable if row else None))

    manager = HornRuntimeManager()
    monkeypatch.setattr(manager, "sync", sync)
    service = HornService(manager)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    app.dependency_overrides[get_horn_service] = lambda: service
    app.dependency_overrides[get_horn_runtime_manager] = lambda: manager
    with TestClient(app) as client:
        yield SimpleNamespace(service=service, manager=manager, client=client, app=app,
                              factory=factory, notifications=notifications)
    manager.stop()
    engine.dispose()


def payload(**changes):
    return dict({"name": "现场喇叭", "url": "http://speaker.local", "username": "operator",
                 "password": "test-only-device-secret", "enable": False}, **changes)


def test_crud_contract_password_and_committed_notifications(backend):
    client = backend.client
    created = client.post("/api/horns", json=payload())
    assert created.status_code == 201
    data = created.json()
    horn_id = data["id"]
    assert data["password_set"] is True and "password" not in data
    assert data["runtime"]["state"] == "disabled"
    assert backend.notifications == [(horn_id, False)]
    for endpoint in ["/api/horns", f"/api/horns/{horn_id}", f"/api/horns/{horn_id}/status"]:
        response = client.get(endpoint)
        assert response.status_code == 200
        assert payload()["password"] not in response.text
    for empty_password in ["", None]:
        updated = client.patch(f"/api/horns/{horn_id}", json={"password": empty_password, "enable": True})
        assert updated.status_code == 200
        assert updated.json()["runtime"]["state"] == "not_started"
        with backend.factory() as session:
            assert session.get(AiHornConfig, horn_id).password == payload()["password"]
    assert client.patch(f"/api/horns/{horn_id}", json={"password": "replacement"}).status_code == 200
    with backend.factory() as session:
        assert session.get(AiHornConfig, horn_id).password == "replacement"
    assert client.delete(f"/api/horns/{horn_id}").status_code == 204
    assert backend.notifications[-1] == (horn_id, None)
    assert client.get(f"/api/horns/{horn_id}").status_code == 404
    assert client.patch(f"/api/horns/{horn_id}", json={"enable": False}).status_code == 404
    assert client.delete(f"/api/horns/{horn_id}").status_code == 404


@pytest.mark.parametrize("method,path", [("get", ""), ("post", ""), ("get", "/1"),
    ("patch", "/1"), ("delete", "/1"), ("get", "/1/status"), ("post", "/test-connection")])
@pytest.mark.parametrize("role,status_code", [(None, 401), ("user", 403)])
def test_every_horn_api_requires_admin(backend, method, path, role, status_code):
    def user():
        if role is None:
            raise HTTPException(401, "login required")
        return {"role": role}
    backend.app.dependency_overrides[get_current_user] = user
    response = backend.client.request(method, "/api/horns" + path, json=payload())
    assert response.status_code == status_code
    assert backend.service.list_horns() == []


@pytest.mark.parametrize("changes", [{"password": ""}, {"password": None}, {"password": "secret" * 100},
    {"url": "http://operator:test-only-device-secret@speaker.local"}, {"url": "file:///tmp/device"},
    {"url": "http://speaker.local/?password=test-only-device-secret"}, {"name": "  "}])
def test_validation_never_echoes_credentials(backend, changes):
    response = backend.client.post("/api/horns", json=payload(**changes))
    assert response.status_code == 422
    assert "test-only-device-secret" not in response.text
    assert "secretsecret" not in response.text
    assert backend.notifications == []


def test_new_device_requires_explicit_password_in_api_and_orm(backend):
    values = payload()
    del values["password"]
    assert backend.client.post("/api/horns", json=values).status_code == 422
    with backend.factory() as session:
        session.add(AiHornConfig(name="missing", url="http://speaker.local"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_conflict_does_not_leak_sql_parameters(backend, caplog):
    assert backend.client.post("/api/horns", json=payload()).status_code == 201
    response = backend.client.post("/api/horns", json=payload())
    assert response.status_code == 409
    assert payload()["password"] not in response.text + caplog.text
    assert len(backend.notifications) == 1


def test_legacy_url_credentials_are_not_returned(backend):
    with backend.factory.begin() as session:
        session.add(AiHornConfig(name="legacy", url="http://user:legacy-secret@speaker.local/?token=legacy-token",
                                 password="legacy-secret", enable=False))
    response = backend.client.get("/api/horns")
    assert response.status_code == 200
    assert "legacy-secret" not in response.text and "legacy-token" not in response.text
    assert response.json()[0]["url"] == "http://speaker.local/"


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_commit_failure_never_changes_runtime(backend, monkeypatch, operation, caplog):
    row = backend.service.create_horn(payload())
    backend.notifications.clear()

    def fail_commit(_session):
        raise OperationalError("test", {"password": payload()["password"]}, RuntimeError("failed"))

    monkeypatch.setattr(backend.factory.class_, "commit", fail_commit)
    if operation == "create":
        response = backend.client.post("/api/horns", json=payload(name="new"))
    elif operation == "update":
        response = backend.client.patch(f"/api/horns/{row['id']}", json={"enable": True})
    else:
        response = backend.client.delete(f"/api/horns/{row['id']}")
    assert response.status_code == 503
    assert backend.notifications == []
    assert payload()["password"] not in response.text + caplog.text
    with backend.factory() as session:
        assert session.get(AiHornConfig, row["id"]).enable is False
        assert session.query(AiHornConfig).count() == 1


@pytest.mark.parametrize("feature_name", [name for name, spec in all_specs().items() if "alarm" in spec.config_schema.model_fields])
def test_delete_protects_every_feature_even_disabled(backend, feature_name):
    horn = backend.service.create_horn(payload())
    model = all_specs()[feature_name].orm_class
    with backend.factory.begin() as session:
        camera = AiCameraConfig(name="camera", shm_name="camera", url="rtsp://test.local")
        session.add(camera)
        session.flush()
        session.add(model(camera_id=camera.id, horn_id=horn["id"], horn_enable=False, enable=False))
    response = backend.client.delete(f"/api/horns/{horn['id']}")
    assert response.status_code == 409
    assert backend.service.get_horn(horn["id"]) is not None
    assert len(backend.notifications) == 1
    with backend.factory.begin() as session:
        session.query(model).update({model.horn_id: None})
    assert backend.service.delete_horn(horn["id"]) is True


def test_delete_protects_disabled_logistics_channel(backend):
    horn = backend.service.create_horn(payload())
    with backend.factory.begin() as session:
        session.add(LogisticsChannel(name="channel", feature_name="logistics", enabled=False,
                                     horn_enable=False, horn_id=horn["id"], department="general_electric"))
    assert backend.client.delete(f"/api/horns/{horn['id']}").status_code == 409
    with pytest.raises(HornInUseError):
        backend.service.delete_horn(horn["id"])


def test_connection_is_silent_transient_and_can_reuse_saved_password(backend, monkeypatch):
    from AiVision.alarms.devices import horn as horn_module
    calls, probes = [], []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {"access_key": "key", "access_id": "id"})

    monkeypatch.setattr(horn_module.requests, "post", post)
    real_factory = backend.manager._factory

    def factory(*args, **kwargs):
        instance = real_factory(*args, **kwargs)
        probes.append(instance)
        return instance

    monkeypatch.setattr(backend.manager, "_factory", factory)
    horn = backend.service.create_horn(payload())
    backend.notifications.clear()
    for body in [{"url": "http://new.local", "password": "temporary"},
                 {"horn_id": horn["id"], "password": ""},
                 {"horn_id": horn["id"], "url": "http://edited.local", "password": "unsaved"}]:
        response = backend.client.post("/api/horns/test-connection", json=body)
        assert response.status_code == 200 and response.json()["success"] is True
        assert "password" not in response.text and "access_key" not in response.text
    assert len(calls) == 6
    assert all(url.endswith(("login", "online")) for url, _ in calls)
    assert calls[2][1]["json"]["password"] == payload()["password"]
    assert all(probe._heart_thread is None and probe._stop_event.is_set() for probe in probes)
    assert backend.notifications == [] and len(backend.service.list_horns()) == 1
    assert backend.service.runtime_configs(horn["id"])[0]["password"] == payload()["password"]
    assert backend.service.get_horn(horn["id"])["url"] == payload()["url"]


def test_failed_probe_sanitizes_network_error(backend, monkeypatch, caplog):
    from AiVision.alarms.devices import horn as horn_module

    def fail(*_args, **_kwargs):
        raise RuntimeError("temporary-password access-key device-body")

    monkeypatch.setattr(horn_module.requests, "post", fail)
    response = backend.client.post("/api/horns/test-connection", json={
        "url": "http://new.local", "password": "temporary-password"})
    assert response.status_code == 200 and response.json()["success"] is False
    assert response.json()["runtime"]["state"] == "failed"
    assert "temporary-password" not in response.text + caplog.text
    assert backend.service.list_horns() == []


def test_production_app_registers_horn_router():
    from AiVision.api.app import create_app
    assert "/api/horns/test-connection" in create_app().openapi()["paths"]


def test_api_crud_hot_syncs_real_runtime_after_commit(backend, monkeypatch):
    from AiVision.alarms.devices import horn as horn_module
    monkeypatch.setattr(horn_module.requests, "post", lambda *_args, **_kwargs:
                        SimpleNamespace(status_code=200, json=lambda: {"access_key": "key", "access_id": "id"}))
    manager = HornRuntimeManager(backend.service.runtime_configs)
    backend.service._runtime_manager = manager
    backend.app.dependency_overrides[get_horn_runtime_manager] = lambda: manager
    manager.start()
    instances = []
    try:
        response = backend.client.post("/api/horns", json=payload(enable=True))
        assert response.status_code == 201
        horn_id = response.json()["id"]
        first = manager._entries[horn_id][1]
        instances.append(first)
        assert first._heart_thread.is_alive()
        assert backend.client.patch(f"/api/horns/{horn_id}", json={
            "url": "http://changed.local", "username": "new-user", "password": "new-password"
        }).status_code == 200
        second = manager._entries[horn_id][1]
        instances.append(second)
        assert first._stop_event.is_set()
        assert second.url == "http://changed.local/" and second.password == "new-password"
        assert second.username == "new-user"
        assert backend.client.patch(f"/api/horns/{horn_id}", json={"enable": False}).status_code == 200
        assert second._stop_event.is_set() and horn_id not in manager._entries
        assert backend.client.patch(f"/api/horns/{horn_id}", json={"enable": True}).status_code == 200
        third = manager._entries[horn_id][1]
        instances.append(third)
        assert third is not second
        assert backend.client.delete(f"/api/horns/{horn_id}").status_code == 204
        assert third._stop_event.is_set() and horn_id not in manager._entries
    finally:
        manager.stop()
        for instance in instances:
            instance.stop_heartbeat()
    assert all(not instance._heart_thread.is_alive() for instance in instances)
