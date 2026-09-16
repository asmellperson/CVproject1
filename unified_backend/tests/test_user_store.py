# 文件说明：包含`test_user_store` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

import sqlite3

import pytest

from auth.user_store import (
    UserConflictError,
    UserNotFoundError,
    UserStore,
    UserValidationError,
)


# 功能：实现 `_store` 对应的`test_user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_user_store.py` 的 `test_initializes_and_reads_users_from_database`
#         调用本符号；`unified_backend/tests/test_user_store.py` 的 `test_create_update_reset_and_delete_user`
#         调用本符号；`unified_backend/tests/test_user_store.py` 的 `test_accepts_haoda_company_viewer_department`
#         调用本符号；`unified_backend/tests/test_user_store.py` 的 `test_accepts_precious_metal_recycling_department` 调用本符号；另有 5
#         处静态调用
#   - 内部调用：`UserStore`、`store.create_user`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _store(tmp_path):
    store = UserStore(database_path=tmp_path / "runtime" / "auth_users.db")
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


# 功能：验证 `test_initializes_and_reads_users_from_database` 对应的`test_user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_store`、`store.list_users`、`store.get_user_record`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_initializes_and_reads_users_from_database(tmp_path):
    store = _store(tmp_path)

    assert [item["employee_id"] for item in store.list_users()] == [
        "10001",
        "10002",
    ]
    assert store.get_user_record("10001")["password_hash"] == "hash-admin"
    assert store.get_user_record("10002")["password_hash"] == "hash-viewer"

# 功能：验证 `test_create_update_reset_and_delete_user` 对应的`test_user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_store`、`store.create_user`、`store.update_user`、`store.update_password_hash`、`store.get_user_record`、`store.delete_user`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_create_update_reset_and_delete_user(tmp_path):
    store = _store(tmp_path)

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


# 功能：验证 `test_accepts_haoda_company_viewer_department` 对应的`test_user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_store`、`store.create_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_accepts_haoda_company_viewer_department(tmp_path):
    store = _store(tmp_path)

    created = store.create_user(
        employee_id="20002",
        name="皓达公司用户",
        role="viewer",
        departments=["haoda_company"],
        password_hash="hash-haoda",
    )

    assert created["departments"] == ["haoda_company"]


# 功能：验证 `test_accepts_precious_metal_recycling_department` 对应的`test_user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_store`、`store.create_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_accepts_precious_metal_recycling_department(tmp_path):
    store = _store(tmp_path)

    created = store.create_user(
        employee_id="20003",
        name="伟达公司用户",
        role="viewer",
        departments=["precious_metal_recycling"],
        password_hash="hash-weida",
    )

    assert created["departments"] == ["precious_metal_recycling"]


# 功能：验证 `test_creates_and_updates_viewer_with_multiple_departments` 对应的`test_user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_store`、`store.create_user`、`store.update_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_creates_and_updates_viewer_with_multiple_departments(tmp_path):
    store = _store(tmp_path)

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


def test_user_schema_has_only_formal_departments_field(tmp_path):
    store = _store(tmp_path)
    with sqlite3.connect(store.database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(auth_users)")}
    assert "departments" in columns
    assert "department" not in columns



# 功能：验证 `test_rejects_invalid_or_duplicate_users` 对应的`test_user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_store`、`pytest.raises`、`store.create_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_rejects_invalid_or_duplicate_users(tmp_path):
    store = _store(tmp_path)

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


# 功能：验证 `test_protects_current_user_and_last_enabled_admin` 对应的`test_user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_store`、`pytest.raises`、`store.update_user`、`store.delete_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_protects_current_user_and_last_enabled_admin(tmp_path):
    store = _store(tmp_path)

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


# 功能：验证 `test_allows_admin_change_when_another_enabled_admin_exists` 对应的`test_user_store` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_store`、`store.create_user`、`store.update_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_allows_admin_change_when_another_enabled_admin_exists(tmp_path):
    store = _store(tmp_path)
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


@pytest.mark.parametrize("department", ["研究院", "福达新材院", "通用电气", "电子电工", "伟达公司", "皓达公司", "ge", "general-electric", "general electric", "electronics-electrician", "weida", "weida_company", "haoda", "all"])
def test_rejects_department_aliases_on_create_and_update(tmp_path, department):
    store = _store(tmp_path)
    with pytest.raises(UserValidationError, match="有效事业部"):
        store.create_user(employee_id="invalid", name="非法事业部", role="viewer", departments=[department], password_hash="hash")
    with pytest.raises(UserValidationError, match="有效事业部"):
        store.update_user("10002", actor_employee_id="10001", name="普通用户", role="viewer", departments=[department], enabled=True)
    assert store.get_user_record("10002")["departments"] == ["general_electric"]
