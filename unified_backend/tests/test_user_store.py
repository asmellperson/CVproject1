from __future__ import annotations

import json

import pytest

from auth.user_store import (
    UserConflictError,
    UserNotFoundError,
    UserStore,
    UserValidationError,
)


def _legacy_users():
    return [
        {
            "employee_id": "10001",
            "name": "管理员",
            "role": "admin",
            "department": "all",
            "enabled": True,
            "password_hash": "hash-admin",
        },
        {
            "employee_id": "10002",
            "name": "通用电气用户",
            "role": "viewer",
            "department": "general_electric",
            "enabled": True,
        },
    ]


def _store(tmp_path):
    legacy_path = tmp_path / "auth_users.json"
    legacy_path.write_text(
        json.dumps(_legacy_users(), ensure_ascii=False),
        encoding="utf-8",
    )
    return (
        UserStore(
            database_path=tmp_path / "runtime" / "auth_users.db",
            legacy_json_path=legacy_path,
        ),
        legacy_path,
    )


def test_migrates_legacy_json_once_and_then_reads_only_database(tmp_path):
    store, legacy_path = _store(tmp_path)

    assert [item["employee_id"] for item in store.list_users()] == [
        "10001",
        "10002",
    ]
    assert store.get_user_record("10001")["password_hash"] == "hash-admin"
    assert store.get_user_record("10002")["password_hash"] is None

    legacy_path.write_text(
        json.dumps(
            [
                {
                    "employee_id": "changed",
                    "name": "不应重新导入",
                    "role": "admin",
                    "department": "all",
                    "enabled": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert [item["employee_id"] for item in store.list_users()] == [
        "10001",
        "10002",
    ]


def test_create_update_reset_and_delete_user(tmp_path):
    store, _legacy_path = _store(tmp_path)

    created = store.create_user(
        employee_id="20001",
        name="电子电工用户",
        role="viewer",
        department="electronics_electrician",
        password_hash="hash-new",
    )
    assert created == {
        "employee_id": "20001",
        "name": "电子电工用户",
        "role": "viewer",
        "department": "electronics_electrician",
        "enabled": True,
        "auth_version": 1,
    }

    updated = store.update_user(
        "20001",
        actor_employee_id="10001",
        name="新增管理员",
        role="admin",
        department="general_electric",
        enabled=True,
    )
    assert updated["role"] == "admin"
    assert updated["department"] == "all"

    reset = store.update_password_hash("20001", "hash-reset")
    assert reset["auth_version"] == 2
    assert store.get_user_record("20001")["password_hash"] == "hash-reset"

    store.delete_user("20001", actor_employee_id="10001")
    with pytest.raises(UserNotFoundError):
        store.get_user_record("20001")


def test_rejects_invalid_or_duplicate_users(tmp_path):
    store, _legacy_path = _store(tmp_path)

    with pytest.raises(UserConflictError, match="工号"):
        store.create_user(
            employee_id="10001",
            name="其他姓名",
            role="viewer",
            department="general_electric",
            password_hash="hash",
        )
    with pytest.raises(UserConflictError, match="姓名"):
        store.create_user(
            employee_id="30001",
            name="管理员",
            role="viewer",
            department="general_electric",
            password_hash="hash",
        )
    with pytest.raises(UserValidationError, match="事业部"):
        store.create_user(
            employee_id="30002",
            name="错误事业部",
            role="viewer",
            department="unknown",
            password_hash="hash",
        )


def test_protects_current_user_and_last_enabled_admin(tmp_path):
    store, _legacy_path = _store(tmp_path)

    with pytest.raises(UserConflictError, match="当前登录"):
        store.update_user(
            "10001",
            actor_employee_id="10001",
            name="管理员",
            role="admin",
            department="all",
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
            department="general_electric",
            enabled=True,
        )
    with pytest.raises(UserConflictError, match="最后一个"):
        store.delete_user("10001", actor_employee_id="another-admin")


def test_allows_admin_change_when_another_enabled_admin_exists(tmp_path):
    store, _legacy_path = _store(tmp_path)
    store.create_user(
        employee_id="10003",
        name="第二管理员",
        role="admin",
        department=None,
        password_hash="hash",
    )

    updated = store.update_user(
        "10001",
        actor_employee_id="10003",
        name="前管理员",
        role="viewer",
        department="research_institute",
        enabled=True,
    )

    assert updated["role"] == "viewer"
    assert updated["department"] == "research_institute"


@pytest.mark.parametrize("department", ["研究院", "人工智能研究院", "福达新材院"])
def test_accepts_legacy_and_current_materials_institute_labels(tmp_path, department):
    store, _legacy_path = _store(tmp_path)

    created = store.create_user(
        employee_id=f"viewer-{department}",
        name="新材院用户",
        role="viewer",
        department=department,
        password_hash="hash",
    )

    assert created["department"] == "research_institute"
