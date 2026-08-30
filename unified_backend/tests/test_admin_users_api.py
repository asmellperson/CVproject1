from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from auth.auth import require_admin
from unified_backend.app import (
    AdminUserCreateRequest,
    AdminUserPasswordResetRequest,
    AdminUserUpdateRequest,
    create_app,
)


def _configure_users(monkeypatch, tmp_path):
    legacy_path = tmp_path / "auth_users.json"
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "employee_id": "10001",
                    "name": "管理员",
                    "role": "admin",
                    "department": "all",
                    "enabled": True,
                },
                {
                    "employee_id": "10002",
                    "name": "普通用户",
                    "role": "viewer",
                    "department": "general_electric",
                    "enabled": True,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(legacy_path))
    monkeypatch.setenv(
        "AUTH_USERS_DB",
        str(tmp_path / "runtime" / "auth_users.db"),
    )


def _endpoint(app, path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(
            route,
            "methods",
            set(),
        ):
            return route.endpoint, route
    raise AssertionError(f"route not found: {method} {path}")


def _assert_no_password_material(payload):
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "password_hash" not in serialized
    assert "new_password" not in serialized
    assert '"password"' not in serialized


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
