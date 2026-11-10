"""镜头协议、设备串行控制及管理员 API 回归，不访问真实摄像头。"""
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def modules(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "zoom_test",
        "MYSQL_DB_PASSWORD": "zoom_test", "MYSQL_DB_NAME": "zoom_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "zoom-test-signing-key-0000000000",
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.cameras import zoom
    from AiVision.api.routes import camera_zoom
    return zoom, camera_zoom


@pytest.fixture
def options():
    return SimpleNamespace(scheme="http", port=80, request_timeout_seconds=0.2,
                           step_seconds=0.001, speed_fraction=0.2)


@pytest.fixture
def camera():
    return {"camera_id": 1, "shm_name": "camera_1", "name": "测试摄像头",
            "url": "rtsp://operator:local%40secret@192.0.2.10:554/Streaming/Channels/101",
            "department": "general_electric", "enabled": True}


def channels(support="true", channel=1):
    return f'<PTZChannelList xmlns="http://www.hikvision.com/ver20/XMLSchema"><PTZChannel><id>{channel}</id><zoomSupport>{support}</zoomSupport></PTZChannel></PTZChannelList>'


def capabilities(minimum=-100, maximum=100):
    return f'<PTZChannelCap><ContinuousZoomSpace><ZRange><Min>{minimum}</Min><Max>{maximum}</Max></ZRange></ContinuousZoomSpace></PTZChannelCap>'


def stub_transport(monkeypatch, zoom, replies):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.request.side_effect = [SimpleNamespace(status_code=code, content=body.encode()) for code, body in replies]
    monkeypatch.setattr(zoom.requests, "Session", Mock(return_value=session))
    return session


@pytest.mark.parametrize("minimum,maximum", [(-100, 100), (-1, 1), (0, 1)])
def test_capabilities_require_explicit_flag_and_continuous_range(modules, options, camera, monkeypatch, minimum, maximum):
    zoom, _ = modules
    session = stub_transport(monkeypatch, zoom, [(200, channels()), (200, capabilities(minimum, maximum))])
    result = zoom.CameraZoomService(options).capabilities(camera)
    assert result.status == "supported" and result.channel_id == 1
    assert result.minimum == minimum and result.maximum == maximum
    assert result.zoom_in and result.zoom_out == (minimum < 0)
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)
    assert session.trust_env is False
    assert session.auth.username == "operator" and session.auth.password == "local@secret"
    assert all(call.kwargs["allow_redirects"] is False for call in session.request.call_args_list)
    assert "local@secret" not in result.model_dump_json()


@pytest.mark.parametrize("reply,status", [
    ((200, channels("false")), "unsupported"),
    ((200, '<ResponseStatus><statusCode>4</statusCode><subStatusCode>notSupport</subStatusCode></ResponseStatus>'), "unknown"),
    ((200, '<PTZChannelList/>'), "unknown"),
    ((200, '<notSupport/>'), "unknown"),
    ((403, '<ResponseStatus/>'), "unknown"),
    ((404, '<html/>'), "unknown"),
    ((302, '<html/>'), "unknown"),
    ((200, 'invalid xml'), "unknown"),
])
def test_missing_or_rejected_capability_is_not_false_support(modules, options, camera, monkeypatch, reply, status):
    zoom, _ = modules
    session = stub_transport(monkeypatch, zoom, [reply])
    assert zoom.CameraZoomService(options).capabilities(camera).status == status
    assert session.request.call_count == 1


@pytest.mark.parametrize("minimum,maximum", [("nan", 100), (-100, "inf"), (10, 100), (-1, -1)])
def test_invalid_control_range_is_unknown(modules, options, camera, monkeypatch, minimum, maximum):
    zoom, _ = modules
    stub_transport(monkeypatch, zoom, [(200, channels()), (200, capabilities(minimum, maximum))])
    assert zoom.CameraZoomService(options).capabilities(camera).status == "unknown"


def test_stream_channel_is_matched_instead_of_always_controlling_first_camera(modules, options, camera, monkeypatch):
    zoom, _ = modules
    camera["url"] = camera["url"].replace('/101', '/202')
    session = stub_transport(monkeypatch, zoom, [(200, channels(channel=1))])
    assert zoom.CameraZoomService(options).capabilities(camera).status == "unknown"
    assert session.request.call_count == 1
    session = stub_transport(monkeypatch, zoom, [(200, channels(channel=2)), (200, capabilities())])
    assert zoom.CameraZoomService(options).capabilities(camera).channel_id == 2
    assert session.request.call_args_list[1].args[1].endswith('/2/capabilities')


@pytest.mark.parametrize("url", ["/local/file.mp4", "rtsp://192.0.2.1/live", "https://example.test/api",
    "rtsp://operator:fake-password@192.0.2.1/h264/ch2/main/av_stream"])
def test_invalid_sources_do_not_send_network_requests(modules, options, camera, monkeypatch, url):
    zoom, _ = modules
    factory = Mock()
    camera['url'] = url
    result = zoom.CameraZoomService(options, factory).capabilities(camera)
    assert result.status == "unknown"
    factory.assert_not_called()


@pytest.mark.parametrize("action,speed", [("in", "20"), ("out", "-20")])
def test_short_step_always_stops_and_uses_zoom_only(modules, options, camera, monkeypatch, action, speed):
    zoom, _ = modules
    ok = '<ResponseStatus><statusCode>1</statusCode></ResponseStatus>'
    session = stub_transport(monkeypatch, zoom, [(200, channels()), (200, capabilities()), (200, ok), (200, ok)])
    result = zoom.CameraZoomService(options).control(camera, action)
    puts = [call for call in session.request.call_args_list if call.args[0] == "PUT"]
    assert result.stopped and len(puts) == 2
    assert f'<zoom>{speed}</zoom>'.encode() in puts[0].kwargs['data']
    assert b'<zoom>0</zoom>' in puts[1].kwargs['data']
    assert all(b'<pan>' not in call.kwargs['data'] and b'<tilt>' not in call.kwargs['data'] for call in puts)


def fake_client(zoom):
    return SimpleNamespace(capabilities=Mock(return_value=zoom.CameraZoomCapabilities(
        status="supported", message="支持", minimum=-100, maximum=100, zoom_in=True, zoom_out=True)), continuous=Mock())


def test_start_timeout_still_sends_stop(modules, options, camera):
    zoom, _ = modules
    client = fake_client(zoom)
    client.continuous.side_effect = [zoom.CameraZoomError("启动超时"), None]
    with pytest.raises(zoom.CameraZoomError, match="启动超时"):
        zoom.CameraZoomService(options, lambda *args: client).control(camera, "in")
    assert [call.args[0] for call in client.continuous.call_args_list] == [20, 0]


def test_unconfirmed_stop_is_reported_as_failure(modules, options, camera):
    zoom, _ = modules
    client = fake_client(zoom)
    client.continuous.side_effect = [None, zoom.CameraZoomError("停止超时")]
    with pytest.raises(zoom.CameraZoomError, match="停止变焦未获设备确认"):
        zoom.CameraZoomService(options, lambda *args: client).control(camera, "in")


def test_device_business_rejection_is_not_success(modules, options, camera, monkeypatch):
    zoom, _ = modules
    session = stub_transport(monkeypatch, zoom, [(200, channels()), (200, capabilities()),
        (200, '<ResponseStatus><statusCode>4</statusCode></ResponseStatus>'),
        (200, '<ResponseStatus><statusCode>1</statusCode></ResponseStatus>')])
    with pytest.raises(zoom.CameraZoomError, match="未接受"):
        zoom.CameraZoomService(options).control(camera, "in")
    assert b'<zoom>0</zoom>' in session.request.call_args.kwargs['data']


def test_same_device_aliases_are_serialized_and_stop_interrupts_wait(modules, options, camera):
    zoom, _ = modules
    options.step_seconds = 5
    client = fake_client(zoom)
    started = Event()
    client.continuous.side_effect = lambda speed: started.set() if speed else None
    service = zoom.CameraZoomService(options, lambda *args: client)
    results = []
    failures = []
    def move():
        try:
            results.append(service.control(camera, "in"))
        except Exception as exc:
            failures.append(exc)
    worker = Thread(target=move)
    worker.start()
    try:
        assert started.wait(1)
        alias = {**camera, "camera_id": 2, "shm_name": "camera_2"}
        with pytest.raises(zoom.CameraZoomError, match="正在调整"):
            service.control(alias, "out")
        assert service.control(alias, "stop").stopped
        worker.join(1)
        assert not worker.is_alive() and not failures and results[0].stopped
        assert [call.args[0] for call in client.continuous.call_args_list] == [20, 0, 0]
    finally:
        service._motions[zoom._target(camera, options).key].cancel.set()
        worker.join(1)


def test_transport_errors_are_sanitized(modules, options, camera, monkeypatch):
    zoom, _ = modules
    session = stub_transport(monkeypatch, zoom, [])
    session.request.side_effect = zoom.requests.Timeout('rtsp://operator:local@secret@192.0.2.10')
    result = zoom.CameraZoomService(options).capabilities(camera)
    assert result.status == 'unknown' and '超时' in result.message
    assert 'secret' not in result.model_dump_json() and '192.0.2.10' not in result.model_dump_json()


@pytest.fixture
def api(modules, camera):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth.auth import get_current_user
    zoom, routes = modules
    app = FastAPI()
    app.include_router(routes.router)
    user = {"role": "admin", "feature_access": {"general_electric": ["detect_phone"]}}
    app.dependency_overrides[get_current_user] = lambda: user
    manager = SimpleNamespace(get_camera=Mock(return_value=camera))
    service = SimpleNamespace(capabilities=Mock(return_value=zoom.CameraZoomCapabilities(status="supported", message="支持")),
        control=Mock(side_effect=lambda cam, action: zoom.CameraZoomResult(action=action)))
    app.dependency_overrides[routes.get_camera_config_manager] = lambda: manager
    app.dependency_overrides[routes.get_camera_zoom_service] = lambda: service
    with TestClient(app) as client:
        yield client, user, manager, service, camera


@pytest.mark.parametrize("method", ["get", "post"])
def test_viewer_cannot_query_or_control_lens(api, method):
    client, user, _, service, _ = api
    user['role'] = 'viewer'
    response = getattr(client, method)('/api/cameras/camera_1/zoom?feature=detect_phone', **({'json': {'action': 'in'}} if method == 'post' else {}))
    assert response.status_code == 403
    service.capabilities.assert_not_called()
    service.control.assert_not_called()


def test_api_checks_exact_department_disabled_camera_and_resource(api):
    client, _, manager, service, camera = api
    url = '/api/cameras/camera_1/zoom?feature=detect_phone'
    assert client.get(url).status_code == 200
    camera['department'] = 'research_institute'
    assert client.get(url).status_code == 403
    assert client.post(url, json={'action': 'in'}).status_code == 403
    camera['department'] = None
    assert client.get(url).status_code == 403
    camera['department'] = 'general_electric'
    camera['enabled'] = False
    assert client.get(url).status_code == 409
    assert client.post(url, json={'action': 'in'}).status_code == 409
    assert client.post(url, json={'action': 'stop'}).status_code == 200
    manager.get_camera.return_value = None
    assert client.get(url).status_code == 404
    assert service.control.call_count == 1


@pytest.mark.parametrize('payload', [{'action': 'arbitrary'}, {'action': 'in', 'url': 'http://example.test'}, {'action': 'in', 'speed': 100}, {'action': 'in', 'duration': 60}])
def test_api_rejects_client_selected_source_speed_or_duration(api, payload):
    client, _, _, service, _ = api
    assert client.post('/api/cameras/camera_1/zoom?feature=detect_phone', json=payload).status_code == 422
    service.control.assert_not_called()


def test_new_api_does_not_expose_device_credentials(api):
    client, _, _, service, _ = api
    assert client.get('/api/cameras/camera_1/zoom?feature=detect_phone').json()['status'] == 'supported'
    result = client.post('/api/cameras/camera_1/zoom?feature=detect_phone', json={'action': 'out'})
    assert result.json() == {'action': 'out', 'stopped': True}
    assert 'url' not in result.text and 'secret' not in result.text
    assert service.control.call_args.args[0]['shm_name'] == 'camera_1'
