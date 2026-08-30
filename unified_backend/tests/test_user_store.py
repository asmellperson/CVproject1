from __future__ import annotations

import json
import sqlite3

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
        "departments": ["electronics_electrician"],
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
    assert updated["departments"] == ["all"]

    reset = store.update_password_hash("20001", "hash-reset")
    assert reset["auth_version"] == 2
    assert store.get_user_record("20001")["password_hash"] == "hash-reset"

    store.delete_user("20001", actor_employee_id="10001")
    with pytest.raises(UserNotFoundError):
        store.get_user_record("20001")


def test_accepts_haoda_company_viewer_department(tmp_path):
    store, _legacy_path = _store(tmp_path)

    created = store.create_user(
        employee_id="20002",
        name="皓达公司用户",
        role="viewer",
        department="皓达公司",
        password_hash="hash-haoda",
    )

    assert created["department"] == "haoda_company"


def test_accepts_weida_company_as_legacy_department_alias(tmp_path):
    store, _legacy_path = _store(tmp_path)

    created = store.create_user(
        employee_id="20003",
        name="伟达公司用户",
        role="viewer",
        department="伟达公司",
        password_hash="hash-weida",
    )

    assert created["department"] == "precious_metal_recycling"


def test_creates_and_updates_viewer_with_multiple_departments(tmp_path):
    store, _legacy_path = _store(tmp_path)

    created = store.create_user(
        employee_id="20004",
        name="跨事业部负责人",
        role="viewer",
        department=None,
        departments=[
            "electronics_electrician",
            "electrical_components",
            "electronics_electrician",
        ],
        password_hash="hash-multi",
    )

    assert created["department"] == "electronics_electrician"
    assert created["departments"] == [
        "electronics_electrician",
        "electrical_components",
    ]

    updated = store.update_user(
        "20004",
        actor_employee_id="10001",
        name="跨公司负责人",
        role="viewer",
        department=None,
        departments=["伟达公司", "皓达公司"],
        enabled=True,
    )

    assert updated["department"] == "precious_metal_recycling"
    assert updated["departments"] == [
        "precious_metal_recycling",
        "haoda_company",
    ]


def test_backfills_departments_when_opening_legacy_sqlite_database(tmp_path):
    database_path = tmp_path / "runtime" / "auth_users.db"
    database_path.parent.mkdir(parents=True)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE auth_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO auth_metadata(key, value) VALUES ('legacy_json_imported', '1');
            CREATE TABLE auth_users (
                employee_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL,
                department TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                password_hash TEXT,
                auth_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO auth_users(
                employee_id, name, role, department, enabled, auth_version
            ) VALUES ('legacy-viewer', '旧账号', 'viewer', 'general_electric', 1, 1);
            """
        )

    store = UserStore(
        database_path=database_path,
        legacy_json_path=tmp_path / "missing.json",
    )

    assert store.list_users()[0]["departments"] == ["general_electric"]
    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(auth_users)")
        }
    assert "departments" in columns


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
    with pytest.raises(UserValidationError, match="至少选择一个"):
        store.create_user(
            employee_id="30003",
            name="空事业部",
            role="viewer",
            department=None,
            departments=[],
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
