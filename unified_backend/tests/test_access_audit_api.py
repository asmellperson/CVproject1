# 文件说明：包含接口访问的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from unified_backend.access_audit import (
    AccessAuditStore,
    require_access_audit_owner,
)
from unified_backend.app import create_app


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


# 功能：实现 `_user` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
#   - `name`（str）：业务对象名称
#   - `role`（str）：`role` 对应的业务输入值；默认值为 `'viewer'`
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_access_audit_api.py` 的 `test_access_audit_store_aggregates_by_user_and_orders_recent_first`
#         调用本符号；`unified_backend/tests/test_access_audit_api.py` 的 `test_access_audit_route_is_owner_only_and_me_records_visits`
#         调用本符号；`unified_backend/tests/test_access_audit_api.py` 的 `test_access_audit_owner_dependency_rejects_other_admins` 调用本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _user(employee_id: str, name: str, role: str = "viewer") -> dict:
    return {
        "employee_id": employee_id,
        "name": name,
        "role": role,
        "departments": ["all" if role == "admin" else "general_electric"],
    }


# 功能：验证 `test_access_audit_store_aggregates_by_user_and_orders_recent_first` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AccessAuditStore`、`datetime`、`store.record_visit`、`_user`、`store.list_recent`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_access_audit_store_aggregates_by_user_and_orders_recent_first(tmp_path):
    store = AccessAuditStore(tmp_path / "access_audit.db")
    first = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 8, 13, 9, 30, tzinfo=timezone.utc)

    store.record_visit(
        _user("10003", "过期用户"),
        visited_at=datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc),
    )
    store.record_visit(_user("10002", "普通用户"), visited_at=first)
    store.record_visit(_user("10001", "平台所有者", "admin"), visited_at=first)
    store.record_visit(_user("10002", "普通用户（新姓名）"), visited_at=latest)

    items = store.list_recent()

    assert [item["employee_id"] for item in items] == ["10002", "10001"]
    assert items[0]["name"] == "普通用户（新姓名）"
    assert items[0]["visit_count"] == 2
    assert items[0]["first_seen_at"] == "2026-08-12T08:00:00Z"
    assert items[0]["last_seen_at"] == "2026-08-13T09:30:00Z"


# 功能：验证 `test_access_audit_route_is_owner_only_and_me_records_visits` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setenv`、`str`、`create_app`、`_endpoint`、`_user`、`any`、`me`、`list_access_audit`、`json.dumps`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_access_audit_route_is_owner_only_and_me_records_visits(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("PLATFORM_OWNER_EMPLOYEE_ID", "10001")
    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path))
    app = create_app()
    me, _me_route = _endpoint(app, "/api/auth/me", "GET")
    list_access_audit, audit_route = _endpoint(
        app,
        "/api/admin/access-audit",
        "GET",
    )
    owner = _user("10001", "平台所有者", "admin")
    viewer = _user("10002", "普通用户")

    assert any(
        dependency.call is require_access_audit_owner
        for dependency in audit_route.dependant.dependencies
    )
    assert me(viewer)["user"]["capabilities"]["view_access_audit"] is False
    assert me(owner)["user"]["capabilities"]["view_access_audit"] is True

    payload = list_access_audit(100, owner)
    assert [item["employee_id"] for item in payload["items"]] == [
        "10001",
        "10002",
    ]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "password" not in serialized
    assert "token" not in serialized


# 功能：验证 `test_access_audit_owner_dependency_rejects_other_admins` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setenv`、`pytest.raises`、`require_access_audit_owner`、`_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_access_audit_owner_dependency_rejects_other_admins(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_EMPLOYEE_ID", "10001")

    with pytest.raises(HTTPException) as exc_info:
        require_access_audit_owner(_user("10003", "其他管理员", "admin"))

    assert exc_info.value.status_code == 403
