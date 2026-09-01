# 文件说明：封装`user_store` 模块的 React 状态与副作用。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""SQLite-backed user storage."""
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
    "haoda_company",
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
    "weida": "precious_metal_recycling",
    "weida_company": "precious_metal_recycling",
    "weida-company": "precious_metal_recycling",
    "weida company": "precious_metal_recycling",
    "伟达": "precious_metal_recycling",
    "伟达公司": "precious_metal_recycling",
    "贵金属回收": "precious_metal_recycling",
    "皓达公司": "haoda_company",
    "皓达": "haoda_company",
}


# 功能：Base error for user persistence failures；输入与输出详见下方说明
# 参数：无。
# 返回：UserStoreError；返回新建的 `UserStoreError` 实例。
# 调用关系：
#   - 调用方：认证服务及用户管理接口捕获本符号及其子类
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class UserStoreError(RuntimeError):
    """Base error for user persistence failures."""


# 功能：A user payload is invalid；输入与输出详见下方说明
# 参数：无。
# 返回：UserValidationError；返回新建的 `UserValidationError` 实例。
# 调用关系：
#   - 调用方：`auth/user_store.py` 的 `_normalize_required` 实例化本符号；`auth/user_store.py` 的 `_normalize_role_departments`
#         实例化本符号；`auth/user_store.py` 的 `UserStore::create_user` 实例化本符号；`auth/user_store.py` 的 `UserStore::update_password_hash`
#         实例化本符号；另有 2 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class UserValidationError(UserStoreError):
    """A user payload is invalid."""


# 功能：A mutation violates uniqueness or administrator safety constraints；输入与输出详见下方说明
# 参数：无。
# 返回：UserConflictError；返回新建的 `UserConflictError` 实例。
# 调用关系：
#   - 调用方：`auth/user_store.py` 的 `UserStore::create_user` 实例化本符号；`auth/user_store.py` 的 `UserStore::update_user`
#         实例化本符号；`auth/user_store.py` 的 `UserStore::delete_user` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class UserConflictError(UserStoreError):
    """A mutation violates uniqueness or administrator safety constraints."""


# 功能：The requested user does not exist；输入与输出详见下方说明
# 参数：无。
# 返回：UserNotFoundError；返回新建的 `UserNotFoundError` 实例。
# 调用关系：
#   - 调用方：`auth/user_store.py` 的 `UserStore::get_user_record` 实例化本符号；`auth/user_store.py` 的 `UserStore::update_user`
#         实例化本符号；`auth/user_store.py` 的 `UserStore::update_password_hash` 实例化本符号；`auth/user_store.py` 的 `UserStore::delete_user`
#         实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class UserNotFoundError(UserStoreError):
    """The requested user does not exist."""


# 功能：实现 `default_database_path` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/user_store.py` 的 `UserStore::__init__` 调用本符号；`auth/auth.py` 的 `get_auth_users_database_path` 调用本符号
#   - 内部调用：`os.getenv`、`Path`、`Path(__file__).resolve`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def default_database_path() -> Path:
    raw = os.getenv("AUTH_USERS_DB")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "runtime" / "auth" / "auth_users.db"


# 功能：转换或规范化 `_normalize_required` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（object）：待转换、校验或写入的值
#   - `label`（str）：`label` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/user_store.py` 的 `UserStore::create_user` 调用本符号；`auth/user_store.py` 的 `UserStore::update_user`
#         调用本符号；`auth/user_store.py` 的 `UserStore::update_password_hash`
#         调用本符号；另有 1 处静态调用
#   - 内部调用：`str(value or '').strip`、`str`、`UserValidationError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _normalize_required(value: object, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise UserValidationError(f"{label}不能为空")
    return normalized


# 功能：转换或规范化 `_normalize_role_departments` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `role`（object）：`role` 对应的业务输入值
#   - `department`（object）：业务部门名称或标识
#   - `departments`（object）：`departments` 对应的业务输入值；默认值为 `None`
# 返回：tuple[str, list[str]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/user_store.py` 的 `UserStore::initialize` 调用本符号；`auth/user_store.py` 的 `UserStore::create_user` 调用本符号；
#         `auth/user_store.py` 的 `UserStore::update_user` 调用本符号
#   - 内部调用：`str(role or '').strip().lower`、`str(role or
#          '').strip`、`str`、`UserValidationError`、`isinstance`、`list`、`str(raw_department or
#          '').strip`、`DEPARTMENT_ALIASES.get`、`normalized_department.lower`、`normalized_departments.append`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _normalize_role_departments(
    role: object,
    department: object,
    departments: object = None,
) -> tuple[str, list[str]]:
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in ALLOWED_ROLES:
        raise UserValidationError("角色必须是 admin 或 viewer")
    if normalized_role == "admin":
        return normalized_role, ["all"]

    if departments is None:
        raw_departments = [department]
    elif isinstance(departments, (list, tuple)):
        raw_departments = list(departments)
    else:
        raise UserValidationError("事业部必须是数组")

    normalized_departments: list[str] = []
    for raw_department in raw_departments:
        normalized_department = str(raw_department or "").strip()
        normalized_department = DEPARTMENT_ALIASES.get(
            normalized_department,
            DEPARTMENT_ALIASES.get(
                normalized_department.lower(),
                normalized_department,
            ),
        )
        if normalized_department not in ALLOWED_VIEWER_DEPARTMENTS:
            raise UserValidationError("普通用户必须选择有效事业部")
        if normalized_department not in normalized_departments:
            normalized_departments.append(normalized_department)
    if not normalized_departments:
        raise UserValidationError("普通用户必须至少选择一个有效事业部")
    return normalized_role, normalized_departments


# 功能：实现 `_encode_departments` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `departments`（list[str]）：`departments` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/user_store.py` 的 `UserStore::initialize` 调用本符号；`auth/user_store.py` 的 `UserStore::create_user` 调用本符号；
#         `auth/user_store.py` 的 `UserStore::update_user` 调用本符号
#   - 内部调用：`json.dumps`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _encode_departments(departments: list[str]) -> str:
    return json.dumps(departments, ensure_ascii=False, separators=(",", ":"))


# 功能：实现 `_decode_departments` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（object）：待转换、校验或写入的值
#   - `fallback`（object）：`fallback` 对应的业务输入值
# 返回：list[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/user_store.py` 的 `_public_user` 调用本符号；`auth/user_store.py` 的 `UserStore::initialize` 调用本符号
#   - 内部调用：`isinstance`、`json.loads`、`str`、`str(fallback or '').strip`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _decode_departments(value: object, fallback: object) -> list[str]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list) and decoded:
        return [str(item) for item in decoded]
    normalized_fallback = str(fallback or "").strip()
    return [normalized_fallback] if normalized_fallback else []


# 功能：实现 `_public_user` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `row`（sqlite3.Row）：`row` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_decode_departments`、`bool`、`int`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _public_user(row: sqlite3.Row) -> dict[str, Any]:
    departments = _decode_departments(row["departments"], row["department"])
    return {
        "employee_id": row["employee_id"],
        "name": row["name"],
        "role": row["role"],
        "department": row["department"],
        "departments": departments,
        "enabled": bool(row["enabled"]),
        "auth_version": int(row["auth_version"]),
    }


# 功能：实现 `_user_record` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `row`（sqlite3.Row）：`row` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/user_store.py` 的 `UserStore::get_user_record` 调用本符号；`auth/user_store.py` 的 `UserStore::find_enabled_user` 调用本符号
#   - 内部调用：`_public_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _user_record(row: sqlite3.Row) -> dict[str, Any]:
    item = _public_user(row)
    item["password_hash"] = row["password_hash"]
    return item


# 功能：定义 `UserStore` 类，封装`user_store` 模块相关的状态、约束与操作
# 参数：
#   - `database_path`（str | Path | None）：`database_path` 对应的业务输入值；默认值为 `None`
# 返回：UserStore；返回新建的 `UserStore` 实例。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `get_user_store` 实例化本符号；`unified_backend/tests/test_user_store.py` 的 `_store`
#         实例化本符号；`unified_backend/tests/test_user_store.py` 的 `test_backfills_departments_when_opening_older_sqlite_database`
#         实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class UserStore:
    # 功能：初始化或配置 `__init__` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `database_path`（str | Path | None）：`database_path` 对应的业务输入值；默认值为 `None`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path`、`default_database_path`、`threading.Lock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(
        self,
        *,
        database_path: str | Path | None = None,
    ):
        self.database_path = Path(database_path or default_database_path())
        self._initialize_lock = threading.Lock()
        self._initialized = False

    # 功能：实现 `_connect` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：sqlite3.Connection；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`auth/user_store.py` 的 `UserStore::initialize` 调用本符号；`auth/user_store.py` 的 `UserStore::list_users`
    #         调用本符号；`auth/user_store.py` 的 `UserStore::get_user_record` 调用本符号；`auth/user_store.py` 的 `UserStore::find_enabled_user`
    #         调用本符号；另有 4 处静态调用
    #   - 内部调用：`sqlite3.connect`、`connection.execute`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    # 功能：初始化或配置 `initialize` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`auth/user_store.py` 的 `UserStore::list_users` 调用本符号；`auth/user_store.py` 的 `UserStore::get_user_record`
    #         调用本符号；`auth/user_store.py` 的 `UserStore::find_enabled_user` 调用本符号；`auth/user_store.py` 的 `UserStore::create_user`
    #         调用本符号；另有 3 处静态调用
    #   - 内部调用：`self.database_path.parent.mkdir`、`self._connect`、`connection.execute`、`str`、`connection.execute('PRAGMA
    #          table_info(auth_users)').fetchall`、`connection.execute('SELECT employee_id, role, department, departments FROM
    #          auth_users').fetchall`、`_normalize_role_departments`、`_decode_departments`、`_encode_departments`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
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
                    CREATE TABLE IF NOT EXISTS auth_users (
                        employee_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
                        department TEXT NOT NULL,
                        departments TEXT NOT NULL DEFAULT '[]',
                        enabled INTEGER NOT NULL DEFAULT 1,
                        password_hash TEXT,
                        auth_version INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                columns = {
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(auth_users)"
                    ).fetchall()
                }
                if "departments" not in columns:
                    connection.execute(
                        "ALTER TABLE auth_users "
                        "ADD COLUMN departments TEXT NOT NULL DEFAULT '[]'"
                    )
                for row in connection.execute(
                    "SELECT employee_id, role, department, departments "
                    "FROM auth_users"
                ).fetchall():
                    role, departments = _normalize_role_departments(
                        row["role"],
                        row["department"],
                        _decode_departments(
                            row["departments"],
                            row["department"],
                        ),
                    )
                    connection.execute(
                        "UPDATE auth_users "
                        "SET role = ?, department = ?, departments = ? "
                        "WHERE employee_id = ?",
                        (
                            role,
                            departments[0],
                            _encode_departments(departments),
                            row["employee_id"],
                        ),
                    )
                connection.commit()
                self._initialized = True
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    # 功能：读取或查询 `list_users` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`auth/auth.py` 的 `load_auth_users` 调用本符号；`auth/auth.py` 的 `list_auth_users`
    #         调用本符号；`unified_backend/tests/test_admin_users_api.py` 的 `test_admin_user_routes_cover_full_lifecycle`
    #         调用本符号；`unified_backend/tests/test_user_store.py` 的 `test_initializes_and_reads_users_from_database`
    #         调用本符号；另有 1 处静态调用
    #   - 内部调用：`self.initialize`、`closing`、`self._connect`、`connection.execute('\n                SELECT employee_id, name, role,
    #          department, departments, enabled,\n                       password_hash, auth_version\n                FROM
    #          auth_users\n                ORDER BY employee_id\n                ').fetchall`、`connection.execute`、`_public_user`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def list_users(self) -> list[dict[str, Any]]:
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT employee_id, name, role, department, departments, enabled,
                       password_hash, auth_version
                FROM auth_users
                ORDER BY employee_id
                """
            ).fetchall()
        return [_public_user(row) for row in rows]

    # 功能：读取或查询 `get_user_record` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`auth/user_store.py` 的 `UserStore::create_user` 调用本符号；`auth/user_store.py` 的 `UserStore::update_user`
    #         调用本符号；`auth/user_store.py` 的 `UserStore::update_password_hash` 调用本符号；`auth/auth.py` 的 `change_own_password` 调用本符号；另有 2
    #         处静态调用
    #   - 内部调用：`self.initialize`、`closing`、`self._connect`、`connection.execute('\n                SELECT employee_id, name, role,
    #          department, departments, enabled,\n                       password_hash, auth_version\n                FROM
    #          auth_users\n                WHERE employee_id = ?\n                ',
    #          (str(employee_id).strip(),)).fetchone`、`connection.execute`、`str(employee_id).strip`、`str`、`UserNotFoundError`、`_user_record`。
    # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
    def get_user_record(self, employee_id: str) -> dict[str, Any]:
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT employee_id, name, role, department, departments, enabled,
                       password_hash, auth_version
                FROM auth_users
                WHERE employee_id = ?
                """,
                (str(employee_id).strip(),),
            ).fetchone()
        if row is None:
            raise UserNotFoundError("用户不存在")
        return _user_record(row)

    # 功能：读取或查询 `find_enabled_user` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `identifier`（str）：`identifier` 对应的业务输入值
    # 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.initialize`、`str(identifier).strip`、`str`、`closing`、`self._connect`、`connection.execute('\n
    #          SELECT employee_id, name, role, department, departments, enabled,\n                       password_hash,
    #          auth_version\n                FROM auth_users\n                WHERE enabled = 1 AND (employee_id = ? OR name = ?)\n
    #          LIMIT 1\n                ', (normalized, normalized)).fetchone`、`connection.execute`、`_user_record`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def find_enabled_user(self, identifier: str) -> dict[str, Any] | None:
        self.initialize()
        normalized = str(identifier).strip()
        if not normalized:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT employee_id, name, role, department, departments, enabled,
                       password_hash, auth_version
                FROM auth_users
                WHERE enabled = 1 AND (employee_id = ? OR name = ?)
                LIMIT 1
                """,
                (normalized, normalized),
            ).fetchone()
        return _user_record(row) if row is not None else None

    # 功能：创建或构建 `create_user` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
    #   - `name`（str）：业务对象名称
    #   - `role`（str）：`role` 对应的业务输入值
    #   - `department`（str | None）：业务部门名称或标识
    #   - `password_hash`（str）：`password_hash` 对应的业务输入值
    #   - `departments`（list[str] | None）：`departments` 对应的业务输入值；默认值为 `None`
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`auth/auth.py` 的 `create_auth_user` 调用本符号；`unified_backend/tests/test_admin_users_api.py` 的
    #         `test_admin_user_routes_cover_full_lifecycle` 调用本符号；`unified_backend/tests/test_user_store.py` 的
    #         `test_create_update_reset_and_delete_user` 调用本符号；`unified_backend/tests/test_user_store.py` 的
    #         `test_accepts_haoda_company_viewer_department` 调用本符号；另有 5 处静态调用
    #   - 内部调用：`self.initialize`、`_normalize_required`、`_normalize_role_departments`、`UserValidationError`、`self._connect`、`connection.execute`、`connection.execute('SELECT
    #          1 FROM auth_users WHERE employee_id = ?',
    #          (normalized_employee_id,)).fetchone`、`UserConflictError`、`connection.execute('SELECT 1 FROM auth_users WHERE name =
    #          ?', (normalized_name,)).fetchone`、`_encode_departments` 等共 15 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
    def create_user(
        self,
        *,
        employee_id: str,
        name: str,
        role: str,
        department: str | None,
        password_hash: str,
        departments: list[str] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        normalized_employee_id = _normalize_required(employee_id, "工号")
        normalized_name = _normalize_required(name, "姓名")
        normalized_role, normalized_departments = _normalize_role_departments(
            role,
            department,
            departments,
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
                    employee_id, name, role, department, departments, enabled,
                    password_hash, auth_version
                ) VALUES (?, ?, ?, ?, ?, 1, ?, 1)
                """,
                (
                    normalized_employee_id,
                    normalized_name,
                    normalized_role,
                    normalized_departments[0],
                    _encode_departments(normalized_departments),
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

    # 功能：更新或保存 `update_user` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
    #   - `actor_employee_id`（str）：`actor_employee_id` 对应业务对象的唯一标识
    #   - `name`（str）：业务对象名称
    #   - `role`（str）：`role` 对应的业务输入值
    #   - `department`（str | None）：业务部门名称或标识
    #   - `enabled`（bool）：是否启用相应能力
    #   - `departments`（list[str] | None）：`departments` 对应的业务输入值；默认值为 `None`
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`auth/auth.py` 的 `update_auth_user` 调用本符号；`unified_backend/tests/test_admin_users_api.py` 的
    #         `test_admin_user_routes_cover_full_lifecycle` 调用本符号；`unified_backend/tests/test_user_store.py` 的
    #         `test_create_update_reset_and_delete_user` 调用本符号；`unified_backend/tests/test_user_store.py` 的
    #         `test_creates_and_updates_viewer_with_multiple_departments` 调用本符号；另有 2 处静态调用
    #   - 内部调用：`self.initialize`、`_normalize_required`、`_normalize_role_departments`、`bool`、`self._connect`、`connection.execute`、`connection.execute('SELECT
    #          * FROM auth_users WHERE employee_id = ?',
    #          (normalized_employee_id,)).fetchone`、`UserNotFoundError`、`UserConflictError`、`connection.execute('\n
    #          SELECT 1 FROM auth_users\n                WHERE name = ? AND employee_id <> ?\n                ', (normalized_name,
    #          normalized_employee_id)).fetchone` 等共 18 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
    def update_user(
        self,
        employee_id: str,
        *,
        actor_employee_id: str,
        name: str,
        role: str,
        department: str | None,
        enabled: bool,
        departments: list[str] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        normalized_employee_id = _normalize_required(employee_id, "工号")
        normalized_actor = _normalize_required(actor_employee_id, "当前管理员工号")
        normalized_name = _normalize_required(name, "姓名")
        normalized_role, normalized_departments = _normalize_role_departments(
            role,
            department,
            departments,
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
                SET name = ?, role = ?, department = ?, departments = ?, enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE employee_id = ?
                """,
                (
                    normalized_name,
                    normalized_role,
                    normalized_departments[0],
                    _encode_departments(normalized_departments),
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

    # 功能：更新或保存 `update_password_hash` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
    #   - `password_hash`（str）：`password_hash` 对应的业务输入值
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`auth/auth.py` 的 `change_own_password` 调用本符号；`auth/auth.py` 的 `reset_auth_user_password`
    #         调用本符号；`unified_backend/tests/test_user_store.py` 的 `test_create_update_reset_and_delete_user` 调用本符号
    #   - 内部调用：`self.initialize`、`_normalize_required`、`UserValidationError`、`self._connect`、`connection.execute`、`UserNotFoundError`、`connection.commit`、`connection.rollback`、`connection.close`、`_public_without_password`
    #          等共 11 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
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

    # 功能：删除或清理 `delete_user` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
    #   - `actor_employee_id`（str）：`actor_employee_id` 对应业务对象的唯一标识
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`auth/auth.py` 的 `delete_auth_user` 调用本符号；`unified_backend/tests/test_admin_users_api.py` 的
    #         `test_admin_user_routes_cover_full_lifecycle` 调用本符号；`unified_backend/tests/test_admin_users_api.py` 的
    #         `test_admin_route_maps_self_delete_to_conflict` 调用本符号；`unified_backend/tests/test_user_store.py` 的
    #         `test_create_update_reset_and_delete_user` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`self.initialize`、`_normalize_required`、`UserConflictError`、`self._connect`、`connection.execute`、`connection.execute('SELECT
    #          * FROM auth_users WHERE employee_id = ?',
    #          (normalized_employee_id,)).fetchone`、`UserNotFoundError`、`bool`、`self._enabled_admin_count`、`connection.commit` 等共 12
    #          个调用。
    # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
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

    # 功能：实现 `_enabled_admin_count` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `connection`（sqlite3.Connection）：`connection` 对应的业务输入值
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`auth/user_store.py` 的 `UserStore::update_user` 调用本符号；`auth/user_store.py` 的 `UserStore::delete_user` 调用本符号
    #   - 内部调用：`connection.execute("\n            SELECT COUNT(*) AS count\n            FROM auth_users\n            WHERE role =
    #          'admin' AND enabled = 1\n            ").fetchone`、`connection.execute`、`int`。
    # 副作用/注意事项：可能读取或修改数据库事务。
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


# 功能：实现 `_public_without_password` 对应的`user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `record`（dict[str, Any]）：`record` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/user_store.py` 的 `UserStore::create_user` 调用本符号；`auth/user_store.py` 的 `UserStore::update_user`
#         调用本符号；`auth/user_store.py` 的 `UserStore::update_password_hash` 调用本符号
#   - 内部调用：`record.items`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
]
