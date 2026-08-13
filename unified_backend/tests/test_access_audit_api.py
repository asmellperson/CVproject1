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


def _endpoint(app, path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(
            route,
            "methods",
            set(),
        ):
            return route.endpoint, route
    raise AssertionError(f"route not found: {method} {path}")


def _user(employee_id: str, name: str, role: str = "viewer") -> dict:
    return {
        "employee_id": employee_id,
        "name": name,
        "role": role,
        "department": "all" if role == "admin" else "general_electric",
    }


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


def test_access_audit_owner_dependency_rejects_other_admins(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_EMPLOYEE_ID", "10001")

    with pytest.raises(HTTPException) as exc_info:
        require_access_audit_owner(_user("10003", "其他管理员", "admin"))

    assert exc_info.value.status_code == 403
