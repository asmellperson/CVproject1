"""通过 AiVision HTTP 验证登录、账号权限、改密和审计链路。"""

import pytest
from sqlalchemy.exc import OperationalError

from auth import api, auth


def login(client, employee_id="10001"):
    response = client.post(
        "/api/auth/login",
        json={"employee_id": employee_id, "password": "test-password"},
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    return response


def test_admin_user_lifecycle(client):
    assert client.get("/api/admin/users").status_code == 401
    login(client)
    assert len(client.get("/api/admin/users").json()["items"]) == 3
    data = {
        "employee_id": "20001",
        "name": "跨部门用户",
        "role": "viewer",
        "departments": ["electronics_electrician", "electrical_components"],
        "password": "initial-password",
    }
    created = client.post("/api/admin/users", json=data)
    assert created.status_code == 200
    assert created.json()["user"]["departments"] == data["departments"]
    assert "password" not in created.text
    assert client.post("/api/admin/users", json=data).status_code == 409
    updated = client.patch(
        "/api/admin/users/20001",
        json={
            "name": "新管理员",
            "role": "admin",
            "departments": ["all"],
            "enabled": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["user"]["role"] == "admin"
    assert (
        client.post(
            "/api/admin/users/20001/reset-password",
            json={"new_password": "reset-password"},
        ).json()["user"]["auth_version"]
        == 2
    )
    assert client.delete("/api/admin/users/20001").json() == {"success": True}
    assert client.delete("/api/admin/users/20001").status_code == 404
    assert client.delete("/api/admin/users/10001").status_code == 409


def test_viewer_permissions_and_token_revocation(client):
    login(client, "10002")
    assert client.get("/api/admin/users").status_code == 403
    token = client.cookies.get(auth.COOKIE_NAME)
    response = client.post(
        "/api/auth/password",
        json={"current_password": "test-password", "new_password": "new-password"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["auth_version"] == 2
    assert (
        client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"employee_id": "10002", "password": "new-password"}
        ).status_code
        == 200
    )
    assert client.post("/api/auth/logout").json() == {"success": True}
    assert client.get("/api/auth/me").status_code == 401


def test_disabled_account_and_changed_permissions_take_effect(client):
    login(client, "10002")
    token = client.cookies.get(auth.COOKIE_NAME)
    login(client)
    body = {
        "name": "用户-10002",
        "role": "viewer",
        "departments": ["haoda_company"],
        "enabled": True,
    }
    assert client.patch("/api/admin/users/10002", json=body).status_code == 200
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).json()["user"][
        "departments"
    ] == ["haoda_company"]
    assert (
        client.patch(
            "/api/admin/users/10002", json={**body, "enabled": False}
        ).status_code
        == 200
    )
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_access_audit_is_owner_only_and_aggregates_visits(client):
    assert (
        login(client, "10002").json()["user"]["capabilities"]["view_access_audit"]
        is False
    )
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/admin/access-audit").status_code == 403
    login(client, "10003")
    assert client.get("/api/admin/access-audit").status_code == 403
    assert login(client).json()["user"]["capabilities"]["view_access_audit"] is True
    response = client.get("/api/admin/access-audit")
    assert response.status_code == 200
    rows = response.json()["items"]
    assert [row["employee_id"] for row in rows] == ["10001", "10003", "10002"]
    assert rows[-1]["visit_count"] == 2
    assert "password" not in response.text and "token" not in response.text
    assert client.get("/api/admin/access-audit?limit=501").status_code == 422


def test_audit_failure_is_logged_without_breaking_login(client, monkeypatch, caplog):
    def unavailable(*args, **kwargs):
        raise OperationalError(
            "private SQL", {"password_hash": "private"}, RuntimeError("offline")
        )

    monkeypatch.setattr(api.access_audit_store, "record_visit", unavailable)
    login(client)
    assert "记录平台访问失败" in caplog.text
    assert "OperationalError" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize(
    "path,payload",
    [
        (
            "/api/auth/login",
            {"employee_id": "10001", "password": "test-password", "department": "all"},
        ),
        (
            "/api/admin/users",
            {
                "employee_id": "20001",
                "name": "用户",
                "password": "initial-password",
                "role": "viewer",
                "department": "general_electric",
            },
        ),
    ],
)
def test_api_rejects_obsolete_fields(client, path, payload):
    login(client)
    assert client.post(path, json=payload).status_code == 422
