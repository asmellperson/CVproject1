# 文件说明：包含请求代理的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import StreamingResponse

import unified_backend.app as app_module
from unified_backend.app import _proxy
from unified_backend.proxy import (
    AsyncProxyClient,
    ProxyRequestError,
    ProxySettings,
    filtered_response_headers,
    stream_response_bytes,
)


# 功能：实现 `_settings` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：ProxySettings；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_async_proxy.py` 的 `test_fifty_viewers_at_five_fps_do_not_block_event_loop::scenario`
#         调用本符号；`unified_backend/tests/test_async_proxy.py` 的 `test_proxy_maps_upstream_failures::scenario` 调用本符号
#   - 内部调用：`ProxySettings`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _settings() -> ProxySettings:
    return ProxySettings(
        max_connections=512,
        max_keepalive_connections=128,
        connect_timeout_seconds=3.0,
        pool_timeout_seconds=2.0,
        write_timeout_seconds=10.0,
        read_timeout_seconds=10.0,
    )


# 功能：验证 `test_proxy_settings_read_environment` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setenv`、`ProxySettings.from_env`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：验证 `test_fifty_viewers_at_five_fps_do_not_block_event_loop` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`asyncio.run`、`scenario`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_fifty_viewers_at_five_fps_do_not_block_event_loop():
    # 功能：实现 `scenario` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`asyncio.Event`、`AsyncProxyClient`、`_settings`、`httpx.MockTransport`、`asyncio.create_task`、`proxy.send`、`range`、`asyncio.wait_for`、`all_entered.wait`、`asyncio.get_running_loop`
    #          等共 20 个调用。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    async def scenario():
        release = asyncio.Event()
        all_entered = asyncio.Event()
        entered = 0

        # 功能：实现 `slow_upstream` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `request`（httpx.Request）：当前 HTTP 请求及上下文
        # 返回：httpx.Response；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`all_entered.set`、`release.wait`、`httpx.Response`。
        # 副作用/注意事项：会修改全局或闭包状态；可能发起网络请求或发送外部消息。
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


# 功能：验证 `test_proxy_maps_upstream_failures` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `upstream_error`（未显式标注）：`upstream_error` 对应的业务输入值
#   - `expected_status`（未显式标注）：`expected_status` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`asyncio.run`、`scenario`、`pytest.mark.parametrize`、`httpx.ConnectError`、`httpx.ReadTimeout`、`httpx.PoolTimeout`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
@pytest.mark.parametrize(
    ("upstream_error", "expected_status"),
    [
        (httpx.ConnectError("connection refused"), 502),
        (httpx.ReadTimeout("upstream stalled"), 504),
        (httpx.PoolTimeout("connection pool exhausted"), 504),
    ],
)
def test_proxy_maps_upstream_failures(upstream_error, expected_status):
    # 功能：实现 `scenario` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`AsyncProxyClient`、`_settings`、`httpx.MockTransport`、`pytest.raises`、`proxy.send`、`proxy.close`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    async def scenario():
        # 功能：实现 `failing_upstream` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `request`（httpx.Request）：当前 HTTP 请求及上下文
        # 返回：httpx.Response；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：验证 `test_filtered_response_headers_remove_connection_specific_values` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`httpx.Headers`、`filtered_response_headers`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
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


# 功能：验证 `test_stream_response_closes_upstream_when_downstream_stops_consuming` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`asyncio.run`、`scenario`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_stream_response_closes_upstream_when_downstream_stops_consuming():
    # 功能：定义 `FakeStreamingResponse` 类，封装请求代理相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeStreamingResponse；返回新建的 `FakeStreamingResponse` 实例。
    # 调用关系：
    #   - 调用方：`unified_backend/tests/test_async_proxy.py` 的
    #         `test_stream_response_closes_upstream_when_downstream_stops_consuming::scenario` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeStreamingResponse:
        # 功能：初始化或配置 `__init__` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；初始化当前实例，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：会更新当前实例的运行状态。
        def __init__(self):
            self.closed = False

        # 功能：实现 `aiter_bytes` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `chunk_size`（未显式标注）：`chunk_size` 对应的数量或大小
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：`unified_backend/proxy.py` 的 `stream_response_bytes` 调用本符号
        #   - 内部调用：`asyncio.Event().wait`、`asyncio.Event`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        async def aiter_bytes(self, chunk_size):
            assert chunk_size == 64 * 1024
            yield b"frame"
            await asyncio.Event().wait()

        # 功能：实现 `aclose` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：`unified_backend/tests/test_async_proxy.py` 的 `test_fifty_viewers_at_five_fps_do_not_block_event_loop::scenario`
        #         调用本符号；`unified_backend/tests/test_async_proxy.py` 的
        #         `test_stream_response_closes_upstream_when_downstream_stops_consuming::scenario` 调用本符号；`unified_backend/proxy.py`
        #         的 `stream_response_bytes` 调用本符号；`unified_backend/proxy.py` 的 `AsyncProxyClient::close` 调用本符号
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：会更新当前实例的运行状态。
        async def aclose(self):
            self.closed = True

    # 功能：实现 `scenario` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`FakeStreamingResponse`、`stream_response_bytes`、`anext`、`stream.aclose`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def scenario():
        upstream = FakeStreamingResponse()
        stream = stream_response_bytes(upstream)
        assert await anext(stream) == b"frame"
        await stream.aclose()
        assert upstream.closed is True

    asyncio.run(scenario())


# 功能：验证 `test_fastapi_proxy_uses_app_scoped_async_client` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`asyncio.run`、`scenario`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_fastapi_proxy_uses_app_scoped_async_client(monkeypatch):
    # 功能：定义 `FakeProxyClient` 类，封装请求代理相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeProxyClient；返回新建的 `FakeProxyClient` 实例。
    # 调用关系：
    #   - 调用方：`unified_backend/tests/test_async_proxy.py` 的 `test_fastapi_proxy_uses_app_scoped_async_client::scenario` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeProxyClient:
        # 功能：初始化或配置 `__init__` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；初始化当前实例，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：会更新当前实例的运行状态。
        def __init__(self):
            self.call = None

        # 功能：发送或分发 `send` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`httpx.Response`、`httpx.Request`。
        # 副作用/注意事项：会更新当前实例的运行状态；可能发起网络请求或发送外部消息。
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

    # 功能：实现 `scenario` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`FakeProxyClient`、`SimpleNamespace`、`Request`、`_proxy`、`isinstance`、`b''.join`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    async def scenario():
        proxy_client = FakeProxyClient()
        app = SimpleNamespace(
            state=SimpleNamespace(proxy_client=proxy_client),
        )
        sent = False

        # 功能：实现 `receive` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：会修改全局或闭包状态。
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
                "path": "/api/cameras/cam/frame.jpg",
                "raw_path": b"/api/cameras/cam/frame.jpg",
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
            "/api/cameras/cam/frame.jpg",
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
                "api/cameras/cam/frame.jpg?quality=72"
            ),
            "body": b"",
            "headers": {"cookie": "session=test"},
        }

    # 功能：实现 `reject_sync_request` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `**_kwargs`（未显式标注）：`_kwargs` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`AssertionError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def reject_sync_request(**_kwargs):
        raise AssertionError("同步 requests.request 不应由异步代理调用")

    monkeypatch.setattr("unified_backend.app.requests.request", reject_sync_request)
    asyncio.run(scenario())


# 功能：验证 `test_visual_and_root_routes_target_aivision_control_plane` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setenv`、`str`、`monkeypatch.setattr`、`app_module.create_app`、`object`、`asyncio.run`、`scenario`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_visual_and_root_routes_target_aivision_control_plane(monkeypatch, tmp_path):
    calls = []

    # 功能：实现 `fake_proxy` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `request`（未显式标注）：当前 HTTP 请求及上下文
    #   - `base_url`（未显式标注）：`base_url` 对应的业务输入值
    #   - `upstream_path`（未显式标注）：`upstream_path` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`calls.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def fake_proxy(request, base_url, upstream_path):
        calls.append((request, base_url, upstream_path))
        return {"ok": True}

    monkeypatch.setenv("UNIFIED_AIVISION_URL", "http://aivision:7862/")
    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "_proxy", fake_proxy)
    app = app_module.create_app()
    routes = {route.name: route for route in app.routes}
    request = object()

    # 功能：实现 `scenario` 对应的请求代理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def scenario():
        await routes["proxy_aivision_root_api"].endpoint("guard-behavior/sites", request)
        await routes["proxy_aivision_root_api"].endpoint(
            "security-inspection/history",
            request,
        )
        await routes["proxy_aivision_root_api"].endpoint(
            "exception-alert",
            request,
        )
        await routes["proxy_aivision_root_api"].endpoint(
            "models/yolo_human/path",
            request,
        )
        await routes["proxy_aivision_root_api"].endpoint(
            "guard-behavior/sites/12/policy", request,
        )

    asyncio.run(scenario())

    assert calls == [
        (
            request,
            "http://aivision:7862",
            "/api/guard-behavior/sites",
        ),
        (
            request,
            "http://aivision:7862",
            "/api/security-inspection/history",
        ),
        (
            request,
            "http://aivision:7862",
            "/api/exception-alert",
        ),
        (
            request,
            "http://aivision:7862",
            "/api/models/yolo_human/path",
        ),
        (request, "http://aivision:7862", "/api/guard-behavior/sites/12/policy"),
    ]

    assert "PATCH" in routes["proxy_aivision_root_api"].methods
