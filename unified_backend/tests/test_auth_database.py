from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from auth.auth import (
    AuthError,
    change_own_password,
    create_token,
    get_current_user_from_request,
    verify_login,
)


def _request_with_token(token: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/auth/me",
            "raw_path": b"/api/auth/me",
            "query_string": b"",
            "headers": [
                (
                    b"cookie",
                    f"aicv_auth_token={token}".encode("utf-8"),
                )
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 5000),
        }
    )


def _configure_legacy_user(monkeypatch, tmp_path):
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
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "AUTH_USERS_DB",
        str(tmp_path / "runtime" / "auth_users.db"),
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(legacy_path))
    monkeypatch.setenv("AUTH_DEFAULT_PASSWORD", "legacy-password")
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-with-at-least-32-characters")


def test_migrated_default_password_user_login_and_token_version(monkeypatch, tmp_path):
    _configure_legacy_user(monkeypatch, tmp_path)

    user = verify_login("10001", "legacy-password")
    assert user is not None
    assert user["auth_version"] == 1
    assert user["departments"] == ["all"]
    token = create_token(user)
    assert get_current_user_from_request(_request_with_token(token))["employee_id"] == "10001"

    changed = change_own_password(
        "10001",
        "legacy-password",
        "new-password",
    )
    assert changed["auth_version"] == 2

    with pytest.raises(AuthError, match="登录状态已失效"):
        get_current_user_from_request(_request_with_token(token))
    assert verify_login("10001", "legacy-password") is None
    assert verify_login("10001", "new-password") is not None


def test_version_one_token_without_auth_version_remains_compatible(monkeypatch, tmp_path):
    _configure_legacy_user(monkeypatch, tmp_path)
    user = verify_login("10001", "legacy-password")
    assert user is not None

    legacy_token = create_token(
        {
            "employee_id": user["employee_id"],
            "name": user["name"],
            "role": user["role"],
            "department": user["department"],
        }
    )

    assert get_current_user_from_request(
        _request_with_token(legacy_token)
    )["auth_version"] == 1
