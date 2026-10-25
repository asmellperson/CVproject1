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
from starlette.websockets import WebSocketDisconnect


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
