"""Guard Room 与 Security VLM 执行进程的异步流式客户端。"""
from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Literal
from urllib.parse import urljoin

import httpx

from core.settings import VisualWorkerSettings

VisualWorkerName = Literal["guard_room", "security_vlm"]

_EXCLUDED_RESPONSE_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "transfer-encoding",
}


class VisualWorkerRequestError(RuntimeError):
    """可映射为控制面 HTTP 状态码的执行进程请求错误。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def filtered_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in _EXCLUDED_RESPONSE_HEADERS
    }


async def stream_response_bytes(response: httpx.Response) -> AsyncIterator[bytes]:
    try:
        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
            if chunk:
                yield chunk
    finally:
        await response.aclose()


class VisualWorkerClient:
    """复用连接池访问 AiVision 管理的隔离视觉执行进程。"""

    def __init__(
        self,
        settings: VisualWorkerSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if settings.max_keepalive_connections > settings.max_connections:
            raise ValueError(
                "VISUAL_WORKER_PROXY_MAX_KEEPALIVE_CONNECTIONS "
                "不能大于 VISUAL_WORKER_PROXY_MAX_CONNECTIONS"
            )
        self._base_urls = {
            "guard_room": settings.guard_room_url.rstrip("/"),
            "security_vlm": settings.security_vlm_url.rstrip("/"),
        }
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                pool=settings.pool_timeout_seconds,
                write=settings.write_timeout_seconds,
                read=settings.read_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=settings.max_connections,
                max_keepalive_connections=settings.max_keepalive_connections,
            ),
            transport=transport,
            follow_redirects=False,
        )

    async def send(
        self,
        *,
        worker: VisualWorkerName,
        method: str,
        upstream_path: str,
        query: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        url = urljoin(
            f"{self._base_urls[worker]}/",
            upstream_path.lstrip("/"),
        )
        if query:
            url = f"{url}?{query}"
        request = self._client.build_request(
            method=method,
            url=url,
            content=body or None,
            headers=dict(headers),
        )
        try:
            return await self._client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise VisualWorkerRequestError(
                504,
                f"{worker} worker request timed out",
            ) from exc
        except httpx.RequestError as exc:
            raise VisualWorkerRequestError(
                502,
                f"{worker} worker unavailable",
            ) from exc

    async def close(self) -> None:
        await self._client.aclose()
