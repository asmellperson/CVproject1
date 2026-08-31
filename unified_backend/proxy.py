# 文件说明：实现请求代理相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：实现 `_positive_int_from_env` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `default`（int）：`default` 对应的业务输入值
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/proxy.py` 的 `ProxySettings::from_env` 调用本符号
#   - 内部调用：`os.getenv`、`int`、`ValueError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return value


# 功能：实现 `_positive_float_from_env` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `default`（float）：`default` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/proxy.py` 的 `ProxySettings::from_env` 调用本符号
#   - 内部调用：`os.getenv`、`float`、`ValueError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _positive_float_from_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return value


# 功能：定义 `ProxySettings` 类，封装请求代理相关的状态、约束与操作
# 参数：
#   - `max_connections`（int）：`max_connections` 对应的业务输入值
#   - `max_keepalive_connections`（int）：`max_keepalive_connections` 对应的业务输入值
#   - `connect_timeout_seconds`（float）：`connect_timeout_seconds` 对应的时间间隔或时长
#   - `pool_timeout_seconds`（float）：`pool_timeout_seconds` 对应的时间间隔或时长
#   - `write_timeout_seconds`（float）：`write_timeout_seconds` 对应的时间间隔或时长
#   - `read_timeout_seconds`（float）：`read_timeout_seconds` 对应的时间间隔或时长
# 返回：ProxySettings；返回新建的 `ProxySettings` 实例。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_async_proxy.py` 的 `_settings` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class ProxySettings:
    max_connections: int = 512
    max_keepalive_connections: int = 128
    connect_timeout_seconds: float = 3.0
    pool_timeout_seconds: float = 2.0
    write_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 10.0

    # 功能：实现 `from_env` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    # 返回：'ProxySettings'；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`unified_backend/tests/test_async_proxy.py` 的 `test_proxy_settings_read_environment` 调用本符号；`unified_backend/app.py` 的
    #         `create_app::lifespan` 调用本符号
    #   - 内部调用：`cls`、`_positive_int_from_env`、`_positive_float_from_env`、`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：可映射为网关 HTTP 状态码的上游请求错误；输入与输出详见下方说明
# 参数：
#   - `status_code`（int）：`status_code` 对应的业务输入值
#   - `detail`（str）：`detail` 对应的业务输入值
# 返回：ProxyRequestError；返回新建的 `ProxyRequestError` 实例。
# 调用关系：
#   - 调用方：`unified_backend/proxy.py` 的 `AsyncProxyClient::send` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ProxyRequestError(RuntimeError):
    """可映射为网关 HTTP 状态码的上游请求错误。"""

    # 功能：初始化或配置 `__init__` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `status_code`（int）：`status_code` 对应的业务输入值
    #   - `detail`（str）：`detail` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().__init__`、`super`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# 功能：实现 `filtered_response_headers` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `headers`（Mapping[str, str]）：`headers` 对应的业务输入值
# 返回：dict[str, str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_async_proxy.py` 的 `test_filtered_response_headers_remove_connection_specific_values`
#         调用本符号；`unified_backend/app.py` 的 `_proxy` 调用本符号
#   - 内部调用：`headers.items`、`key.lower`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def filtered_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in _EXCLUDED_RESPONSE_HEADERS
    }


# 功能：实现 `stream_response_bytes` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `response`（httpx.Response）：待读取或更新的 HTTP 响应
# 返回：AsyncIterator[bytes]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_async_proxy.py` 的
#         `test_stream_response_closes_upstream_when_downstream_stops_consuming::scenario` 调用本符号；`unified_backend/app.py` 的 `_proxy`
#         调用本符号
#   - 内部调用：`response.aiter_bytes`、`response.aclose`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
async def stream_response_bytes(response: httpx.Response) -> AsyncIterator[bytes]:
    try:
        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
            if chunk:
                yield chunk
    finally:
        await response.aclose()


# 功能：复用连接池并异步流式访问算法子服务；输入与输出详见下方说明
# 参数：
#   - `settings`（ProxySettings）：应用配置集合
#   - `transport`（httpx.AsyncBaseTransport | None）：`transport` 对应的业务输入值；默认值为 `None`
# 返回：AsyncProxyClient；返回新建的 `AsyncProxyClient` 实例。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_async_proxy.py` 的 `test_fifty_viewers_at_five_fps_do_not_block_event_loop::scenario`
#         实例化本符号；`unified_backend/tests/test_async_proxy.py` 的 `test_proxy_maps_upstream_failures::scenario`
#         实例化本符号；`unified_backend/app.py` 的 `create_app::lifespan` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AsyncProxyClient:
    """复用连接池并异步流式访问算法子服务。"""

    # 功能：初始化或配置 `__init__` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `settings`（ProxySettings）：应用配置集合
    #   - `transport`（httpx.AsyncBaseTransport | None）：`transport` 对应的业务输入值；默认值为 `None`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`httpx.AsyncClient`、`httpx.Timeout`、`httpx.Limits`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能发起网络请求或发送外部消息。
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

    # 功能：发送或分发 `send` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `method`（str）：`method` 对应的业务输入值
    #   - `url`（str）：目标接口、媒体流或页面地址
    #   - `body`（bytes）：`body` 对应的业务输入值
    #   - `headers`（Mapping[str, str]）：`headers` 对应的业务输入值
    # 返回：httpx.Response；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._client.build_request`、`dict`、`self._client.send`、`ProxyRequestError`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；校验或执行失败时会主动抛出异常。
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

    # 功能：停止并释放 `close` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._client.aclose`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def close(self) -> None:
        await self._client.aclose()
