"""统一后端的异步上游代理客户端。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncIterator, Mapping

import httpx


_EXCLUDED_RESPONSE_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "transfer-encoding",
}


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return value


def _positive_float_from_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return value


@dataclass(frozen=True)
class ProxySettings:
    max_connections: int = 512
    max_keepalive_connections: int = 128
    connect_timeout_seconds: float = 3.0
    pool_timeout_seconds: float = 2.0
    write_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "ProxySettings":
        settings = cls(
            max_connections=_positive_int_from_env(
                "UNIFIED_PROXY_MAX_CONNECTIONS",
                cls.max_connections,
            ),
            max_keepalive_connections=_positive_int_from_env(
                "UNIFIED_PROXY_MAX_KEEPALIVE_CONNECTIONS",
                cls.max_keepalive_connections,
            ),
            connect_timeout_seconds=_positive_float_from_env(
                "UNIFIED_PROXY_CONNECT_TIMEOUT_SECONDS",
                cls.connect_timeout_seconds,
            ),
            pool_timeout_seconds=_positive_float_from_env(
                "UNIFIED_PROXY_POOL_TIMEOUT_SECONDS",
                cls.pool_timeout_seconds,
            ),
            write_timeout_seconds=_positive_float_from_env(
                "UNIFIED_PROXY_WRITE_TIMEOUT_SECONDS",
                cls.write_timeout_seconds,
            ),
            read_timeout_seconds=_positive_float_from_env(
                "UNIFIED_PROXY_READ_TIMEOUT_SECONDS",
                cls.read_timeout_seconds,
            ),
        )
        if settings.max_keepalive_connections > settings.max_connections:
            raise ValueError(
                "UNIFIED_PROXY_MAX_KEEPALIVE_CONNECTIONS "
                "不能大于 UNIFIED_PROXY_MAX_CONNECTIONS"
            )
        return settings


class ProxyRequestError(RuntimeError):
    """可映射为网关 HTTP 状态码的上游请求错误。"""

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


class AsyncProxyClient:
    """复用连接池并异步流式访问算法子服务。"""

    def __init__(
        self,
        settings: ProxySettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.settings = settings
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
        method: str,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        request = self._client.build_request(
            method=method,
            url=url,
            content=body or None,
            headers=dict(headers),
        )
        try:
            return await self._client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise ProxyRequestError(504, "upstream request timed out") from exc
        except httpx.RequestError as exc:
            raise ProxyRequestError(502, "upstream unavailable") from exc

    async def close(self) -> None:
        await self._client.aclose()
