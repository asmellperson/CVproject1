# 文件说明：实现`access_audit` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""Privacy-minimal access audit storage for the unified visual platform."""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, status

from auth.auth import get_current_user


DEFAULT_PLATFORM_OWNER_EMPLOYEE_ID = "260210063"
DEFAULT_ACCESS_AUDIT_LIMIT = 100
MAX_ACCESS_AUDIT_LIMIT = 500
DEFAULT_ACCESS_AUDIT_RETENTION_DAYS = 90


# 功能：读取或查询 `get_platform_owner_employee_id` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/access_audit.py` 的 `is_platform_owner` 调用本符号
#   - 内部调用：`os.getenv('PLATFORM_OWNER_EMPLOYEE_ID', DEFAULT_PLATFORM_OWNER_EMPLOYEE_ID).strip`、`os.getenv`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_platform_owner_employee_id() -> str:
    return os.getenv(
        "PLATFORM_OWNER_EMPLOYEE_ID",
        DEFAULT_PLATFORM_OWNER_EMPLOYEE_ID,
    ).strip()


# 功能：读取或查询 `get_access_audit_retention_days` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/access_audit.py` 的 `AccessAuditStore::_delete_expired` 调用本符号
#   - 内部调用：`os.getenv`、`str`、`max`、`int`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_access_audit_retention_days() -> int:
    raw_value = os.getenv(
        "ACCESS_AUDIT_RETENTION_DAYS",
        str(DEFAULT_ACCESS_AUDIT_RETENTION_DAYS),
    )
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_ACCESS_AUDIT_RETENTION_DAYS


# 功能：检查或判断 `is_platform_owner` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any] | None）：当前用户或待处理用户对象
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/access_audit.py` 的 `require_access_audit_owner` 调用本符号；`unified_backend/access_audit.py` 的
#         `add_access_audit_capability` 调用本符号
#   - 内部调用：`str(user.get('employee_id', '')).strip`、`str`、`user.get`、`get_platform_owner_employee_id`、`bool`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def is_platform_owner(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    employee_id = str(user.get("employee_id", "")).strip()
    owner_employee_id = get_platform_owner_employee_id()
    return bool(employee_id and owner_employee_id and employee_id == owner_employee_id)


# 功能：实现 `require_access_audit_owner` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_access_audit_api.py` 的 `test_access_audit_owner_dependency_rejects_other_admins` 调用本符号
#   - 内部调用：`Depends`、`is_platform_owner`、`HTTPException`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def require_access_audit_owner(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not is_platform_owner(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="access audit permission required",
        )
    return user


# 功能：创建或构建 `add_access_audit_capability` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::login` 调用本符号；`unified_backend/app.py` 的 `create_app::me`
#         调用本符号；`unified_backend/app.py` 的 `create_app::change_password` 调用本符号
#   - 内部调用：`dict`、`is_platform_owner`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def add_access_audit_capability(user: dict[str, Any]) -> dict[str, Any]:
    public_user = dict(user)
    public_user["capabilities"] = {
        "view_access_audit": is_platform_owner(user),
    }
    return public_user


# 功能：Keep one aggregated, privacy-minimal access record per account；输入与输出详见下方说明
# 参数：
#   - `database_path`（str | Path）：`database_path` 对应的业务输入值
# 返回：AccessAuditStore；返回新建的 `AccessAuditStore` 实例。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_access_audit_api.py` 的 `test_access_audit_store_aggregates_by_user_and_orders_recent_first`
#         实例化本符号；`unified_backend/app.py` 的 `create_app` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AccessAuditStore:
    """Keep one aggregated, privacy-minimal access record per account."""

    # 功能：初始化或配置 `__init__` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `database_path`（str | Path）：`database_path` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path`、`threading.Lock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self._initialize_lock = threading.Lock()
        self._initialized = False

    # 功能：实现 `_connect` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：sqlite3.Connection；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`unified_backend/access_audit.py` 的 `AccessAuditStore::initialize` 调用本符号；`unified_backend/access_audit.py` 的
    #         `AccessAuditStore::record_visit` 调用本符号；`unified_backend/access_audit.py` 的 `AccessAuditStore::list_recent` 调用本符号
    #   - 内部调用：`sqlite3.connect`、`connection.execute`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    # 功能：初始化或配置 `initialize` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`unified_backend/access_audit.py` 的 `AccessAuditStore::record_visit` 调用本符号；`unified_backend/access_audit.py` 的
    #         `AccessAuditStore::list_recent` 调用本符号
    #   - 内部调用：`self.database_path.parent.mkdir`、`self._connect`、`connection.execute`、`connection.commit`、`connection.close`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能读取或修改数据库事务。
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
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS access_viewers (
                        employee_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        role TEXT NOT NULL,
                        department TEXT,
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        visit_count INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_access_viewers_last_seen
                    ON access_viewers(last_seen_at DESC)
                    """
                )
                connection.commit()
                self._initialized = True
            finally:
                connection.close()

    # 功能：实现 `record_visit` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `user`（dict[str, Any]）：当前用户或待处理用户对象
    #   - `visited_at`（datetime | None）：`visited_at` 对应的业务输入值；默认值为 `None`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`unified_backend/tests/test_access_audit_api.py` 的
    #         `test_access_audit_store_aggregates_by_user_and_orders_recent_first` 调用本符号；`unified_backend/app.py` 的
    #         `create_app::login` 调用本符号；`unified_backend/app.py` 的 `create_app::me` 调用本符号
    #   - 内部调用：`str(user.get('employee_id', '')).strip`、`str`、`user.get`、`str(user.get('name',
    #          '')).strip`、`ValueError`、`self.initialize`、`datetime.now`、`visit_time.replace`、`visit_time.astimezone`、`visit_time.isoformat().replace`
    #          等共 18 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
    def record_visit(
        self,
        user: dict[str, Any],
        *,
        visited_at: datetime | None = None,
    ) -> None:
        employee_id = str(user.get("employee_id", "")).strip()
        name = str(user.get("name", "")).strip()
        if not employee_id or not name:
            raise ValueError("access audit requires employee_id and name")

        self.initialize()
        visit_time = visited_at or datetime.now(timezone.utc)
        if visit_time.tzinfo is None:
            visit_time = visit_time.replace(tzinfo=timezone.utc)
        visit_time = visit_time.astimezone(timezone.utc)
        timestamp = visit_time.isoformat().replace("+00:00", "Z")
        connection = self._connect()
        try:
            self._delete_expired(connection, visit_time)
            connection.execute(
                """
                INSERT INTO access_viewers (
                    employee_id,
                    name,
                    role,
                    department,
                    first_seen_at,
                    last_seen_at,
                    visit_count
                ) VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(employee_id) DO UPDATE SET
                    name = excluded.name,
                    role = excluded.role,
                    department = excluded.department,
                    last_seen_at = excluded.last_seen_at,
                    visit_count = access_viewers.visit_count + 1
                """,
                (
                    employee_id,
                    name,
                    str(user.get("role", "")).strip(),
                    str(user.get("department", "")).strip() or None,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    # 功能：读取或查询 `list_recent` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `limit`（int）：返回或处理的最大记录数；默认值为 `DEFAULT_ACCESS_AUDIT_LIMIT`
    # 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`unified_backend/tests/test_access_audit_api.py` 的
    #         `test_access_audit_store_aggregates_by_user_and_orders_recent_first` 调用本符号；`unified_backend/app.py` 的
    #         `create_app::access_audit` 调用本符号
    #   - 内部调用：`self.initialize`、`max`、`min`、`int`、`self._connect`、`self._delete_expired`、`datetime.now`、`connection.execute('\n
    #          SELECT\n                    employee_id,\n                    name,\n                    role,\n
    #          department,\n                    first_seen_at,\n                    last_seen_at,\n                    visit_count\n
    #          FROM access_viewers\n                ORDER BY last_seen_at DESC, employee_id ASC\n                LIMIT ?\n
    #          ', (normalized_limit,)).fetchall`、`connection.execute`、`connection.commit` 等共 12 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def list_recent(self, limit: int = DEFAULT_ACCESS_AUDIT_LIMIT) -> list[dict[str, Any]]:
        self.initialize()
        normalized_limit = max(1, min(int(limit), MAX_ACCESS_AUDIT_LIMIT))
        connection = self._connect()
        try:
            self._delete_expired(connection, datetime.now(timezone.utc))
            rows = connection.execute(
                """
                SELECT
                    employee_id,
                    name,
                    role,
                    department,
                    first_seen_at,
                    last_seen_at,
                    visit_count
                FROM access_viewers
                ORDER BY last_seen_at DESC, employee_id ASC
                LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()
            connection.commit()
        finally:
            connection.close()
        return [dict(row) for row in rows]

    # 功能：删除或清理 `_delete_expired` 对应的`access_audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `connection`（sqlite3.Connection）：`connection` 对应的业务输入值
    #   - `reference_time`（datetime）：`reference_time` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`unified_backend/access_audit.py` 的 `AccessAuditStore::record_visit` 调用本符号；`unified_backend/access_audit.py` 的
    #         `AccessAuditStore::list_recent` 调用本符号
    #   - 内部调用：`timedelta`、`get_access_audit_retention_days`、`cutoff.astimezone(timezone.utc).isoformat().replace`、`cutoff.astimezone(timezone.utc).isoformat`、`cutoff.astimezone`、`connection.execute`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能读取或修改数据库事务。
    @staticmethod
    def _delete_expired(
        connection: sqlite3.Connection,
        reference_time: datetime,
    ) -> None:
        cutoff = reference_time - timedelta(days=get_access_audit_retention_days())
        cutoff_value = cutoff.astimezone(timezone.utc).isoformat().replace(
            "+00:00",
            "Z",
        )
        connection.execute(
            "DELETE FROM access_viewers WHERE last_seen_at < ?",
            (cutoff_value,),
        )
