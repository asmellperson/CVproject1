"""外部凭证的永久有效期、到期边界和管理员接口回归。"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

DEPARTMENTS = ["general_electric", "electronics_electrician", "electrical_components"]


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """仅使用内存数据库和临时存储，避免连接部署环境的 MySQL。"""
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test",
        "MYSQL_DB_PASSWORD": "test", "MYSQL_DB_NAME": "test",
        "DATA_PATH": str(tmp_path), "AUTO_CREATE_DB": "false",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def store(isolated_settings):
    """每项测试使用独立的凭证表，摘要和授权均经过实际持久化。"""
    from auth.external_store import ExternalClientStore
    from auth.orm import ExternalClient

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    ExternalClient.__table__.create(engine)
    yield ExternalClientStore(sessionmaker(engine))
    engine.dispose()


def payload(expires_at=None):
    """用三个明确事业部的围栏只读凭证覆盖实际接入场景。"""
    from auth.external_schema import ExternalClientCreate

    return ExternalClientCreate(
        name="围栏大屏", departments=DEPARTMENTS, scopes=["security_fence:read"], expires_at=expires_at,
    )


@pytest.mark.parametrize("expires_at", ["missing", "2000-01-01T00:00:00+08:00", "2099-01-01T00:00:00"])
def test_expiration_must_be_explicit_and_future_or_null(expires_at):
    """遗漏、已过期和无时区时间不能意外变成永久授权。"""
    from auth.external_schema import ExternalClientCreate

    data = {"name": "围栏大屏", "departments": DEPARTMENTS, "scopes": ["security_fence:read"]}
    if expires_at != "missing":
        data["expires_at"] = expires_at
    with pytest.raises(ValidationError):
        ExternalClientCreate.model_validate(data)


def test_permanent_credential_survives_time_and_metadata_roundtrip(store, monkeypatch):
    """永久密钥不随时间失效，查询仅返回授权元数据，数据库只保存摘要。"""
    from auth import external_store
    from auth.orm import ExternalClient

    issued = store.create(payload(), "test-admin")
    monkeypatch.setattr(external_store, "utc_now", lambda: datetime(2099, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None))
    info = store.authenticate(issued.api_key)
    assert info.expires_at is None
    assert info.departments == DEPARTMENTS
    assert info.scopes == ["security_fence:read"]
    assert store.list_clients() == [info]
    assert "api_key" not in info.model_dump()
    assert "key_digest" not in info.model_dump()
    with store._session_factory() as session:
        row = session.get(ExternalClient, issued.client.id)
        assert row.expires_at is None
        assert row.key_digest != issued.api_key
        assert len(row.key_digest) == 64


def test_expiring_credential_rejects_exact_expiration_boundary(store, monkeypatch):
    """有限有效期仍按 UTC 在到期瞬间失效。"""
    from auth import external_store
    from auth.external_store import ExternalCredentialError

    expiration = datetime.now(timezone(timedelta(hours=8))) + timedelta(days=1)
    issued = store.create(payload(expiration), "test-admin")
    utc_expiration = expiration.astimezone(timezone.utc)
    assert issued.client.expires_at == utc_expiration
    monkeypatch.setattr(external_store, "utc_now", lambda: utc_expiration.replace(tzinfo=None) - timedelta(microseconds=1))
    assert store.authenticate(issued.api_key).id == issued.client.id
    monkeypatch.setattr(external_store, "utc_now", lambda: utc_expiration.replace(tzinfo=None))
    with pytest.raises(ExternalCredentialError):
        store.authenticate(issued.api_key)


def test_permanent_credential_can_be_rotated_and_disabled(store):
    """永久凭证仍须立即响应密钥轮换和停用，重新启用后保持永久有效。"""
    from auth.external_store import ExternalCredentialError

    issued = store.create(payload(), "test-admin")
    rotated = store.rotate(issued.client.id)
    assert rotated.client.expires_at is None
    with pytest.raises(ExternalCredentialError):
        store.authenticate(issued.api_key)
    assert store.authenticate(rotated.api_key).expires_at is None
    assert store.set_enabled(issued.client.id, False).expires_at is None
    with pytest.raises(ExternalCredentialError):
        store.authenticate(rotated.api_key)
    store.set_enabled(issued.client.id, True)
    assert store.authenticate(rotated.api_key).expires_at is None


def test_update_between_expiring_and_permanent_preserves_authorization(store, monkeypatch):
    """调整有效期和事业部授权后，原密钥立即按最新记录校验。"""
    from auth import external_store
    from auth.external_schema import ExternalClientUpdate
    from auth.external_store import ExternalCredentialError

    expiration = datetime.now(timezone.utc) + timedelta(days=1)
    issued = store.create(payload(expiration), "test-admin")
    update = ExternalClientUpdate(**payload().model_dump(), enabled=True)
    update.departments = DEPARTMENTS[:1]
    updated = store.update(issued.client.id, update)
    assert updated.expires_at is None
    monkeypatch.setattr(external_store, "utc_now", lambda: expiration.replace(tzinfo=None) + timedelta(seconds=1))
    assert store.authenticate(issued.api_key).departments == DEPARTMENTS[:1]
    update.expires_at = expiration
    assert store.update(issued.client.id, update).expires_at == expiration
    with pytest.raises(ExternalCredentialError):
        store.authenticate(issued.api_key)


def test_admin_api_creates_and_updates_permanent_credential(store):
    """真实管理路由接受 null 并保留三个事业部及围栏只读权限。"""
    from auth.auth import get_current_user
    from auth.external import get_external_client_store
    from auth.external_api import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"employee_id": "test-admin", "role": "admin"}
    app.dependency_overrides[get_external_client_store] = lambda: store
    with TestClient(app) as client:
        response = client.post("/api/admin/external-clients", json=payload().model_dump(mode="json"))
        assert response.status_code == 201
        assert response.headers["cache-control"] == "no-store"
        issued = response.json()
        assert issued["client"]["expires_at"] is None
        assert issued["client"]["departments"] == DEPARTMENTS
        assert store.authenticate(issued["api_key"]).scopes == ["security_fence:read"]
        listed = client.get("/api/admin/external-clients").json()
        assert listed == [issued["client"]]
        update = {**payload().model_dump(mode="json"), "enabled": True}
        changed = client.put(f"/api/admin/external-clients/{issued['client']['id']}", json=update)
        assert changed.status_code == 200
        assert changed.json()["expires_at"] is None
        app.dependency_overrides[get_current_user] = lambda: {"employee_id": "test-viewer", "role": "viewer"}
        assert client.post("/api/admin/external-clients", json=update).status_code == 403
