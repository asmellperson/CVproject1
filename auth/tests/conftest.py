"""账号与审计测试使用隔离的 SQLAlchemy 数据库，不访问业务库。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth import api, auth
from auth.access_audit import AccessAuditStore
from auth.orm import AccessViewer, AuthUser
from auth.user_store import UserStore


@pytest.fixture
def auth_database(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth-contract.sqlite'}")
    AuthUser.__table__.create(engine)
    AccessViewer.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(auth, "_user_store", UserStore(factory))
    monkeypatch.setattr(api, "access_audit_store", AccessAuditStore(factory))
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-with-at-least-32-characters")
    monkeypatch.setenv("PLATFORM_OWNER_EMPLOYEE_ID", "10001")
    yield factory
    engine.dispose()


@pytest.fixture
def client(auth_database):
    from AiVision.api.app import create_app

    for employee_id, role in (
        ("10001", "admin"),
        ("10002", "viewer"),
        ("10003", "admin"),
    ):
        auth.create_auth_user(
            employee_id=employee_id,
            name=f"用户-{employee_id}",
            role=role,
            departments=["all"] if role == "admin" else ["general_electric"],
            password="test-password",
        )
    with TestClient(create_app()) as http:
        yield http
