"""现有前端经通用代理访问 AiVision 的唯一认证路由。"""

import asyncio
import importlib

import httpx

from auth import auth
from AiVision.api.app import create_app as create_aivision_app
from unified_backend.proxy import AsyncProxyClient


def test_gateway_forwards_login_cookie_admin_and_logout(
    auth_database, monkeypatch, tmp_path
):
    backend = importlib.import_module("unified_backend.app")
    auth.create_auth_user(
        employee_id="admin",
        name="管理员",
        role="admin",
        departments=["all"],
        password="test-password",
    )
    native = create_aivision_app()
    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path / "gateway"))
    monkeypatch.setattr(
        backend,
        "AsyncProxyClient",
        lambda settings: AsyncProxyClient(
            settings, transport=httpx.ASGITransport(app=native)
        ),
    )
    app = backend.create_app()
    assert not any(
        getattr(route, "path", "").startswith(("/api/auth/", "/api/admin/"))
        for route in app.routes
    )

    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                response = await client.post(
                    "/api/auth/login",
                    json={"employee_id": "admin", "password": "test-password"},
                )
                assert response.status_code == 200
                assert "HttpOnly" in response.headers["set-cookie"]
                assert client.cookies.get(auth.COOKIE_NAME)
                assert (await client.get("/api/auth/me")).json()["user"][
                    "employee_id"
                ] == "admin"
                assert len((await client.get("/api/admin/users")).json()["items"]) == 1
                assert (await client.post("/api/auth/logout")).json() == {
                    "success": True
                }
                assert (await client.get("/api/auth/me")).status_code == 401

    asyncio.run(scenario())
