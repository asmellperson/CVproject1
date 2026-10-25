"""单路 MSE 代理的授权、协议隔离与连接回收回归。"""
import asyncio
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState


MIME = 'video/mp4; codecs="avc1.640029"'
HANDSHAKE = {"type": "mse", "value": "avc1.640029,mp4a.40.2"}
WS_PATH = "/ws/cameras/camera_1/preview?feature=security_fence"


@pytest.fixture
def preview(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "tests", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "tests", "DATA_PATH": str(tmp_path), "AUTH_SECRET": "preview-test-secret-" * 3,
        "AUTH_TOKEN_EXPIRE_HOURS": "1",
    }.items():
        monkeypatch.setenv(name, value)
    from auth import auth
    from AiVision.api.routes import preview_stream as module
    from AiVision.departments.service import department_service

    record = {"employee_id": "preview-test", "name": "测试账号", "role": "viewer",
              "departments": ["general_electric"], "auth_version": 1, "enabled": True}
    assignments = {"general_electric": ["security_fence"], "electronics_electrician": ["security_fence"]}
    monkeypatch.setattr(auth, "get_user_store", lambda: SimpleNamespace(get_user_record=lambda key: record))
    monkeypatch.setattr(department_service, "feature_access", lambda: assignments)
    monkeypatch.setattr(module.settings.preview, "camera_key", "camera_1")
    monkeypatch.setattr(module.settings.preview, "feature", "security_fence")
    monkeypatch.setattr(module.settings.preview, "auth_check_seconds", 0.02)
    monkeypatch.setattr(module.settings.api, "cors_origins", ["*"])
    sources = {
        "camera_1": {"camera_id": 1, "shm_name": "camera_1", "department": "general_electric",
                     "url": "rtsp://camera.invalid/live", "enabled": True},
        "camera_2": {"camera_id": 2, "shm_name": "camera_2", "department": "general_electric",
                     "url": "rtsp://camera.invalid/other", "enabled": True},
    }
    source_reads = []

    def read_source(key):
        source_reads.append(key)
        source = sources.get("camera_1" if key == "入口" else key)
        return dict(source) if source else None

    manager = SimpleNamespace(get_camera_preview_source=read_source)
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[module.get_camera_config_manager] = lambda: manager
    upstream = SimpleNamespace(sent=[], closed=threading.Event(), cancelled=threading.Event(), urls=[])
    upstream.aborted = threading.Event()
    upstream.transport = SimpleNamespace(abort=upstream.aborted.set)
    upstream.messages = [json.dumps({"type": "mse", "value": MIME}), b"fmp4-fixture"]

    async def receive_upstream():
        if upstream.messages:
            message = upstream.messages.pop(0)
            if isinstance(message, BaseException):
                raise message
            return message
        try:
            await asyncio.Future()
        finally:
            upstream.cancelled.set()

    async def send_upstream(message):
        upstream.sent.append(json.loads(message))

    upstream.recv = receive_upstream
    upstream.send = send_upstream

    @asynccontextmanager
    async def connect(url, **kwargs):
        upstream.urls.append(url)
        assert kwargs["proxy"] is None
        try:
            yield upstream
        finally:
            upstream.closed.set()

    registrations = []

    def register(request):
        registrations.append(request)
        return module.httpx.Response(200)

    client_factory = module.httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client_factory(
        transport=module.httpx.MockTransport(register), **kwargs,
    ))
    monkeypatch.setattr(module, "connect", connect)
    client = TestClient(app)
    client.cookies.set(auth.COOKIE_NAME, auth.create_token(record))
    yield SimpleNamespace(
        client=client, module=module, auth=auth, record=record, assignments=assignments,
        sources=sources, source_reads=source_reads, upstream=upstream, registrations=registrations,
        manager=manager, monkeypatch=monkeypatch, real_httpx_client=client_factory,
    )
    client.close()


def test_capability_is_canonical_and_never_exposes_source(preview):
    response = preview.client.get("/api/cameras/入口/preview", params={"feature": "security_fence"})
    assert response.status_code == 200
    assert response.json() == {"enabled": True, "mode": "mse", "url": WS_PATH, "raw": True}
    assert preview.source_reads == ["入口"]
    assert "rtsp" not in response.text and "127.0.0.1" not in response.text


@pytest.fixture
def multiple_preview(preview):
    preview.monkeypatch.setattr(preview.module.settings.preview, "camera_key", "camera_1,camera_2")
    preview.monkeypatch.setattr(preview.module.settings.preview, "feature", "security_fence,guard_behavior")
    preview.assignments["general_electric"] = ["security_fence", "guard_behavior", "security_inspection"]
    preview.sources["camera_3"] = {
        "camera_id": 3, "shm_name": "camera_3", "department": "general_electric",
        "url": "rtsp://camera.invalid/outside-list", "enabled": True,
    }
    return preview


@pytest.mark.parametrize("key", ["camera_1", "camera_2"])
@pytest.mark.parametrize("feature", ["security_fence", "guard_behavior"])
def test_capability_enables_each_listed_camera_and_feature(multiple_preview, key, feature):
    response = multiple_preview.client.get(f"/api/cameras/{key}/preview", params={"feature": feature})
    assert response.status_code == 200
    assert response.json() == {
        "enabled": True, "mode": "mse", "url": f"/ws/cameras/{key}/preview?feature={feature}", "raw": True,
    }


@pytest.mark.parametrize("key", ["camera_1", "camera_2"])
@pytest.mark.parametrize("feature", ["security_fence", "guard_behavior"])
def test_websocket_registers_each_listed_camera_with_its_own_source(multiple_preview, key, feature):
    preview = multiple_preview
    with preview.client.websocket_connect(
        f"/ws/cameras/{key}/preview?feature={feature}", headers={"origin": "http://testserver"},
    ) as websocket:
        websocket.send_json(HANDSHAKE)
        assert websocket.receive_json() == {"type": "mse", "value": MIME}
        assert websocket.receive_bytes() == b"fmp4-fixture"
    assert preview.upstream.closed.wait(1)
    assert dict(preview.registrations[0].url.params) == {
        "name": f"fuda_preview_camera_{preview.sources[key]['camera_id']}", "src": preview.sources[key]["url"],
    }


@pytest.mark.parametrize("key, feature", [
    ("camera_3", "security_fence"), ("camera_1", "security_inspection"),
])
def test_nonlisted_camera_or_feature_remains_jpeg_and_cannot_open_stream(multiple_preview, key, feature):
    preview = multiple_preview
    response = preview.client.get(f"/api/cameras/{key}/preview", params={"feature": feature})
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "mode": "jpeg", "url": None, "raw": True}
    with preview.client.websocket_connect(
        f"/ws/cameras/{key}/preview?feature={feature}", headers={"origin": "http://testserver"},
    ) as websocket:
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1008
    assert not preview.registrations


@pytest.mark.parametrize("denied", ["department", "feature"])
def test_multiple_camera_lists_do_not_replace_individual_access_checks(multiple_preview, denied):
    preview = multiple_preview
    key, feature = "camera_2", "guard_behavior"
    if denied == "department":
        preview.sources[key]["department"] = "electronics_electrician"
        preview.assignments["electronics_electrician"] = [feature]
    else:
        preview.assignments["general_electric"] = ["security_fence"]
    response = preview.client.get(f"/api/cameras/{key}/preview", params={"feature": feature})
    assert response.status_code == 403
    with preview.client.websocket_connect(
        f"/ws/cameras/{key}/preview?feature={feature}", headers={"origin": "http://testserver"},
    ) as websocket:
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1008
    assert not preview.registrations


def test_empty_camera_list_disables_all_configured_features(multiple_preview):
    preview = multiple_preview
    preview.monkeypatch.setattr(preview.module.settings.preview, "camera_key", "")
    for key, feature in [("camera_1", "security_fence"), ("camera_2", "guard_behavior")]:
        response = preview.client.get(f"/api/cameras/{key}/preview", params={"feature": feature})
        assert response.status_code == 200
        assert response.json()["enabled"] is False


def test_unknown_feature_is_still_rejected_at_request_time(multiple_preview):
    preview = multiple_preview
    preview.monkeypatch.setattr(preview.module.settings.preview, "feature", "not_registered")
    preview.assignments["general_electric"].append("not_registered")
    response = preview.client.get("/api/cameras/camera_1/preview?feature=not_registered")
    assert response.status_code == 404
    assert not preview.registrations


@pytest.mark.parametrize("change", ["other_camera", "feature", "disabled", "non_rtsp", "pilot_off"])
def test_capability_keeps_jpeg_outside_enabled_pilot(preview, change):
    key, feature = "camera_1", "security_fence"
    if change == "other_camera":
        key = "camera_2"
    elif change == "feature":
        feature = None
    elif change == "disabled":
        preview.sources[key]["enabled"] = False
    elif change == "non_rtsp":
        preview.sources[key]["url"] = "file:///camera.mp4"
    else:
        preview.monkeypatch.setattr(preview.module.settings.preview, "camera_key", "")
    response = preview.client.get(f"/api/cameras/{key}/preview", params={"feature": feature} if feature else {})
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "mode": "jpeg", "url": None, "raw": True}


@pytest.mark.parametrize("failure, expected", [("login", 401), ("department", 403), ("feature", 403), ("missing", 404)])
def test_http_capability_keeps_camera_and_feature_permissions(preview, failure, expected):
    key = "camera_1"
    if failure == "login":
        preview.client.cookies.clear()
    elif failure == "department":
        preview.record["departments"] = []
    elif failure == "feature":
        preview.assignments["general_electric"] = []
    else:
        key = "missing"
    response = preview.client.get(f"/api/cameras/{key}/preview?feature=security_fence")
    assert response.status_code == expected
    assert not preview.registrations


def test_mse_registers_database_source_and_only_relays_mime_and_media(preview):
    preview.upstream.messages.insert(0, json.dumps({"type": "debug", "value": preview.sources["camera_1"]["url"]}))
    with preview.client.websocket_connect(WS_PATH, headers={"origin": "http://testserver"}) as websocket:
        websocket.send_json(HANDSHAKE)
        assert websocket.receive_json() == {"type": "mse", "value": MIME}
        assert websocket.receive_bytes() == b"fmp4-fixture"
        assert preview.upstream.sent == [HANDSHAKE]
    assert preview.upstream.closed.wait(1)
    assert preview.upstream.cancelled.is_set()
    assert preview.upstream.aborted.is_set()
    request = preview.registrations[0]
    assert request.method == "PATCH"
    assert str(request.url.copy_with(query=None)) == "http://127.0.0.1:1984/api/streams"
    assert dict(request.url.params) == {"name": "fuda_preview_camera_1", "src": "rtsp://camera.invalid/live"}
    assert preview.upstream.urls == ["ws://127.0.0.1:1984/api/ws?src=fuda_preview_camera_1"]


@pytest.mark.parametrize("failure", ["login", "department", "feature", "disabled", "other_camera", "origin", "src"])
def test_websocket_checks_its_own_authentication_and_pilot_gate(preview, failure):
    path, origin = WS_PATH, "http://testserver"
    if failure == "login":
        preview.client.cookies.clear()
    elif failure == "department":
        preview.record["departments"] = []
    elif failure == "feature":
        preview.assignments["general_electric"] = []
    elif failure == "disabled":
        preview.sources["camera_1"]["enabled"] = False
    elif failure == "other_camera":
        path = path.replace("camera_1", "camera_2")
    elif failure == "origin":
        origin = "https://cross-site.invalid"
    else:
        path += "&src=rtsp://attacker.invalid/live"
    with preview.client.websocket_connect(path, headers={"origin": origin}) as websocket:
        with pytest.raises(WebSocketDisconnect) as failure_info:
            websocket.receive_json()
    assert failure_info.value.code == 1008
    assert not preview.registrations


@pytest.mark.parametrize("handshake", [
    {"type": "webrtc/offer", "value": "x"}, {"type": "mse", "value": "rtsp://attacker.invalid/live"},
    {"type": "mse", "value": "avc1.640029", "src": "camera_2"}, {"type": "mse", "value": "x" * 2048},
])
def test_only_one_bounded_codec_handshake_can_reach_go2rtc(preview, handshake):
    with preview.client.websocket_connect(WS_PATH, headers={"origin": "http://testserver"}) as websocket:
        websocket.send_json(handshake)
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1008
    assert not preview.registrations


def test_client_cannot_send_additional_media_commands(preview):
    with preview.client.websocket_connect(WS_PATH, headers={"origin": "http://testserver"}) as websocket:
        websocket.send_json(HANDSHAKE)
        websocket.receive_json()
        websocket.receive_bytes()
        websocket.send_json({"type": "mse", "value": "hvc1.1.6.L153.B0"})
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1008
    assert preview.upstream.sent == [HANDSHAKE]
    assert preview.upstream.closed.wait(1)


@pytest.mark.parametrize("change", ["disabled", "department", "feature", "source", "account", "version", "expiry"])
def test_live_connection_rechecks_authentication_and_source(preview, change):
    with preview.client.websocket_connect(WS_PATH, headers={"origin": "http://testserver"}) as websocket:
        websocket.send_json(HANDSHAKE)
        websocket.receive_json()
        websocket.receive_bytes()
        if change == "disabled":
            preview.sources["camera_1"]["enabled"] = False
        elif change == "department":
            preview.sources["camera_1"]["department"] = "electronics_electrician"
        elif change == "feature":
            preview.assignments["general_electric"] = []
        elif change == "source":
            preview.sources["camera_1"]["url"] = "rtsp://camera.invalid/reconfigured"
        elif change == "account":
            preview.record["enabled"] = False
        elif change == "version":
            preview.record["auth_version"] += 1
        else:
            current = time.time()
            preview.monkeypatch.setattr(preview.auth.time, "time", lambda: current + 7200)
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1008
    assert preview.upstream.closed.wait(1)
    assert preview.upstream.cancelled.is_set()


@pytest.mark.parametrize("phase", ["receive", "send", "announcement"])
def test_ready_frame_cancellation_cannot_be_swallowed_and_continue_relaying(preview, phase):
    async def scenario():
        stop_event = asyncio.Event()
        task = None

        class Upstream:
            reads = 0

            async def recv(self):
                self.reads += 1
                if self.reads == 1:
                    return json.dumps({"type": "mse", "value": MIME})
                if self.reads == 2:
                    if phase == "receive":
                        asyncio.get_running_loop().call_soon(task.cancel)
                    return b"frame"
                # 旧实现会吞掉同拍取消并进入这里；保留阻塞点便于测试超时后清理。
                await asyncio.Future()

        class Socket:
            async def send_json(self, message):
                if phase == "announcement":
                    asyncio.get_running_loop().call_soon(task.cancel)

            async def send_bytes(self, message):
                if phase == "send":
                    asyncio.get_running_loop().call_soon(task.cancel)

        upstream = Upstream()
        task = asyncio.create_task(preview.module._relay_media(Socket(), upstream, stop_event))
        try:
            done, _ = await asyncio.wait({task}, timeout=0.2)
            assert task in done, "帧读写恰好完成时也必须响应取消，不能继续无限转发"
            assert task.cancelled()
            assert upstream.reads == (1 if phase == "announcement" else 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_stop_signal_blocks_frame_that_arrives_after_authorization_ends(preview):
    async def scenario():
        stop_event = asyncio.Event()
        sent = []

        class Upstream:
            reads = 0

            async def recv(self):
                self.reads += 1
                if self.reads == 1:
                    return json.dumps({"type": "mse", "value": MIME})
                stop_event.set()
                return b"frame-after-revocation"

        class Socket:
            async def send_json(self, message):
                sent.append(message)

            async def send_bytes(self, message):
                sent.append(message)

        await preview.module._relay_media(Socket(), Upstream(), stop_event)
        assert sent == [{"type": "mse", "value": MIME}]

    asyncio.run(scenario())


def test_policy_failure_closes_browser_before_bounded_upstream_cleanup(preview):
    async def scenario():
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        exited, browser_closed = asyncio.Event(), asyncio.Event()

        class Socket:
            application_state = WebSocketState.CONNECTED
            client_state = WebSocketState.CONNECTED
            close_codes = []

            async def receive(self):
                await asyncio.Future()

            async def close(self, code):
                self.close_codes.append(code)
                self.application_state = WebSocketState.DISCONNECTED
                browser_closed.set()

        async def blocked_cleanup(websocket, source, handshake, stop_event):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                try:
                    cleaning.set()
                    await release.wait()
                finally:
                    exited.set()

        async def reject_authorization(*args):
            await entered.wait()
            raise preview.module.PreviewPolicyError()

        preview.monkeypatch.setattr(preview.module, "_CLEANUP_TIMEOUT_SECONDS", 0.03)
        preview.monkeypatch.setattr(preview.module, "_stream_media", blocked_cleanup)
        preview.monkeypatch.setattr(preview.module, "_reauthorize", reject_authorization)
        websocket = Socket()
        task = asyncio.create_task(preview.module._relay_session(
            websocket, preview.manager, "camera_1", "security_fence", preview.sources["camera_1"], HANDSHAKE,
        ))
        close_wait = asyncio.create_task(browser_closed.wait())
        try:
            done, _ = await asyncio.wait({close_wait}, timeout=0.2)
            assert close_wait in done and websocket.close_codes == [1008]
            assert not release.is_set(), "关闭浏览器不能等待上游清理结束"
            done, _ = await asyncio.wait({task}, timeout=0.3)
            assert task in done, "清理超时必须结束 ASGI 会话，不能永久等待 gather"
            with pytest.raises(preview.module.PreviewPolicyError):
                task.result()
            await asyncio.sleep(0)
            assert cleaning.is_set() and exited.is_set()
        finally:
            release.set()
            task.cancel()
            close_wait.cancel()
            await asyncio.gather(task, close_wait, return_exceptions=True)

    asyncio.run(scenario())


def test_three_concurrent_streams_each_close_on_revocation_and_release_upstream(preview):
    async def scenario():
        revoked = False
        upstream_closed, upstream_aborted = set(), set()
        sources = {
            f"camera_{index}": {**preview.sources["camera_1"], "camera_id": index, "shm_name": f"camera_{index}"}
            for index in (1, 2, 3)
        }

        class Socket:
            application_state = WebSocketState.CONNECTED
            client_state = WebSocketState.CONNECTED

            def __init__(self):
                self.ready = asyncio.Event()
                self.close_codes = []

            async def send_json(self, message):
                pass

            async def send_bytes(self, message):
                self.ready.set()

            async def receive(self):
                await asyncio.Future()

            async def close(self, code):
                self.close_codes.append(code)
                self.application_state = WebSocketState.DISCONNECTED

        class Upstream:
            def __init__(self, key):
                self.reads = 0
                self.transport = SimpleNamespace(abort=lambda: upstream_aborted.add(key))

            async def send(self, message):
                pass

            async def recv(self):
                self.reads += 1
                if self.reads == 1:
                    return json.dumps({"type": "mse", "value": MIME})
                await asyncio.sleep(0.001)
                return b"frame"

        @asynccontextmanager
        async def connect_stream(url, **kwargs):
            key = url.rsplit("/", 1)[-1]
            try:
                yield Upstream(key)
            finally:
                upstream_closed.add(key)

        async def register(source):
            return f"ws://fixture/{source['shm_name']}", source["shm_name"]

        async def authorize(websocket, manager, key, feature):
            if revoked:
                raise preview.module.HTTPException(403, "feature permission required")
            return dict(sources[key])

        preview.monkeypatch.setattr(preview.module, "connect", connect_stream)
        preview.monkeypatch.setattr(preview.module, "_register_source", register)
        preview.monkeypatch.setattr(preview.module, "_authorized_source", authorize)
        sockets = {key: Socket() for key in sources}
        tasks = [asyncio.create_task(preview.module._relay_session(
            sockets[key], preview.manager, key, "security_fence", source, HANDSHAKE,
        )) for key, source in sources.items()]
        ready_tasks = [asyncio.create_task(socket.ready.wait()) for socket in sockets.values()]
        try:
            ready, _ = await asyncio.wait(ready_tasks, timeout=0.5)
            assert len(ready) == 3
            revoked = True
            done, _ = await asyncio.wait(tasks, timeout=0.5)
            assert len(done) == 3, "一条连接关闭不能取消或遗失其他两路的权限复查"
            for task in done:
                assert isinstance(task.exception(), preview.module.HTTPException)
            assert all(socket.close_codes == [1008] for socket in sockets.values())
            assert upstream_closed == set(sources)
            assert upstream_aborted == set(sources)
        finally:
            for task in tasks + ready_tasks:
                task.cancel()
            await asyncio.gather(*tasks, *ready_tasks, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("blocked_read", ["user", "camera"])
def test_blocked_authorization_read_closes_live_stream_without_waiting_for_thread(preview, blocked_read):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    preview.monkeypatch.setattr(preview.module, "_AUTH_CHECK_TIMEOUT_SECONDS", 0.05)
    if blocked_read == "user":
        target, attribute = preview.module, "get_current_user_from_request"
    else:
        target, attribute = preview.manager, "get_camera_preview_source"
    original = getattr(target, attribute)

    def blocked(*args):
        entered.set()
        try:
            release.wait()
            return original(*args)
        finally:
            finished.set()

    try:
        with preview.client.websocket_connect(WS_PATH, headers={"origin": "http://testserver"}) as websocket:
            websocket.send_json(HANDSHAKE)
            websocket.receive_json()
            websocket.receive_bytes()
            preview.monkeypatch.setattr(target, attribute, blocked)
            assert entered.wait(1), "持续授权检查应进入被阻塞的读取"
            with pytest.raises(WebSocketDisconnect) as error:
                websocket.receive_json()
            assert error.value.code == 1008
            assert not release.is_set(), "不能等待数据库或用户查询恢复后才停止媒体"
        assert preview.upstream.closed.wait(1)
        assert preview.upstream.cancelled.is_set()
    finally:
        # 即使断言失败，也释放本测试的同步读取线程，不把阻塞带到其他回归。
        release.set()
        if entered.is_set():
            assert finished.wait(1)


def test_authorization_timeout_uses_builtin_exception_on_python310(preview):
    class LegacyAsyncioTimeout(Exception):
        pass

    async def blocked_read(*args, **kwargs):
        await asyncio.Future()

    # Python 3.10 中 asyncio.TimeoutError 与 AnyIO 抛出的内建 TimeoutError 不同。
    preview.monkeypatch.setattr(preview.module.asyncio, "TimeoutError", LegacyAsyncioTimeout)
    preview.monkeypatch.setattr(preview.module.to_thread, "run_sync", blocked_read)
    preview.monkeypatch.setattr(preview.module, "_AUTH_CHECK_TIMEOUT_SECONDS", 0.02)

    async def scenario():
        started = asyncio.get_running_loop().time()
        with pytest.raises(preview.module.PreviewPolicyError):
            await preview.module._authorized_source(None, preview.manager, "camera_1", "security_fence")
        assert asyncio.get_running_loop().time() - started < 0.5

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["upstream_error", "malformed_mime", "registration"])
def test_upstream_errors_do_not_expose_source_details(preview, failure):
    secret_detail = preview.sources["camera_1"]["url"] + "/private-detail"
    if failure == "upstream_error":
        preview.upstream.messages = [json.dumps({"type": "error", "value": secret_detail})]
    elif failure == "malformed_mime":
        preview.upstream.messages = [json.dumps({"type": "mse", "value": secret_detail})]
    else:
        async def failed_registration(source):
            raise RuntimeError(secret_detail)
        preview.monkeypatch.setattr(preview.module, "_register_source", failed_registration)
    with preview.client.websocket_connect(WS_PATH, headers={"origin": "http://testserver"}) as websocket:
        websocket.send_json(HANDSHAKE)
        assert websocket.receive_json() == {"type": "error", "value": "视频预览暂不可用"}
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1011


def test_source_registration_logs_remove_source_but_keep_other_http_logs(preview, caplog):
    source = "rtsp://fixture-user:fixture-pass@camera.invalid/live"
    preview.sources["camera_1"]["url"] = source
    requests = []

    class SidecarHandler(BaseHTTPRequestHandler):
        def do_PATCH(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format, *args):
            logging.getLogger("preview-test-sidecar").debug("本机测试媒体源已接收")

    server = HTTPServer(("127.0.0.1", 0), SidecarHandler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    preview.monkeypatch.setattr(preview.module.httpx, "AsyncClient", preview.real_httpx_client)
    preview.monkeypatch.setattr(preview.module.settings.preview, "base_url", f"http://127.0.0.1:{server.server_port}")
    try:
        # 真实本机 HTTP 传输同时覆盖 httpx INFO 与 httpcore DEBUG，而非只检查 MockTransport。
        with caplog.at_level(logging.DEBUG, logger="httpx"), caplog.at_level(logging.DEBUG, logger="httpcore"):
            with preview.client.websocket_connect(WS_PATH, headers={"origin": "http://testserver"}) as websocket:
                websocket.send_json(HANDSHAKE)
                assert websocket.receive_json() == {"type": "mse", "value": MIME}
                websocket.receive_bytes()
            logging.getLogger("httpx").info("其他业务请求 %s", "keep-this-log")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
    assert "fixture-user" not in caplog.text and "fixture-pass" not in caplog.text
    assert "camera.invalid" not in caplog.text and "rtsp" not in caplog.text
    assert "fuda_preview_camera_1" in caplog.text
    assert "keep-this-log" in caplog.text
    assert preview.module.httpx.URL(requests[0]).params["src"] == source


def test_disconnect_cancels_pending_sidecar_registration(preview):
    entered, cancelled = threading.Event(), threading.Event()

    async def blocked_registration(source):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    preview.monkeypatch.setattr(preview.module, "_register_source", blocked_registration)
    with preview.client.websocket_connect(WS_PATH, headers={"origin": "http://testserver"}) as websocket:
        websocket.send_json(HANDSHAKE)
        assert entered.wait(1)
    assert cancelled.wait(1)
    assert not preview.upstream.urls


def test_websocket_origin_accepts_explicit_frontend_origin(preview):
    preview.monkeypatch.setattr(preview.module.settings.api, "cors_origins", ["https://frontend.invalid"])
    with preview.client.websocket_connect(WS_PATH, headers={"origin": "https://frontend.invalid"}) as websocket:
        websocket.send_json(HANDSHAKE)
        assert websocket.receive_json()["type"] == "mse"


def test_handshake_timeout_does_not_open_upstream(preview):
    preview.monkeypatch.setattr(preview.module, "_CONNECT_TIMEOUT_SECONDS", 0.02)
    with preview.client.websocket_connect(WS_PATH, headers={"origin": "http://testserver"}) as websocket:
        assert websocket.receive_json() == {"type": "error", "value": "视频预览暂不可用"}
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1011
    assert not preview.registrations
    assert not preview.upstream.urls


def test_upstream_idle_timeout_closes_both_connections(preview):
    preview.monkeypatch.setattr(preview.module, "_IDLE_TIMEOUT_SECONDS", 0.03)
    with preview.client.websocket_connect(WS_PATH, headers={"origin": "http://testserver"}) as websocket:
        websocket.send_json(HANDSHAKE)
        websocket.receive_json()
        websocket.receive_bytes()
        assert websocket.receive_json() == {"type": "error", "value": "视频预览暂不可用"}
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1011
    assert preview.upstream.closed.wait(1)
    assert preview.upstream.cancelled.is_set()


def test_internal_source_lookup_reads_only_current_camera_table(preview):
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from AiVision.cameras import config_manager
    from AiVision.cameras.orm import AiCameraConfig

    # 只建主表，任何意外的功能查询都会直接失败，SQL 计数同时约束高频规范 key。
    engine = create_engine("sqlite://")
    AiCameraConfig.__table__.create(engine)
    factory = sessionmaker(engine)
    preview.monkeypatch.setattr(config_manager, "get_session", factory)
    with factory.begin() as session:
        session.add(AiCameraConfig(
            id=1, name="入口", shm_name="camera_1", url="rtsps://camera.invalid/live",
            department="general_electric", enable=True,
        ))
    reads = []

    @event.listens_for(engine, "before_cursor_execute")
    def count_selects(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    manager = config_manager.CameraConfigManager()
    try:
        assert manager.get_camera_preview_source("camera_1") == {
            "camera_id": 1, "shm_name": "camera_1", "department": "general_electric",
            "url": "rtsps://camera.invalid/live", "enabled": True,
        }
        assert len(reads) == 1
        with factory.begin() as session:
            source = session.get(AiCameraConfig, 1)
            source.enable = False
            source.url = "rtsp://camera.invalid/reconfigured"
        reads.clear()
        result = manager.get_camera_preview_source("camera_1")
        assert result["enabled"] is False and result["url"] == "rtsp://camera.invalid/reconfigured"
        assert len(reads) == 1
        assert manager.get_camera_preview_source("missing") is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("camera_keys, features, expected_keys, expected_features", [
    ("camera_1", "security_fence", frozenset({"camera_1"}), frozenset({"security_fence"})),
    (" camera_1 , camera_2 , camera_1 ", " security_fence , guard_behavior , security_fence ",
     frozenset({"camera_1", "camera_2"}), frozenset({"security_fence", "guard_behavior"})),
    ("  ", "security_fence,guard_behavior", frozenset(), frozenset({"security_fence", "guard_behavior"})),
])
def test_preview_settings_normalize_single_and_multiple_allowlists(
    preview, camera_keys, features, expected_keys, expected_features,
):
    from AiVision.core.settings import PreviewSettings
    config = PreviewSettings(GO2RTC_PREVIEW_CAMERA_KEY=camera_keys, GO2RTC_PREVIEW_FEATURE=features)
    assert config.camera_keys == expected_keys
    assert config.features == expected_features
    assert isinstance(config.camera_keys, frozenset) and isinstance(config.features, frozenset)
    assert " " not in config.camera_key and " " not in config.feature
    assert len(config.camera_key.split(",")) == len(expected_keys) if expected_keys else config.camera_key == ""
    assert len(config.feature.split(",")) == len(expected_features)


@pytest.mark.parametrize("field, value", [
    ("GO2RTC_PREVIEW_CAMERA_KEY", "camera_0"),
    ("GO2RTC_PREVIEW_CAMERA_KEY", "camera_01"),
    ("GO2RTC_PREVIEW_CAMERA_KEY", "1"),
    ("GO2RTC_PREVIEW_CAMERA_KEY", "camera_1,,camera_2"),
    ("GO2RTC_PREVIEW_CAMERA_KEY", "camera_1,"),
    ("GO2RTC_PREVIEW_CAMERA_KEY", "camera_1, ,camera_2"),
    ("GO2RTC_PREVIEW_FEATURE", " "),
    ("GO2RTC_PREVIEW_FEATURE", "security_fence,,guard_behavior"),
    ("GO2RTC_PREVIEW_FEATURE", "security_fence,"),
    ("GO2RTC_PREVIEW_FEATURE", "security-fence"),
    ("GO2RTC_PREVIEW_FEATURE", "SecurityFence"),
])
def test_preview_settings_reject_invalid_or_empty_allowlist_items(preview, field, value):
    from AiVision.core.settings import PreviewSettings
    with pytest.raises(ValidationError):
        PreviewSettings(**{field: value})


@pytest.mark.parametrize("url", ["http://outside.invalid:1984", "https://127.0.0.1:1984", "http://127.0.0.1:1984/api"])
def test_preview_settings_reject_non_loopback_media_services(preview, url):
    from AiVision.core.settings import PreviewSettings
    with pytest.raises(ValidationError):
        PreviewSettings(GO2RTC_BASE_URL=url)


def test_real_app_registers_http_and_websocket_preview_routes(preview):
    from AiVision.api.app import create_app
    paths = {route.path for route in create_app().routes}
    assert "/api/cameras/{key}/preview" in paths
    assert "/ws/cameras/{key}/preview" in paths
