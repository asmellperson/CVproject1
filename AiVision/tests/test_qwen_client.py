"""共享模型客户端的错误分类、超时与并发名额回收回归，不访问模型服务。"""

from concurrent.futures import ThreadPoolExecutor
import threading
import traceback
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
import requests


@pytest.fixture
def transport_case(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path), "SECURITY_VLM_API_KEY": "fixture-only-key",
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.connectors.qwen import client as module

    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    slots = Mock()
    slots.acquire.return_value = True
    monkeypatch.setattr(module, "_slots", slots)
    response = MagicMock(status_code=200, text='{"choices":[]}')
    response.__enter__.return_value = response
    transport = MagicMock()
    transport.__enter__.return_value = transport
    transport.post.return_value = response
    factory = Mock(return_value=transport)
    monkeypatch.setattr(module.requests, "Session", factory)
    instance = module.QwenClient()
    yield SimpleNamespace(
        module=module, clock=clock, slots=slots, transport=transport, response=response, factory=factory,
        complete=lambda **kwargs: instance.complete(
            base_url="http://model.invalid/v1", model="fixture-model", messages=[{"role": "user", "content": "测试"}],
            max_tokens=256, temperature=0.0, **kwargs,
        ),
    )


@pytest.mark.parametrize("json_mode", [True, False])
def test_payload_preserves_json_mode_auth_and_shared_concurrency_budget(transport_case, json_mode):
    case = transport_case

    def acquire(**_kwargs):
        case.clock.now += 2.0
        return True

    case.slots.acquire.side_effect = acquire
    raw, latency = case.complete(timeout=10.0, json_mode=json_mode)
    assert raw == case.response.text and latency == 2.0
    call = case.transport.post.call_args
    assert call.args[0] == "http://model.invalid/v1/chat/completions"
    assert call.kwargs["timeout"] == (5.0, 8.0)
    assert call.kwargs["allow_redirects"] is False and case.transport.trust_env is False
    assert call.kwargs["headers"]["Authorization"] == "Bearer fixture-only-key"
    payload = call.kwargs["json"]
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload.get("response_format") == ({"type": "json_object"} if json_mode else None)
    case.slots.acquire.assert_called_once_with(timeout=10.0)
    case.slots.release.assert_called_once_with()


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_http_service_errors_are_distinct_and_do_not_expose_response_bodies(transport_case, status):
    case = transport_case
    case.response.status_code = status
    case.response.text = "fixture-private-server-error"
    with pytest.raises(case.module.QwenServiceError) as caught:
        case.complete(timeout=10.0)
    assert str(status) in str(caught.value)
    assert case.response.text not in str(caught.value)
    case.slots.release.assert_called_once_with()


@pytest.mark.parametrize("exception_type, expected", [
    (requests.ConnectionError, "QwenNetworkError"), (requests.RequestException, "QwenNetworkError"),
    (requests.ReadTimeout, "QwenTimeoutError"), (requests.ConnectTimeout, "QwenTimeoutError"),
])
def test_transport_errors_and_timeouts_are_distinct_and_redact_their_exception_chain(transport_case, exception_type, expected):
    case = transport_case
    secret = "fixture-connection-credential-and-dialogue"
    case.transport.post.side_effect = exception_type(secret)
    with pytest.raises(getattr(case.module, expected)) as caught:
        case.complete(timeout=10.0)
    assert isinstance(caught.value, case.module.QwenError)
    assert secret not in "".join(traceback.format_exception(caught.value))
    case.slots.release.assert_called_once_with()


def test_busy_slot_timeout_does_not_release_a_slot_it_never_acquired(transport_case):
    case = transport_case
    case.slots.acquire.return_value = False
    with pytest.raises(case.module.QwenTimeoutError):
        case.complete(timeout=1.0)
    case.slots.release.assert_not_called()
    case.factory.assert_not_called()


def test_exhausted_slot_wait_releases_its_slot_without_sending_http(transport_case):
    case = transport_case

    def acquire(**_kwargs):
        case.clock.now += 10.0
        return True

    case.slots.acquire.side_effect = acquire
    with pytest.raises(case.module.QwenTimeoutError):
        case.complete(timeout=10.0)
    case.slots.release.assert_called_once_with()
    case.factory.assert_not_called()


def test_shared_request_limit_remains_bounded_while_another_request_is_running(transport_case, monkeypatch):
    case = transport_case
    semaphore = threading.BoundedSemaphore(1)
    monkeypatch.setattr(case.module, "_slots", semaphore)
    started, release = threading.Event(), threading.Event()

    def post(*_args, **_kwargs):
        started.set()
        if not release.wait(2.0):
            raise requests.Timeout("fixture release timeout")
        return case.response

    case.transport.post.side_effect = post
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(case.complete, timeout=2.0)
        try:
            assert started.wait(2.0)
            with pytest.raises(case.module.QwenTimeoutError):
                case.complete(timeout=0.02)
            assert case.transport.post.call_count == 1
        finally:
            release.set()
        assert pending.result(timeout=2.0)[0] == case.response.text
    assert semaphore.acquire(blocking=False)
    semaphore.release()
