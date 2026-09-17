
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from AiVision.api.mounted_apps import ManagedVisualServices

import httpx
from fastapi import FastAPI, Request

from AiVision.api.app import create_app


def _config_files(tmp_path: Path) -> Path:
    security = tmp_path / "security.yaml"
    security.write_text("security: true\n", encoding="utf-8")
    return security


def _factory(name: str, events: list[str]):
    def create(config_path: Path) -> FastAPI:
        events.append(f"create:{name}:{config_path.name}")

        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            events.append(f"start:{name}")
            try:
                yield
            finally:
                events.append(f"stop:{name}")

        app = FastAPI(lifespan=lifespan)

        @app.get("/probe/{value}")
        async def probe(value: str, request: Request):
            return {
                "service": name,
                "value": value,
                "root_path": request.scope["root_path"],
            }

        return app

    return create


def _manager(tmp_path: Path, events: list[str]) -> ManagedVisualServices:
    security = _config_files(tmp_path)
    return ManagedVisualServices(
        security_vlm_config_path=security,
        security_vlm_factory=_factory("security", events),
    )


def test_visual_apps_are_called_in_process_and_share_parent_port(tmp_path):
    events: list[str] = []
    manager = _manager(tmp_path, events)

    parent = FastAPI()
    parent.mount("/security", manager.security_vlm)

    async def scenario():
        async with manager.lifespan():
            transport = httpx.ASGITransport(app=parent)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://aivision.test",
            ) as client:
                security = await client.get("/security/probe/checkpoint-a")

            assert security.status_code == 200
            assert security.json()["service"] == "security"
            assert manager.security_vlm.app is not None

    asyncio.run(scenario())

    assert manager.security_vlm.app is None
    assert events == [
        "create:security:security.yaml",
        "start:security",
        "stop:security",
    ]


def test_unbound_managed_app_returns_service_unavailable(tmp_path):
    manager = _manager(tmp_path, [])
    parent = FastAPI()
    parent.mount("/security", manager.security_vlm)

    async def scenario():
        transport = httpx.ASGITransport(app=parent)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://aivision.test",
        ) as client:
            return await client.get("/security/api/health")

    response = asyncio.run(scenario())
    assert response.status_code == 503
    assert response.json() == {"detail": "security_vlm 尚未由 AiVision 初始化"}


def test_aivision_registers_only_security_managed_route_tree(tmp_path):
    manager = _manager(tmp_path, [])
    app = create_app(managed_visual_services=manager)

    mounted_paths = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/integrations")
    }

    assert mounted_paths == {
        "/api/integrations/security-vlm",
    }


def test_missing_child_config_fails_parent_startup(tmp_path):
    manager = ManagedVisualServices(
        security_vlm_config_path=tmp_path / "missing-security.yaml",
        security_vlm_factory=_factory("security", []),
    )

    async def scenario():
        async with manager.lifespan():
            pass

    try:
        asyncio.run(scenario())
    except FileNotFoundError as exc:
        assert "missing-security.yaml" in str(exc)
    else:
        raise AssertionError("缺少托管子应用配置时 AiVision 应拒绝启动")


def test_parent_exposes_only_security_service_probe_without_auth(tmp_path, monkeypatch):
    import importlib
    from auth.auth import AuthError

    api_module = importlib.import_module("AiVision.api.app")
    manager = _manager(tmp_path, [])
    child = FastAPI()

    @child.get("/health")
    async def health():
        return {"status": "ok", "ready": True}

    def unauthenticated(_request):
        raise AuthError("authentication required")

    manager.security_vlm.bind(child)
    parent = create_app(managed_visual_services=manager)
    monkeypatch.setattr(api_module, "get_current_user_from_request", unauthenticated)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=parent), base_url="http://test") as client:
            response = await client.get("/api/integrations/security-vlm/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "ready": True}
            response = await client.get("/api/integrations/security-vlm/api/departments/fulida_company/health")
            assert response.status_code == 401

    asyncio.run(scenario())
