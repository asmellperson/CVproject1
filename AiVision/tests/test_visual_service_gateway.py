from __future__ import annotations

import asyncio
import importlib
import sys
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

sys.modules.pop("platform", None)
visual_services_api = importlib.import_module("api.v2.visual_services")
visual_services_client = importlib.import_module("platform.visual_services.client")
VisualWorkerClient = visual_services_client.VisualWorkerClient


def _settings(**overrides):
    values = {
        "guard_room_url": "http://guard-worker:5001",
        "security_vlm_url": "http://security-worker:8000",
        "max_connections": 32,
        "max_keepalive_connections": 16,
        "connect_timeout_seconds": 3.0,
        "pool_timeout_seconds": 2.0,
        "write_timeout_seconds": 10.0,
        "read_timeout_seconds": 10.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_aivision_app_registers_both_visual_worker_routes():
    app_module = importlib.import_module("api.app")
    registered_paths: set[str] = set()
    for route in app_module.app.routes:
        path = getattr(route, "path", None)
        if path:
            registered_paths.add(path)
        included_router = getattr(route, "original_router", None)
        if included_router is not None:
            registered_paths.update(
                child.path
                for child in included_router.routes
                if getattr(child, "path", None)
            )

    assert "/api/v2/integrations/guard-room/{path:path}" in registered_paths
    assert "/api/v2/integrations/security-vlm/{path:path}" in registered_paths


def test_visual_service_routes_preserve_paths_queries_and_streaming_headers():
    async def scenario():
        upstream_requests: list[httpx.Request] = []

        async def upstream(request: httpx.Request) -> httpx.Response:
            upstream_requests.append(request)
            return httpx.Response(
                200,
                headers={
                    "content-type": "image/jpeg",
                    "content-length": "11",
                    "connection": "keep-alive",
                    "x-frame-width": "1920",
                },
                content=b"frame-bytes",
                request=request,
            )

        worker_client = VisualWorkerClient(
            _settings(),
            transport=httpx.MockTransport(upstream),
        )
        app = FastAPI()
        app.state.visual_worker_client = worker_client
        app.include_router(visual_services_api.router)

        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://control-plane",
            ) as client:
                guard_response = await client.get(
                    "/api/v2/integrations/guard-room/api/sites",
                    params={"department": "general_electric"},
                    headers={"cookie": "session=test"},
                )
                security_response = await client.get(
                    "/api/v2/integrations/security-vlm/video/camera-a/rule",
                    params={"nonce": "7"},
                )

            assert guard_response.status_code == 200
            assert guard_response.content == b"frame-bytes"
            assert guard_response.headers["x-frame-width"] == "1920"
            assert "content-length" not in guard_response.headers
            assert security_response.status_code == 200
            assert [str(request.url) for request in upstream_requests] == [
                (
                    "http://guard-worker:5001/api/sites"
                    "?department=general_electric"
                ),
                (
                    "http://security-worker:8000/video/camera-a/rule"
                    "?nonce=7"
                ),
            ]
            assert upstream_requests[0].headers["cookie"] == "session=test"
        finally:
            await worker_client.close()

    asyncio.run(scenario())


def test_visual_service_route_maps_unavailable_worker_to_bad_gateway():
    async def scenario():
        async def unavailable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        worker_client = VisualWorkerClient(
            _settings(),
            transport=httpx.MockTransport(unavailable),
        )
        app = FastAPI()
        app.state.visual_worker_client = worker_client
        app.include_router(visual_services_api.router)

        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://control-plane",
            ) as client:
                response = await client.get(
                    "/api/v2/integrations/security-vlm/health"
                )

            assert response.status_code == 502
            assert response.json() == {
                "detail": "security_vlm worker unavailable"
            }
        finally:
            await worker_client.close()

    asyncio.run(scenario())


def test_visual_worker_pool_rejects_keepalive_larger_than_total_connections():
    try:
        VisualWorkerClient(
            _settings(max_connections=4, max_keepalive_connections=5)
        )
    except ValueError as exc:
        assert "MAX_KEEPALIVE_CONNECTIONS" in str(exc)
    else:
        raise AssertionError("无效连接池配置应在启动时被拒绝")
