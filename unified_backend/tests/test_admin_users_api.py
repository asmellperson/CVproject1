# 文件说明：包含接口访问的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from auth.auth import create_auth_user, require_admin
from unified_backend.app import (
    AdminUserCreateRequest,
    AdminUserPasswordResetRequest,
    AdminUserUpdateRequest,
    create_app,
)


# 功能：初始化或配置 `_configure_users` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_admin_users_api.py` 的 `test_admin_user_routes_cover_full_lifecycle`
#         调用本符号；`unified_backend/tests/test_admin_users_api.py` 的 `test_admin_route_maps_self_delete_to_conflict` 调用本符号
#   - 内部调用：`monkeypatch.setenv`、`create_auth_user`、`str`。
# 副作用/注意事项：会创建和写入临时 SQLite 用户数据库。
def _configure_users(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "AUTH_USERS_DB",
        str(tmp_path / "runtime" / "auth_users.db"),
    )
    create_auth_user(
        employee_id="10001",
        name="管理员",
        role="admin",
        department="all",
        password="admin-password",
    )
    create_auth_user(
        employee_id="10002",
        name="普通用户",
        role="viewer",
        department="general_electric",
        password="viewer-password",
    )


# 功能：实现 `_endpoint` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `app`（未显式标注）：`app` 对应的业务输入值
#   - `path`（str）：目标路径
#   - `method`（str）：`method` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`getattr`、`set`、`AssertionError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _endpoint(app, path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(
            route,
            "methods",
            set(),
        ):
            return route.endpoint, route
    raise AssertionError(f"route not found: {method} {path}")


# 功能：实现 `_assert_no_password_material` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（未显式标注）：接口或事件携带的业务数据
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_admin_users_api.py` 的 `test_admin_user_routes_cover_full_lifecycle` 调用本符号
#   - 内部调用：`json.dumps`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _assert_no_password_material(payload):
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "password_hash" not in serialized
    assert "new_password" not in serialized
    assert '"password"' not in serialized


# 功能：验证 `test_admin_user_routes_cover_full_lifecycle` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_configure_users`、`create_app`、`_endpoint`、`any`、`list_users`、`len`、`_assert_no_password_material`、`create_user`、`AdminUserCreateRequest`、`update_user`
#          等共 14 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_admin_user_routes_cover_full_lifecycle(monkeypatch, tmp_path):
    _configure_users(monkeypatch, tmp_path)
    app = create_app()
    admin = {
        "employee_id": "10001",
        "name": "管理员",
        "role": "admin",
        "department": "all",
    }

    list_users, list_route = _endpoint(app, "/api/admin/users", "GET")
    create_user, create_route = _endpoint(app, "/api/admin/users", "POST")
    update_user, update_route = _endpoint(
        app,
        "/api/admin/users/{employee_id}",
        "PATCH",
    )
    reset_password, reset_route = _endpoint(
        app,
        "/api/admin/users/{employee_id}/reset-password",
        "POST",
    )
    delete_user, delete_route = _endpoint(
        app,
        "/api/admin/users/{employee_id}",
        "DELETE",
    )
    for route in (
        list_route,
        create_route,
        update_route,
        reset_route,
        delete_route,
    ):
        assert any(
            dependency.call is require_admin
            for dependency in route.dependant.dependencies
        )

    initial = list_users(admin)
    assert len(initial["items"]) == 2
    _assert_no_password_material(initial)

    created = create_user(
        AdminUserCreateRequest(
            employee_id="20001",
            name="电子电工用户",
            role="viewer",
            departments=[
                "electronics_electrician",
                "electrical_components",
            ],
            password="initial-password",
        ),
        admin,
    )
    assert created["user"]["department"] == "electronics_electrician"
    assert created["user"]["departments"] == [
        "electronics_electrician",
        "electrical_components",
    ]
    _assert_no_password_material(created)

    updated = update_user(
        "20001",
        AdminUserUpdateRequest(
            name="第二管理员",
            role="admin",
            department=None,
            enabled=True,
        ),
        admin,
    )
    assert updated["user"]["role"] == "admin"
    assert updated["user"]["department"] == "all"
    assert updated["user"]["departments"] == ["all"]

    reset = reset_password(
        "20001",
        AdminUserPasswordResetRequest(new_password="reset-password"),
        admin,
    )
    assert reset["user"]["auth_version"] == 2
    _assert_no_password_material(reset)

    deleted = delete_user("20001", admin)
    assert deleted == {"success": True}
    assert [item["employee_id"] for item in list_users(admin)["items"]] == [
        "10001",
        "10002",
    ]


# 功能：验证 `test_viewer_is_rejected_by_admin_dependency` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`require_admin`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_viewer_is_rejected_by_admin_dependency():
    with pytest.raises(HTTPException) as exc_info:
        require_admin(
            {
                "employee_id": "10002",
                "role": "viewer",
                "department": "general_electric",
            }
        )
    assert exc_info.value.status_code == 403


# 功能：验证 `test_admin_route_maps_self_delete_to_conflict` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_configure_users`、`create_app`、`_endpoint`、`pytest.raises`、`delete_user`、`str`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_admin_route_maps_self_delete_to_conflict(monkeypatch, tmp_path):
    _configure_users(monkeypatch, tmp_path)
    app = create_app()
    delete_user, _route = _endpoint(
        app,
        "/api/admin/users/{employee_id}",
        "DELETE",
    )
    admin = {
        "employee_id": "10001",
        "role": "admin",
        "department": "all",
    }

    with pytest.raises(HTTPException) as exc_info:
        delete_user("10001", admin)

    assert exc_info.value.status_code == 409
    assert "当前登录" in str(exc_info.value.detail)
