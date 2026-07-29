from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import StreamingResponse

from unified_backend.app import _proxy
from unified_backend.proxy import (
    AsyncProxyClient,
    ProxyRequestError,
    ProxySettings,
    filtered_response_headers,
)


def _settings() -> ProxySettings:
    return ProxySettings(
        max_connections=512,
        max_keepalive_connections=128,
        connect_timeout_seconds=3.0,
        pool_timeout_seconds=2.0,
        write_timeout_seconds=10.0,
        read_timeout_seconds=10.0,
    )


def test_proxy_settings_read_environment(monkeypatch):
    monkeypatch.setenv("UNIFIED_PROXY_MAX_CONNECTIONS", "600")
    monkeypatch.setenv("UNIFIED_PROXY_MAX_KEEPALIVE_CONNECTIONS", "200")
    monkeypatch.setenv("UNIFIED_PROXY_CONNECT_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("UNIFIED_PROXY_POOL_TIMEOUT_SECONDS", "1.25")
    monkeypatch.setenv("UNIFIED_PROXY_WRITE_TIMEOUT_SECONDS", "8")
    monkeypatch.setenv("UNIFIED_PROXY_READ_TIMEOUT_SECONDS", "9")

    settings = ProxySettings.from_env()

    assert settings.max_connections == 600
    assert settings.max_keepalive_connections == 200
    assert settings.connect_timeout_seconds == 1.5
    assert settings.pool_timeout_seconds == 1.25
    assert settings.write_timeout_seconds == 8.0
    assert settings.read_timeout_seconds == 9.0


def test_fifty_viewers_at_five_fps_do_not_block_event_loop():
    async def scenario():
        release = asyncio.Event()
        all_entered = asyncio.Event()
        entered = 0

        async def slow_upstream(request: httpx.Request) -> httpx.Response:
            nonlocal entered
            entered += 1
            if entered == 250:
                all_entered.set()
            await release.wait()
            return httpx.Response(200, content=b"frame-bytes", request=request)

        proxy = AsyncProxyClient(
            _settings(),
            transport=httpx.MockTransport(slow_upstream),
        )
        tasks = [
            asyncio.create_task(
                proxy.send(
                    method="GET",
                    url=f"http://upstream/frame.jpg?viewer={viewer}",
                    body=b"",
                    headers={},
                )
            )
            for viewer in range(250)
        ]
        try:
            await asyncio.wait_for(all_entered.wait(), timeout=1.0)
            loop = asyncio.get_running_loop()
            started_at = loop.time()
            await asyncio.wait_for(asyncio.sleep(0), timeout=0.2)
            assert loop.time() - started_at < 0.2

            release.set()
            responses = await asyncio.gather(*tasks)
            assert len(responses) == 250
            for response in responses:
                assert await response.aread() == b"frame-bytes"
                await response.aclose()
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await proxy.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("upstream_error", "expected_status"),
    [
        (httpx.ConnectError("connection refused"), 502),
        (httpx.ReadTimeout("upstream stalled"), 504),
        (httpx.PoolTimeout("connection pool exhausted"), 504),
    ],
)
def test_proxy_maps_upstream_failures(upstream_error, expected_status):
    async def scenario():
        async def failing_upstream(request: httpx.Request) -> httpx.Response:
            upstream_error.request = request
            raise upstream_error

        proxy = AsyncProxyClient(
            _settings(),
            transport=httpx.MockTransport(failing_upstream),
        )
        try:
            with pytest.raises(ProxyRequestError) as exc_info:
                await proxy.send(
                    method="GET",
                    url="http://upstream/frame.jpg",
                    body=b"",
                    headers={},
                )
            assert exc_info.value.status_code == expected_status
        finally:
            await proxy.close()

    asyncio.run(scenario())


def test_filtered_response_headers_remove_connection_specific_values():
    headers = httpx.Headers(
        {
            "content-type": "image/jpeg",
            "content-length": "123",
            "content-encoding": "gzip",
            "connection": "keep-alive",
            "transfer-encoding": "chunked",
            "x-frame-width": "1920",
        }
    )

    filtered = filtered_response_headers(headers)

    assert filtered == {
        "content-type": "image/jpeg",
        "x-frame-width": "1920",
    }


def test_fastapi_proxy_uses_app_scoped_async_client(monkeypatch):
    class FakeProxyClient:
        def __init__(self):
            self.call = None

        async def send(self, **kwargs):
            self.call = kwargs
            return httpx.Response(
                200,
                headers={
                    "content-type": "image/jpeg",
                    "content-length": "11",
                    "x-frame-width": "1920",
                },
                content=b"frame-bytes",
                request=httpx.Request("GET", kwargs["url"]),
            )

    async def scenario():
        proxy_client = FakeProxyClient()
        app = SimpleNamespace(
            state=SimpleNamespace(proxy_client=proxy_client),
        )
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/aivision/cameras/cam/frame.jpg",
                "raw_path": b"/api/aivision/cameras/cam/frame.jpg",
                "query_string": b"quality=72",
                "headers": [
                    (b"cookie", b"session=test"),
                    (b"transfer-encoding", b"chunked"),
                ],
                "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 5000),
                "app": app,
            },
            receive=receive,
        )

        response = await _proxy(
            request,
            "http://127.0.0.1:7862",
            "/api/aivision/cameras/cam/frame.jpg",
        )

        assert isinstance(response, StreamingResponse)
        assert response.status_code == 200
        assert response.headers["x-frame-width"] == "1920"
        assert "content-length" not in response.headers
        chunks = [chunk async for chunk in response.body_iterator]
        assert b"".join(chunks) == b"frame-bytes"
        assert proxy_client.call == {
            "method": "GET",
            "url": (
                "http://127.0.0.1:7862/"
                "api/aivision/cameras/cam/frame.jpg?quality=72"
            ),
            "body": b"",
            "headers": {"cookie": "session=test"},
        }

    def reject_sync_request(**_kwargs):
        raise AssertionError("同步 requests.request 不应由异步代理调用")

    monkeypatch.setattr("unified_backend.app.requests.request", reject_sync_request)
    asyncio.run(scenario())
