from __future__ import annotations

from sqlalchemy import inspect

import pytest

from auth.user_store import (
    UserConflictError,
    UserNotFoundError,
    UserStore,
    UserValidationError,
)


def _store(auth_database):
    store = UserStore(auth_database)
    store.create_user(
        employee_id="10001",
        name="管理员",
        role="admin",
        departments=["all"],
        password_hash="hash-admin",
    )
    store.create_user(
        employee_id="10002",
        name="通用电气用户",
        role="viewer",
        departments=["general_electric"],
        password_hash="hash-viewer",
    )
    return store


def test_initializes_and_reads_users_from_database(auth_database):
    store = _store(auth_database)

    assert [item["employee_id"] for item in store.list_users()] == [
        "10001",
        "10002",
    ]
    assert store.get_user_record("10001")["password_hash"] == "hash-admin"
    assert store.get_user_record("10002")["password_hash"] == "hash-viewer"


def test_create_update_reset_and_delete_user(auth_database):
    store = _store(auth_database)

    created = store.create_user(
        employee_id="20001",
        name="电子电工用户",
        role="viewer",
        departments=["electronics_electrician"],
        password_hash="hash-new",
    )
    assert created == {
        "employee_id": "20001",
        "name": "电子电工用户",
        "role": "viewer",
        "departments": ["electronics_electrician"],
        "enabled": True,
        "auth_version": 1,
    }

    updated = store.update_user(
        "20001",
        actor_employee_id="10001",
        name="新增管理员",
        role="admin",
        departments=None,
        enabled=True,
    )
    assert updated["role"] == "admin"
    assert updated["departments"] == ["all"]

    reset = store.update_password_hash("20001", "hash-reset")
    assert reset["auth_version"] == 2
    assert store.get_user_record("20001")["password_hash"] == "hash-reset"

    store.delete_user("20001", actor_employee_id="10001")
    with pytest.raises(UserNotFoundError):
        store.get_user_record("20001")


def test_accepts_haoda_company_viewer_department(auth_database):
    store = _store(auth_database)

    created = store.create_user(
        employee_id="20002",
        name="皓达公司用户",
        role="viewer",
        departments=["haoda_company"],
        password_hash="hash-haoda",
    )

    assert created["departments"] == ["haoda_company"]


def test_accepts_precious_metal_recycling_department(auth_database):
    store = _store(auth_database)

    created = store.create_user(
        employee_id="20003",
        name="伟达公司用户",
        role="viewer",
        departments=["precious_metal_recycling"],
        password_hash="hash-weida",
    )

    assert created["departments"] == ["precious_metal_recycling"]


def test_creates_and_updates_viewer_with_multiple_departments(auth_database):
    store = _store(auth_database)

    created = store.create_user(
        employee_id="20004",
        name="跨事业部负责人",
        role="viewer",
        departments=[
            "electronics_electrician",
            "electrical_components",
            "electronics_electrician",
        ],
        password_hash="hash-multi",
    )

    assert created["departments"] == [
        "electronics_electrician",
        "electrical_components",
    ]

    updated = store.update_user(
        "20004",
        actor_employee_id="10001",
        name="跨公司负责人",
        role="viewer",
        departments=["precious_metal_recycling", "haoda_company"],
        enabled=True,
    )

    assert updated["departments"] == [
        "precious_metal_recycling",
        "haoda_company",
    ]


def test_user_schema_has_only_formal_departments_field(auth_database):
    _store(auth_database)
    with auth_database() as session:
        columns = {
            row["name"] for row in inspect(session.bind).get_columns("auth_users")
        }
    assert "departments" in columns
    assert "department" not in columns


def test_rejects_invalid_or_duplicate_users(auth_database):
    store = _store(auth_database)

    with pytest.raises(UserConflictError, match="工号"):
        store.create_user(
            employee_id="10001",
            name="其他姓名",
            role="viewer",
            departments=["general_electric"],
            password_hash="hash",
        )
    with pytest.raises(UserConflictError, match="姓名"):
        store.create_user(
            employee_id="30001",
            name="管理员",
            role="viewer",
            departments=["general_electric"],
            password_hash="hash",
        )
    with pytest.raises(UserValidationError, match="事业部"):
        store.create_user(
            employee_id="30002",
            name="错误事业部",
            role="viewer",
            departments=["unknown"],
            password_hash="hash",
        )
    with pytest.raises(UserValidationError, match="至少选择一个"):
        store.create_user(
            employee_id="30003",
            name="空事业部",
            role="viewer",
            departments=[],
            password_hash="hash",
        )


def test_protects_current_user_and_last_enabled_admin(auth_database):
    store = _store(auth_database)

    with pytest.raises(UserConflictError, match="当前登录"):
        store.update_user(
            "10001",
            actor_employee_id="10001",
            name="管理员",
            role="admin",
            departments=None,
            enabled=False,
        )
    with pytest.raises(UserConflictError, match="当前登录"):
        store.delete_user("10001", actor_employee_id="10001")

    with pytest.raises(UserConflictError, match="最后一个"):
        store.update_user(
            "10001",
            actor_employee_id="another-admin",
            name="管理员",
            role="viewer",
            departments=["general_electric"],
            enabled=True,
        )
    with pytest.raises(UserConflictError, match="最后一个"):
        store.delete_user("10001", actor_employee_id="another-admin")


def test_allows_admin_change_when_another_enabled_admin_exists(auth_database):
    store = _store(auth_database)
    store.create_user(
        employee_id="10003",
        name="第二管理员",
        role="admin",
        departments=None,
        password_hash="hash",
    )

    updated = store.update_user(
        "10001",
        actor_employee_id="10003",
        name="前管理员",
        role="viewer",
        departments=["research_institute"],
        enabled=True,
    )

    assert updated["role"] == "viewer"
    assert updated["departments"] == ["research_institute"]


@pytest.mark.parametrize(
    "department",
    [
        "研究院",
        "福达新材院",
        "通用电气",
        "电子电工",
        "伟达公司",
        "皓达公司",
        "ge",
        "general-electric",
        "general electric",
        "electronics-electrician",
        "weida",
        "weida_company",
        "haoda",
        "all",
    ],
)
def test_rejects_department_aliases_on_create_and_update(auth_database, department):
    store = _store(auth_database)
    with pytest.raises(UserValidationError, match="有效事业部"):
        store.create_user(
            employee_id="invalid",
            name="非法事业部",
            role="viewer",
            departments=[department],
            password_hash="hash",
        )
    with pytest.raises(UserValidationError, match="有效事业部"):
        store.update_user(
            "10002",
            actor_employee_id="10001",
            name="普通用户",
            role="viewer",
            departments=[department],
            enabled=True,
        )
    assert store.get_user_record("10002")["departments"] == ["general_electric"]
