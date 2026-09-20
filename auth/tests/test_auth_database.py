from __future__ import annotations


import pytest
from starlette.requests import Request

from auth.auth import (
    AuthError,
    change_own_password,
    create_auth_user,
    create_token,
    decode_token,
    get_current_user_from_request,
    get_token_expire_hours,
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


def _configure_database_user(monkeypatch, auth_database):
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-with-at-least-32-characters")
    create_auth_user(
        employee_id="10001",
        name="管理员",
        role="admin",
        departments=["all"],
        password="database-password",
    )


def test_database_user_login_and_token_version(monkeypatch, auth_database):
    _configure_database_user(monkeypatch, auth_database)

    user = verify_login("10001", "database-password")
    assert user is not None
    assert user["auth_version"] == 1
    assert user["departments"] == ["all"]
    token = create_token(user)
    assert (
        get_current_user_from_request(_request_with_token(token))["employee_id"]
        == "10001"
    )

    changed = change_own_password(
        "10001",
        "database-password",
        "new-password",
    )
    assert changed["auth_version"] == 2

    with pytest.raises(AuthError, match="登录状态已失效"):
        get_current_user_from_request(_request_with_token(token))
    assert verify_login("10001", "database-password") is None
    assert verify_login("10001", "new-password") is not None


@pytest.mark.parametrize("version", [None, 0, True, "1", -1])
def test_token_rejects_missing_or_invalid_auth_version(
    monkeypatch, auth_database, version
):
    import hashlib
    import hmac
    from auth.auth import _json_b64, _b64url_encode, get_auth_secret

    _configure_database_user(monkeypatch, auth_database)
    claims = {"sub": "10001"}
    if version is not None:
        claims["auth_version"] = version
    message = f"{_json_b64({'alg': 'HS256'})}.{_json_b64(claims)}"
    signature = hmac.new(
        get_auth_secret().encode(), message.encode(), hashlib.sha256
    ).digest()
    with pytest.raises(AuthError, match="invalid token claims"):
        decode_token(f"{message}.{_b64url_encode(signature)}")


def test_fulida_user_login_preserves_explicit_department(monkeypatch, auth_database):
    _configure_database_user(monkeypatch, auth_database)
    create_auth_user(
        employee_id="fulida",
        name="福力达用户",
        role="viewer",
        departments=["fulida_company"],
        password="fulida-password",
    )
    user = verify_login("fulida", "fulida-password")
    assert user["departments"] == ["fulida_company"]
    assert "department" not in user
    assert get_current_user_from_request(_request_with_token(create_token(user)))[
        "departments"
    ] == ["fulida_company"]


@pytest.mark.parametrize("value", ["", "0", "never", "permanent", "forever"])
def test_persistent_token_values_remain_supported(monkeypatch, value):
    monkeypatch.setenv("AUTH_TOKEN_EXPIRE_HOURS", value)
    assert get_token_expire_hours() is None


@pytest.mark.parametrize("value", ["invalid", "-1", "1.5"])
def test_invalid_token_expiry_fails_fast(monkeypatch, value):
    monkeypatch.setenv("AUTH_TOKEN_EXPIRE_HOURS", value)
    with pytest.raises(ValueError, match="AUTH_TOKEN_EXPIRE_HOURS"):
        get_token_expire_hours()


def test_positive_token_expiry_is_returned(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN_EXPIRE_HOURS", "24")
    assert get_token_expire_hours() == 24
