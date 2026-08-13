"""SQLite-backed user storage with one-time legacy JSON migration."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any


ALLOWED_ROLES = {"admin", "viewer"}
ALLOWED_VIEWER_DEPARTMENTS = {
    "general_electric",
    "research_institute",
    "electronics_electrician",
    "electrical_components",
    "precious_metal_recycling",
}
DEPARTMENT_ALIASES = {
    "ge": "general_electric",
    "general": "general_electric",
    "通用电气": "general_electric",
    "研究院": "research_institute",
    "人工智能研究院": "research_institute",
    "福达新材院": "research_institute",
    "电子电工": "electronics_electrician",
    "电气部件": "electrical_components",
    "贵金属回收": "precious_metal_recycling",
}


class UserStoreError(RuntimeError):
    """Base error for user persistence failures."""


class UserValidationError(UserStoreError):
    """A user payload is invalid."""


class UserConflictError(UserStoreError):
    """A mutation violates uniqueness or administrator safety constraints."""


class UserNotFoundError(UserStoreError):
    """The requested user does not exist."""


def default_database_path() -> Path:
    raw = os.getenv("AUTH_USERS_DB")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "runtime" / "auth" / "auth_users.db"


def default_legacy_json_path() -> Path:
    raw = os.getenv("AUTH_USERS_FILE")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / "auth_users.json"


def _normalize_required(value: object, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise UserValidationError(f"{label}不能为空")
    return normalized


def _normalize_role_department(
    role: object,
    department: object,
) -> tuple[str, str]:
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in ALLOWED_ROLES:
        raise UserValidationError("角色必须是 admin 或 viewer")
    if normalized_role == "admin":
        return normalized_role, "all"

    normalized_department = str(department or "").strip()
    normalized_department = DEPARTMENT_ALIASES.get(
        normalized_department,
        normalized_department,
    )
    if normalized_department not in ALLOWED_VIEWER_DEPARTMENTS:
        raise UserValidationError("普通用户必须选择有效事业部")
    return normalized_role, normalized_department


def _public_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "employee_id": row["employee_id"],
        "name": row["name"],
        "role": row["role"],
        "department": row["department"],
        "enabled": bool(row["enabled"]),
        "auth_version": int(row["auth_version"]),
    }


def _user_record(row: sqlite3.Row) -> dict[str, Any]:
    item = _public_user(row)
    item["password_hash"] = row["password_hash"]
    return item


class UserStore:
    def __init__(
        self,
        *,
        database_path: str | Path | None = None,
        legacy_json_path: str | Path | None = None,
    ):
        self.database_path = Path(database_path or default_database_path())
        self.legacy_json_path = Path(legacy_json_path or default_legacy_json_path())
        self._initialize_lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_users (
                        employee_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
                        department TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        password_hash TEXT,
                        auth_version INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                migrated = connection.execute(
                    "SELECT value FROM auth_metadata WHERE key = ?",
                    ("legacy_json_imported",),
                ).fetchone()
                if migrated is None:
                    self._migrate_legacy_users(connection)
                    connection.execute(
                        "INSERT INTO auth_metadata(key, value) VALUES (?, ?)",
                        ("legacy_json_imported", "1"),
                    )
                connection.commit()
                self._initialized = True
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _migrate_legacy_users(self, connection: sqlite3.Connection) -> None:
        try:
            payload = json.loads(self.legacy_json_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise UserStoreError(
                f"首次迁移找不到用户文件: {self.legacy_json_path}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise UserStoreError(
                f"首次迁移用户文件格式无效: {self.legacy_json_path}"
            ) from exc
        if not isinstance(payload, list) or not payload:
            raise UserStoreError("首次迁移用户文件必须是非空数组")

        employee_ids: set[str] = set()
        names: set[str] = set()
        normalized_users: list[tuple[Any, ...]] = []
        for raw_user in payload:
            if not isinstance(raw_user, dict):
                raise UserStoreError("首次迁移用户记录格式无效")
            employee_id = _normalize_required(raw_user.get("employee_id"), "工号")
            name = _normalize_required(raw_user.get("name"), "姓名")
            try:
                role, department = _normalize_role_department(
                    raw_user.get("role", "viewer"),
                    raw_user.get("department"),
                )
            except UserValidationError as exc:
                raise UserStoreError(f"首次迁移用户 {employee_id} 无效: {exc}") from exc
            if employee_id in employee_ids:
                raise UserStoreError(f"首次迁移存在重复工号: {employee_id}")
            if name in names:
                raise UserStoreError(f"首次迁移存在重复姓名: {name}")
            employee_ids.add(employee_id)
            names.add(name)
            normalized_users.append(
                (
                    employee_id,
                    name,
                    role,
                    department,
                    int(bool(raw_user.get("enabled", False))),
                    raw_user.get("password_hash") or None,
                    max(1, int(raw_user.get("auth_version", 1) or 1)),
                )
            )

        connection.executemany(
            """
            INSERT INTO auth_users(
                employee_id, name, role, department, enabled,
                password_hash, auth_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            normalized_users,
        )

    def list_users(self) -> list[dict[str, Any]]:
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT employee_id, name, role, department, enabled,
                       password_hash, auth_version
                FROM auth_users
                ORDER BY employee_id
                """
            ).fetchall()
        return [_public_user(row) for row in rows]

    def get_user_record(self, employee_id: str) -> dict[str, Any]:
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT employee_id, name, role, department, enabled,
                       password_hash, auth_version
                FROM auth_users
                WHERE employee_id = ?
                """,
                (str(employee_id).strip(),),
            ).fetchone()
        if row is None:
            raise UserNotFoundError("用户不存在")
        return _user_record(row)

    def find_enabled_user(self, identifier: str) -> dict[str, Any] | None:
        self.initialize()
        normalized = str(identifier).strip()
        if not normalized:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT employee_id, name, role, department, enabled,
                       password_hash, auth_version
                FROM auth_users
                WHERE enabled = 1 AND (employee_id = ? OR name = ?)
                LIMIT 1
                """,
                (normalized, normalized),
            ).fetchone()
        return _user_record(row) if row is not None else None

    def create_user(
        self,
        *,
        employee_id: str,
        name: str,
        role: str,
        department: str | None,
        password_hash: str,
    ) -> dict[str, Any]:
        self.initialize()
        normalized_employee_id = _normalize_required(employee_id, "工号")
        normalized_name = _normalize_required(name, "姓名")
        normalized_role, normalized_department = _normalize_role_department(
            role,
            department,
        )
        if not password_hash:
            raise UserValidationError("密码哈希不能为空")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM auth_users WHERE employee_id = ?",
                (normalized_employee_id,),
            ).fetchone():
                raise UserConflictError("工号已存在")
            if connection.execute(
                "SELECT 1 FROM auth_users WHERE name = ?",
                (normalized_name,),
            ).fetchone():
                raise UserConflictError("姓名已存在")
            connection.execute(
                """
                INSERT INTO auth_users(
                    employee_id, name, role, department, enabled,
                    password_hash, auth_version
                ) VALUES (?, ?, ?, ?, 1, ?, 1)
                """,
                (
                    normalized_employee_id,
                    normalized_name,
                    normalized_role,
                    normalized_department,
                    password_hash,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return _public_without_password(
            self.get_user_record(normalized_employee_id)
        )

    def update_user(
        self,
        employee_id: str,
        *,
        actor_employee_id: str,
        name: str,
        role: str,
        department: str | None,
        enabled: bool,
    ) -> dict[str, Any]:
        self.initialize()
        normalized_employee_id = _normalize_required(employee_id, "工号")
        normalized_actor = _normalize_required(actor_employee_id, "当前管理员工号")
        normalized_name = _normalize_required(name, "姓名")
        normalized_role, normalized_department = _normalize_role_department(
            role,
            department,
        )
        normalized_enabled = bool(enabled)

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM auth_users WHERE employee_id = ?",
                (normalized_employee_id,),
            ).fetchone()
            if current is None:
                raise UserNotFoundError("用户不存在")
            if normalized_employee_id == normalized_actor and not normalized_enabled:
                raise UserConflictError("不能禁用当前登录管理员")
            duplicate_name = connection.execute(
                """
                SELECT 1 FROM auth_users
                WHERE name = ? AND employee_id <> ?
                """,
                (normalized_name, normalized_employee_id),
            ).fetchone()
            if duplicate_name:
                raise UserConflictError("姓名已存在")
            removes_enabled_admin = (
                bool(current["enabled"])
                and current["role"] == "admin"
                and (not normalized_enabled or normalized_role != "admin")
            )
            if removes_enabled_admin and self._enabled_admin_count(connection) <= 1:
                raise UserConflictError("不能变更最后一个已启用管理员")
            connection.execute(
                """
                UPDATE auth_users
                SET name = ?, role = ?, department = ?, enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE employee_id = ?
                """,
                (
                    normalized_name,
                    normalized_role,
                    normalized_department,
                    int(normalized_enabled),
                    normalized_employee_id,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return _public_without_password(self.get_user_record(normalized_employee_id))

    def update_password_hash(
        self,
        employee_id: str,
        password_hash: str,
    ) -> dict[str, Any]:
        self.initialize()
        normalized_employee_id = _normalize_required(employee_id, "工号")
        if not password_hash:
            raise UserValidationError("密码哈希不能为空")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE auth_users
                SET password_hash = ?, auth_version = auth_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE employee_id = ?
                """,
                (password_hash, normalized_employee_id),
            )
            if cursor.rowcount == 0:
                raise UserNotFoundError("用户不存在")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return _public_without_password(self.get_user_record(normalized_employee_id))

    def delete_user(
        self,
        employee_id: str,
        *,
        actor_employee_id: str,
    ) -> None:
        self.initialize()
        normalized_employee_id = _normalize_required(employee_id, "工号")
        normalized_actor = _normalize_required(actor_employee_id, "当前管理员工号")
        if normalized_employee_id == normalized_actor:
            raise UserConflictError("不能删除当前登录管理员")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM auth_users WHERE employee_id = ?",
                (normalized_employee_id,),
            ).fetchone()
            if current is None:
                raise UserNotFoundError("用户不存在")
            if (
                bool(current["enabled"])
                and current["role"] == "admin"
                and self._enabled_admin_count(connection) <= 1
            ):
                raise UserConflictError("不能删除最后一个已启用管理员")
            connection.execute(
                "DELETE FROM auth_users WHERE employee_id = ?",
                (normalized_employee_id,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _enabled_admin_count(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM auth_users
            WHERE role = 'admin' AND enabled = 1
            """
        ).fetchone()
        return int(row["count"])


def _public_without_password(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key != "password_hash"
    }


__all__ = [
    "ALLOWED_ROLES",
    "ALLOWED_VIEWER_DEPARTMENTS",
    "UserConflictError",
    "UserNotFoundError",
    "UserStore",
    "UserStoreError",
    "UserValidationError",
    "default_database_path",
    "default_legacy_json_path",
]
