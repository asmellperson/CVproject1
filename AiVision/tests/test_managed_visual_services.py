import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from platform.visual_services import ManagedVisualServices

import httpx
from fastapi import FastAPI, Request

from api.app import create_app


def _config_files(tmp_path: Path) -> tuple[Path, Path]:
    guard = tmp_path / "guard.yaml"
    security = tmp_path / "security.yaml"
    guard.write_text("guard: true\n", encoding="utf-8")
    security.write_text("security: true\n", encoding="utf-8")
    return guard, security


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
    guard, security = _config_files(tmp_path)
    return ManagedVisualServices(
        repository_root=tmp_path,
        guard_room_config_path=guard,
        security_vlm_config_path=security,
        guard_room_factory=_factory("guard", events),
        security_vlm_factory=_factory("security", events),
    )


def test_visual_apps_are_called_in_process_and_share_parent_port(tmp_path):
    events: list[str] = []
    manager = _manager(tmp_path, events)

    parent = FastAPI()
    parent.mount("/guard", manager.guard_room)
    parent.mount("/security", manager.security_vlm)

    async def scenario():
        async with manager.lifespan():
            transport = httpx.ASGITransport(app=parent)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://aivision.test",
            ) as client:
                guard = await client.get("/guard/probe/room-a")
                security = await client.get("/security/probe/checkpoint-a")

            assert guard.status_code == 200
            assert guard.json() == {
                "service": "guard",
                "value": "room-a",
                "root_path": "/guard",
            }
            assert security.status_code == 200
            assert security.json()["service"] == "security"
            assert manager.guard_room.app is not None
            assert manager.security_vlm.app is not None

    asyncio.run(scenario())

    assert manager.guard_room.app is None
    assert manager.security_vlm.app is None
    assert events == [
        "create:guard:guard.yaml",
        "create:security:security.yaml",
        "start:guard",
        "start:security",
        "stop:security",
        "stop:guard",
    ]


def test_unbound_managed_app_returns_service_unavailable(tmp_path):
    manager = _manager(tmp_path, [])
    parent = FastAPI()
    parent.mount("/guard", manager.guard_room)

    async def scenario():
        transport = httpx.ASGITransport(app=parent)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://aivision.test",
        ) as client:
            return await client.get("/guard/api/health")

    response = asyncio.run(scenario())
    assert response.status_code == 503
    assert response.json() == {"detail": "guard_room 尚未由 AiVision 初始化"}


def test_aivision_registers_both_managed_route_trees(tmp_path):
    manager = _manager(tmp_path, [])
    app = create_app(managed_visual_services=manager)

    mounted_paths = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v2/integrations")
    }

    assert mounted_paths == {
        "/api/v2/integrations/guard-room",
        "/api/v2/integrations/security-vlm",
    }


def test_missing_child_config_fails_parent_startup(tmp_path):
    manager = ManagedVisualServices(
        repository_root=tmp_path,
        guard_room_config_path=tmp_path / "missing-guard.yaml",
        security_vlm_config_path=tmp_path / "missing-security.yaml",
        guard_room_factory=_factory("guard", []),
        security_vlm_factory=_factory("security", []),
    )

    async def scenario():
        async with manager.lifespan():
            pass

    try:
        asyncio.run(scenario())
    except FileNotFoundError as exc:
        assert "missing-guard.yaml" in str(exc)
        assert "missing-security.yaml" in str(exc)
    else:
        raise AssertionError("缺少托管子应用配置时 AiVision 应拒绝启动")
