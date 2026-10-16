"""海康音柱的摘要认证、无声连接测试、播放结果和停止门控回归。"""
from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import pytest
import requests
from requests.adapters import HTTPAdapter
from requests.utils import parse_dict_header


DEVICE_INFO = b'<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema"><model>DS-QA6C301</model></DeviceInfo>'
CONFIG = {"id": 1, "url": "http://speaker.example.test", "username": "test-user", "password": "test-password"}


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """模块初始化仅使用测试配置，设备 HTTP 由各测试的传输替身处理。"""
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test",
        "MYSQL_DB_PASSWORD": "test", "MYSQL_DB_NAME": "test",
        "DATA_PATH": str(tmp_path), "AUTO_CREATE_DB": "false",
    }.items():
        monkeypatch.setenv(key, value)


def response_for(adapter, request, status=200, body=DEVICE_INFO, headers=None):
    """保留 requests 的实际认证钩子，仅替换底层 HTTP 传输。"""
    response = requests.Response()
    response.status_code = status
    response._content = body
    response._content_consumed = True
    response.headers.update(headers or {})
    response.encoding = "utf-8"
    response.request = request
    response.url = request.url
    response.connection = adapter
    return response


def horn():
    """通过正式设备控制器创建不立即访问网络的测试实例。"""
    from AiVision.alarms.devices.horn import Horn

    return Horn({"horn_url": CONFIG["url"], "username": CONFIG["username"],
                 "password": CONFIG["password"]}, connect_on_init=False)


def test_connection_negotiates_digest_and_never_plays(monkeypatch):
    """真实 Digest 挑战必须生成正确摘要，代理配置不能劫持局域网连接。"""
    from AiVision.alarms.devices.runtime_manager import HornRuntimeManager

    calls = []
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
        monkeypatch.setenv(key, "http://invalid-proxy.example.test")

    def send(adapter, request, **kwargs):
        calls.append(request)
        assert kwargs["proxies"] == {}
        assert kwargs["timeout"] > 0
        assert request.method == "GET"
        assert urlsplit(request.url).path == "/ISAPI/System/deviceInfo"
        assert request.body is None
        authorization = request.headers.get("Authorization")
        if not authorization:
            return response_for(adapter, request, 401, b"", {
                "WWW-Authenticate": 'Digest realm="test-speaker", nonce="test-nonce", qop="auth"',
            })
        assert authorization.startswith("Digest ")
        fields = parse_dict_header(authorization[7:])

        def digest(value):
            return hashlib.md5(value.encode()).hexdigest()

        ha1 = digest(f"{CONFIG['username']}:test-speaker:{CONFIG['password']}")
        ha2 = digest("GET:/ISAPI/System/deviceInfo")
        expected = digest(f"{ha1}:test-nonce:{fields['nc']}:{fields['cnonce']}:auth:{ha2}")
        assert fields["response"] == expected
        assert CONFIG["password"] not in authorization
        return response_for(adapter, request)

    monkeypatch.setattr(HTTPAdapter, "send", send)
    result = HornRuntimeManager().test_connection(CONFIG)
    assert result["online"] is True
    assert result["state"] == "online"
    assert result["last_error"] is None
    assert result["heartbeat_alive"] is False
    assert len(calls) == 2


def test_connection_route_returns_online_without_saving_or_playing(monkeypatch):
    """前端使用的正式连接测试路由须返回在线，并只执行设备信息读取。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth.auth import require_admin
    from AiVision.api.deps import get_horn_runtime_manager, get_horn_service
    from AiVision.api.routes.horns import router
    from AiVision.alarms.devices.runtime_manager import HornRuntimeManager

    calls = []

    def send(adapter, request, **kwargs):
        calls.append(request)
        return response_for(adapter, request)

    monkeypatch.setattr(HTTPAdapter, "send", send)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin] = lambda: {"employee_id": "test-admin", "role": "admin"}
    app.dependency_overrides[get_horn_service] = lambda: object()
    app.dependency_overrides[get_horn_runtime_manager] = lambda: HornRuntimeManager()
    with TestClient(app) as client:
        response = client.post("/api/horns/test-connection", json={
            "url": CONFIG["url"], "username": CONFIG["username"], "password": CONFIG["password"],
        })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["runtime"]["online"] is True
    assert result["runtime"]["heartbeat_alive"] is False
    assert CONFIG["password"] not in response.text
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert calls[0].url.endswith("/ISAPI/System/deviceInfo")


@pytest.mark.parametrize(("status", "message"), [
    (401, "认证未通过"), (403, "拒绝访问"), (404, "不支持所需 ISAPI 接口"),
    (405, "不支持所需 ISAPI 接口"), (302, "设备要求跳转"), (500, "HTTP 500"),
])
def test_http_failures_are_actionable_and_redirects_are_not_followed(monkeypatch, status, message):
    """错误页面和跳转不能被误判为在线或把认证带到其他地址。"""
    calls = []

    def send(adapter, request, **kwargs):
        calls.append(request)
        return response_for(adapter, request, status, b"", {"Location": "http://other.example.test"})

    monkeypatch.setattr(HTTPAdapter, "send", send)
    device = horn()
    assert device.connect() is False
    result = device.snapshot()
    assert result["state"] == "failed"
    assert message in result["last_error"]
    assert len(calls) == 1


@pytest.mark.parametrize(("error_type", "message"), [
    (requests.ConnectTimeout, "超时"), (requests.ReadTimeout, "超时"),
    (requests.ConnectionError, "无法连接"), (requests.exceptions.SSLError, "证书校验失败"),
    (requests.exceptions.InvalidURL, "HTTP 请求异常"),
])
def test_network_errors_are_distinct_without_exposing_secrets(monkeypatch, caplog, error_type, message):
    """网络错误类型可见，但原始异常中的密码和响应文本不能进入状态或日志。"""
    def send(adapter, request, **kwargs):
        raise error_type("private-error-detail " + CONFIG["password"])

    monkeypatch.setattr(HTTPAdapter, "send", send)
    device = horn()
    assert device.connect() is False
    result = device.snapshot()
    assert message in result["last_error"]
    assert CONFIG["password"] not in result["last_error"] + caplog.text
    assert "private-error-detail" not in result["last_error"] + caplog.text


@pytest.mark.parametrize("body", [b"<html>Login</html>", b"<invalid", b"<ResponseStatus/>"])
def test_connection_rejects_html_malformed_xml_and_error_documents(monkeypatch, body):
    """设备网页或 XML 错误文档返回 200 时仍不得判定认证成功。"""
    monkeypatch.setattr(HTTPAdapter, "send", lambda adapter, request, **kwargs:
                        response_for(adapter, request, body=body))
    device = horn()
    assert device.connect() is False
    assert device.snapshot()["online"] is False
    assert "设备认证失败" in device.snapshot()["last_error"]


@pytest.mark.parametrize(("body", "success"), [
    (b'{"statusCode":1,"statusString":"OK"}', True),
    (b'{"statusCode":4,"subStatusCode":"notSupport"}', False),
    (b'{"statusCode":true}', False), (b"{}", False), (b"<html>Error</html>", False),
])
def test_play_uses_audio_file_id_and_checks_isapi_business_status(monkeypatch, body, success):
    """播放必须使用固件网页相同的 PUT 接口，并检查 HTTP 200 内的业务失败。"""
    calls = []

    def send(adapter, request, **kwargs):
        calls.append(request)
        return response_for(adapter, request, body=DEVICE_INFO if request.method == "GET" else body)

    monkeypatch.setattr(HTTPAdapter, "send", send)
    device = horn()
    assert device.play(42) is success
    assert [(request.method, urlsplit(request.url).path) for request in calls] == [
        ("GET", "/ISAPI/System/deviceInfo"),
        ("PUT", "/ISAPI/AccessControl/EventCardLinkageCfg/CustomAudio/42/play"),
    ]
    assert urlsplit(calls[-1].url).query == "format=json"
    assert json.loads(calls[-1].body) == {}
    result = device.snapshot()
    assert result["online"] is success
    assert bool(result["last_error"]) is not success


@pytest.mark.parametrize("event_id", [0, -1, True, "01", "1/stop", "1?other=2", "unknown", 2_147_483_648])
def test_invalid_audio_ids_do_not_send_control_requests(monkeypatch, event_id):
    """音频 ID 不能改变请求路径或越过现有绑定字段的整数边界。"""
    from AiVision.alarms.devices.hikvision import HikvisionSpeakerClient, HikvisionSpeakerError

    def send(adapter, request, **kwargs):
        pytest.fail("无效音频 ID 不应发送设备请求")

    monkeypatch.setattr(HTTPAdapter, "send", send)
    client = HikvisionSpeakerClient(CONFIG["url"], CONFIG["username"], CONFIG["password"], 5)
    with pytest.raises(HikvisionSpeakerError, match="音频文件 ID"):
        client.play(event_id)


def test_online_checks_recover_without_session_keepalive_calls(monkeypatch):
    """在线状态失败后能恢复，周期检查始终只读同一设备信息接口。"""
    calls = []

    def send(adapter, request, **kwargs):
        calls.append(request)
        return response_for(adapter, request, status=500 if len(calls) == 2 else 200)

    monkeypatch.setattr(HTTPAdapter, "send", send)
    device = horn()
    assert device.check_connection()["online"] is True
    assert device.check_connection()["state"] == "offline"
    assert device.check_connection()["online"] is True
    assert device.snapshot()["last_error"] is None
    assert all(request.method == "GET" and request.url.endswith("/ISAPI/System/deviceInfo") for request in calls)
    assert len(calls) == 3


def test_play_cooldown_and_expired_queue_items_do_not_repeat_requests(monkeypatch):
    """相同设备的短时重复告警和过期排队任务都不能重复触发声音。"""
    calls = []

    def send(adapter, request, **kwargs):
        calls.append(request)
        return response_for(adapter, request, body=DEVICE_INFO if request.method == "GET" else b'{"statusCode":1}')

    monkeypatch.setattr(HTTPAdapter, "send", send)
    device = horn()
    device._cooldown = 60
    assert device.play(1, expires_at=time.monotonic() - 1) is False
    assert calls == []
    assert device.play(1) is True
    assert not device.play(1)
    assert len(calls) == 2


def test_stop_during_authentication_prevents_online_state_and_playback(monkeypatch):
    """停用中的在途认证完成后不能恢复在线，也不能接受新的播放任务。"""
    device = horn()
    calls = []

    def send(adapter, request, **kwargs):
        calls.append(request)
        device.request_stop()
        return response_for(adapter, request)

    monkeypatch.setattr(HTTPAdapter, "send", send)
    assert device.connect() is False
    assert device.snapshot()["state"] == "stopped"
    assert device.snapshot()["online"] is False
    assert device.play(1) is False
    assert len(calls) == 1


@pytest.mark.parametrize(("enabled", "restart", "expected_states"), [
    (True, True, ["false", "true"]), (True, False, ["true"]), (False, True, ["true"]),
])
def test_sip_recovery_reenables_channel_and_preserves_device_settings(monkeypatch, enabled, restart, expected_states):
    """只在恢复未注册的通道时触发重新启用，且保留海康默认 XML 命名空间与其他配置。"""
    from AiVision.alarms.devices.hikvision import HikvisionSpeakerClient

    namespace = "http://www.hikvision.com/ver20/XMLSchema"
    original = (f'<SIPServer xmlns="{namespace}"><localPort>5060</localPort><Standard>'
                f'<enabled>{str(enabled).lower()}</enabled><expires>3600</expires>'
                '</Standard><vendorOption>preserved</vendorOption></SIPServer>').encode()
    writes = []

    def send(adapter, request, **_kwargs):
        if request.method == "GET":
            return response_for(adapter, request, body=original)
        assert b"ns0:" not in request.body
        root = ET.fromstring(request.body)
        standard = root.find(f"{{{namespace}}}Standard")
        writes.append(standard.find(f"{{{namespace}}}enabled").text)
        assert standard.find(f"{{{namespace}}}expires").text == "3600"
        assert root.find(f"{{{namespace}}}vendorOption").text == "preserved"
        assert standard.find(f"{{{namespace}}}registrarPort").text == "5062"
        assert standard.find(f"{{{namespace}}}password").text == "test-sip-password"
        return response_for(adapter, request, body=b'<ResponseStatus><statusCode>1</statusCode></ResponseStatus>')

    monkeypatch.setattr(HTTPAdapter, "send", send)
    client = HikvisionSpeakerClient(CONFIG["url"], CONFIG["username"], CONFIG["password"], 5)
    client.configure_sip({"address": "192.0.2.10", "port": 5062}, {
        "username": "speaker", "auth_id": "speaker-auth", "password": "test-sip-password", "port": 5060,
    }, restart_registration=restart)
    assert writes == expected_states


@pytest.fixture
def sip_registration(monkeypatch):
    """执行正式 REGISTER 摘要认证，仅替换 UDP 发送，不访问真实喇叭。"""
    from AiVision.alarms.devices.sip_protocol import parse_message
    from AiVision.alarms.devices.sip_server import SipAudioServer

    server, responses = SipAudioServer(), []
    config = {"id": 1, "url": "http://192.0.2.20", "enable": True, "sip": {
        "username": "speaker", "auth_id": "speaker-auth", "password": "test-sip-password", "port": 5060,
    }}
    server.set_device(config)
    monkeypatch.setattr(server, "send", lambda data, _peer: responses.append(parse_message(data)))
    return server, config, responses


def register_sip(server, responses, *, username="speaker", auth_id="speaker", password="test-sip-password"):
    """模拟设备按服务端挑战回复 Digest，覆盖固件使用账户或认证 ID 两种情况。"""
    from AiVision.alarms.devices.sip_protocol import SipMessage, authorization

    uri = "sip:192.0.2.10:5062"
    message = SipMessage(f"REGISTER {uri} SIP/2.0", {
        "via": "SIP/2.0/UDP 192.0.2.20:5060;branch=z9hG4bK-test",
        "from": f"<sip:{username}@192.0.2.10>;tag=test", "to": f"<sip:{username}@192.0.2.10>",
        "call-id": "test-registration", "cseq": "1 REGISTER", "expires": "3600",
    })
    peer = ("192.0.2.20", 5060)
    server._register(message, peer)
    assert responses[-1].status == 401
    message.headers["authorization"] = authorization(
        responses[-1].headers["www-authenticate"], auth_id, password, "REGISTER", uri,
    )
    message.headers["cseq"] = "2 REGISTER"
    server._register(message, peer)
    return responses[-1].status


@pytest.mark.parametrize("auth_id", ["speaker", "speaker-auth"])
def test_sip_registration_accepts_supported_digest_identities(sip_registration, auth_id):
    """注册通过真实密码校验后才可用，两种海康摘要账户形式均能工作。"""
    server, _config, responses = sip_registration
    assert "未收到" in server.registration_error(1)
    assert register_sip(server, responses, auth_id=auth_id) == 200
    assert server.registered(1)


def test_sip_registration_distinguishes_account_and_password_failures(sip_registration):
    """拒绝错误账户和密码，错误信息不含密码，正确注册后不保留旧失败状态。"""
    from AiVision.alarms.devices.sip_protocol import SipMessage

    server, _config, responses = sip_registration
    server._register(SipMessage("REGISTER sip:192.0.2.10 SIP/2.0", {"to": "<sip:other@192.0.2.10>"}),
                     ("192.0.2.20", 5060))
    assert "账户" in server.registration_error(1)
    assert not responses and not server.registered(1)
    assert register_sip(server, responses, password="incorrect-test-password") == 401
    assert "认证" in server.registration_error(1)
    assert "test-password" not in server.registration_error(1)
    assert not server.registered(1)
    assert register_sip(server, responses) == 200
    assert server.registered(1)
    server.remove_device(1)
    assert not server.registered(1)
    assert "未收到" in server.registration_error(1)


def test_sip_retries_after_registration_timeout_and_server_restart(sip_registration, monkeypatch):
    """首次超时后仍触发注册恢复；平台重启或注册过期时重试，正常心跳不反复启停。"""
    from AiVision.alarms.devices import horn as module
    from AiVision.alarms.devices.sip_protocol import SipAudioError

    server, config, responses = sip_registration
    server.generation = 1
    monkeypatch.setattr(module, "horn_sip_service", SimpleNamespace(
        server=server, ensure_started=lambda: {"running": True, "address": "192.0.2.10", "port": 5062},
    ))
    monkeypatch.setattr(module.settings.alarm, "horn_sip_call_timeout", 0.001)
    device = module.Horn({"id": 1, "horn_url": config["url"], "sip": config["sip"]}, connect_on_init=False)
    attempts = []

    def configure(_server, _sip, *, restart_registration):
        attempts.append(restart_registration)
        if len(attempts) > 1:
            assert register_sip(server, responses) == 200

    monkeypatch.setattr(device._client, "configure_sip", configure)
    with pytest.raises(SipAudioError, match="未收到"):
        device.prepare_sip()
    assert not device.snapshot()["sip_ready"]
    assert device.prepare_sip()
    assert device.prepare_sip()
    assert len(attempts) == 2
    server.stop()
    server.generation += 1
    assert device.prepare_sip()
    assert device.snapshot()["sip_ready"]
    assert attempts == [True, True, True]
