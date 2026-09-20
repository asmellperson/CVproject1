"""显式启用的真实 MySQL 并发验证，仅操作自动创建的临时库。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from AiVision.core.settings import settings
from AiVision.core.schema import assert_table_matches
from auth.access_audit import AccessAuditStore
from auth.orm import AccessViewer, AuthUser
from auth.user_store import UserConflictError, UserStore


def test_mysql_schema_and_concurrent_writes():
    if os.getenv("AUTH_TEST_MYSQL") != "1":
        pytest.skip("设置 AUTH_TEST_MYSQL=1 后，在配置的 MySQL 服务创建隔离测试库")
    name = "fuda_auth_test_" + uuid4().hex
    url = make_url(settings.db.sqlalchemy_url)
    server = create_engine(url.set(database=None), hide_parameters=True)
    engine = create_engine(url.set(database=name), hide_parameters=True)
    created = False
    try:
        with server.begin() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
                )
            )
            created = True
        for model in (AuthUser, AccessViewer):
            model.__table__.create(engine)
        with engine.connect() as connection:
            for model in (AuthUser, AccessViewer):
                assert_table_matches(connection, model.__table__)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        users = UserStore(factory)
        audit = AccessAuditStore(factory)
        for key in ("admin1", "admin2"):
            users.create_user(
                employee_id=key,
                name=key,
                role="admin",
                departments=["all"],
                password_hash="test-only",
            )
        barrier = Barrier(2)

        def demote(key):
            barrier.wait(timeout=10)
            try:
                users.update_user(
                    key,
                    actor_employee_id=key,
                    name=key,
                    role="viewer",
                    enabled=True,
                    departments=["general_electric"],
                )
                return "updated"
            except UserConflictError:
                return "protected"

        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(demote, ("admin1", "admin2"))) == [
                "protected",
                "updated",
            ]
        accounts = [
            users.create_user(
                employee_id=f"viewer{i}",
                name=f"viewer{i}",
                role="viewer",
                departments=["general_electric"],
                password_hash="test-only",
            )
            for i in range(12)
        ]
        with ThreadPoolExecutor(12) as pool:
            list(pool.map(audit.record_visit, accounts))
        assert len(audit.list_recent()) == 12
        account = users.get_user_record("admin1")
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda _: audit.record_visit(account), range(24)))
        assert (
            next(row for row in audit.list_recent() if row["employee_id"] == "admin1")[
                "visit_count"
            ]
            == 24
        )
        with ThreadPoolExecutor(4) as pool:
            list(
                pool.map(
                    lambda _: users.update_password_hash("admin1", "test-only-new"),
                    range(8),
                )
            )
        assert users.get_user_record("admin1")["auth_version"] == 9
    finally:
        engine.dispose()
        if created:
            with server.begin() as connection:
                connection.execute(text(f"DROP DATABASE `{name}`"))
        server.dispose()
