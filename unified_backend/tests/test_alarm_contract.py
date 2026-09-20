"""报警上游故障不能伪装成空列表，正式接口只接受 items 格式。"""
import json

from fastapi import HTTPException
import pytest
import requests
from starlette.requests import Request

from unified_backend import app as backend
from unified_backend.alarm_dispositions import AlarmDispositionStore


REQUEST = Request({"type": "http", "headers": [(b"authorization", b"Bearer test-only"), (b"cookie", b"session=test-only")]})


def response(status=200, body=b'{"items": []}'):
    result = requests.Response()
    result.status_code = status
    result._content = body
    result._content_consumed = True
    return result


def test_current_empty_list_and_request_credentials(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response()
    monkeypatch.setattr(backend.requests, "get", get)
    payload = backend._get_upstream_json("http://aivision", "/api/alarms", REQUEST)
    assert backend._items_from_payload(payload) == []
    assert calls == [("http://aivision/api/alarms", {
        "headers": {"authorization": "Bearer test-only", "cookie": "session=test-only"},
        "timeout": 3.0, "allow_redirects": False,
    })]


@pytest.mark.parametrize("payload", [[], {"alarms": []}, {}, None, {"items": None}, {"items": [1]}, {"items": [{}]}])
def test_alarm_list_rejects_other_shapes(payload):
    with pytest.raises(HTTPException) as caught:
        backend._items_from_payload(payload)
    assert caught.value.status_code == 502


@pytest.mark.parametrize("upstream,expected", [(401, 401), (403, 403), (404, 502), (500, 502), (302, 502), (204, 502)])
@pytest.mark.parametrize("route", ["/api/alarms", "/api/statistics"])
def test_upstream_http_errors_remain_errors(monkeypatch, tmp_path, upstream, expected, route):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(backend, "get_current_user_from_request", lambda _request: {"role": "admin"})
    monkeypatch.setattr(backend.requests, "get", lambda *_args, **_kwargs: response(upstream))
    app = backend.create_app()
    app.dependency_overrides[backend.get_current_user] = lambda: {"role": "admin"}
    result = TestClient(app).get(route)
    assert result.status_code == expected
    assert "items" not in result.json() and "summary" not in result.json()


@pytest.mark.parametrize("body", [b'not json', b'null', b'123', b'"text"'])
def test_invalid_json_response_fails_explicitly(monkeypatch, body):
    monkeypatch.setattr(backend.requests, "get", lambda *_args, **_kwargs: response(body=body))
    with pytest.raises(HTTPException) as caught:
        backend._get_upstream_json("http://aivision", "/api/alarms", REQUEST)
    assert caught.value.status_code == 502


@pytest.mark.parametrize("error,status", [(requests.ReadTimeout, 504), (requests.ConnectionError, 502)])
def test_upstream_network_failure_is_visible_in_overview(monkeypatch, error, status):
    def fail(*_args, **_kwargs):
        raise error("test failure")
    monkeypatch.setattr(backend.requests, "get", fail)
    with pytest.raises(HTTPException) as caught:
        backend._get_upstream_json("http://aivision", "/api/alarms", REQUEST)
    assert caught.value.status_code == status
    ok, payload, _latency, detail = backend._get_json("http://aivision", "/api/runtime/status", request=REQUEST)
    assert not ok and payload is None and detail == caught.value.detail


def test_unexpected_programming_error_is_not_hidden(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("unexpected failure")
    monkeypatch.setattr(backend.requests, "get", fail)
    with pytest.raises(RuntimeError, match="unexpected failure"):
        backend._get_json("http://aivision", "/api/runtime/status")


@pytest.mark.parametrize("raw", ['[]', '{"alarms": []}', '{"items": [null]}', '{', '{"items": [{}]}'])
def test_invalid_disposition_file_is_not_treated_as_empty(tmp_path, raw):
    path = tmp_path / "alarm_dispositions.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        AlarmDispositionStore(tmp_path)
    assert path.read_text() == raw


def test_disposition_write_reload_history_and_duplicate_detection(tmp_path):
    store = AlarmDispositionStore(tmp_path)
    actor = {"employee_id": "test", "name": "测试"}
    first = store.update(alarm_id="aivision:1", status="acknowledged", note="检查中", user=actor)
    second = store.update(alarm_id="aivision:1", status="resolved", note="已处理", user=actor)
    assert second["history"] == [{key: first[key] for key in ("status", "note", "updated_at", "updated_by")}]
    assert AlarmDispositionStore(tmp_path).get_many(["aivision:1"]) == {"aivision:1": second}
    store.path.write_text(json.dumps({"items": [second, second]}))
    with pytest.raises(ValueError, match="duplicate disposition"):
        AlarmDispositionStore(tmp_path)
