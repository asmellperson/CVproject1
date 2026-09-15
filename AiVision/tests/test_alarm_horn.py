import logging
import threading
import time

from AiVision.alarms.devices import horn as horn_module
from AiVision.alarms.devices.horn import Horn


def test_stop_during_login_prevents_online_play_and_restart(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        entered.set()
        assert release.wait(2)
        return FakeResponse(200, {"access_key": "key", "access_id": "id"})

    monkeypatch.setattr(horn_module.requests, "post", post)
    horn = Horn({"horn_url": "http://speaker.local", "password": "test"}, connect_on_init=False)
    assert calls == []
    horn.start_heartbeat()
    assert entered.wait(1)
    horn.request_stop()
    assert horn.snapshot()["state"] == "stopping"
    release.set()
    horn.stop_heartbeat()
    horn.play(1)
    horn.connect()
    horn.start_heartbeat()
    assert calls == ["http://speaker.local/login"]
    assert horn.snapshot()["state"] == "stopped"
    assert not horn.status and horn.access_key is None


def test_heartbeat_http_failure_recovers_on_next_heartbeat(monkeypatch):
    calls = []
    responses = iter([FakeResponse(200, {"access_key": "a", "access_id": "b"}),
                      FakeResponse(401), FakeResponse(200, {"access_key": "c", "access_id": "d"}),
                      FakeResponse(200)])
    monkeypatch.setattr(horn_module.requests, "post", lambda url, **kwargs: calls.append(url) or next(responses))
    horn = Horn({"horn_url": "http://speaker.local"})
    horn._send_heart()
    assert horn.snapshot()["state"] == "offline"
    horn._send_heart()
    assert horn.snapshot()["state"] == "online"
    assert horn.snapshot()["last_error"] is None
    assert horn.snapshot()["last_seen_at"] is not None
    assert [url.rsplit("/", 1)[-1] for url in calls] == ["login", "online", "login", "online"]


def test_device_play_cooldown_is_preserved(monkeypatch):
    calls = []
    monkeypatch.setattr(horn_module.requests, "post", lambda url, **kwargs: calls.append(url) or
                        FakeResponse(200, {"access_key": "key", "access_id": "id"}))
    horn = Horn({"horn_url": "http://speaker.local"})
    horn.play(1)
    horn.play(1)
    assert sum(url.endswith("run_task") for url in calls) == 1


def test_expiration_after_waiting_for_device_lock_skips_play(monkeypatch):
    calls = []
    monkeypatch.setattr(horn_module.requests, "post", lambda url, **kwargs: calls.append(url))
    horn = Horn({"horn_url": "http://speaker.local"}, connect_on_init=False)
    with horn._io_lock:
        worker = threading.Thread(target=lambda: horn.play(1, expires_at=time.monotonic() + 0.01))
        worker.start()
        threading.Event().wait(0.03)
    worker.join(1)
    assert not worker.is_alive() and calls == []


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_horn_normalizes_url_and_requires_both_login_credentials(monkeypatch, caplog):
    calls = []
    responses = iter(
        (
            FakeResponse(200, {"access_key": "key", "access_id": "id"}),
            FakeResponse(200, {"access_key": "key"}),
        )
    )
    monkeypatch.setattr(
        horn_module.requests,
        "post",
        lambda url, **kwargs: calls.append(url) or next(responses),
    )

    horn = Horn({"horn_url": "http://speaker.local"})
    assert horn.url == "http://speaker.local/"
    assert horn.status is True
    assert calls == ["http://speaker.local/login"]

    with caplog.at_level(logging.WARNING):
        assert horn.connect() is False
    assert horn.status is False
    assert horn.access_key is None
    assert horn.access_id is None
    assert "缺少 access_key/access_id" in caplog.text


def test_horn_heartbeat_reconnects_before_online(monkeypatch):
    calls = []
    responses = iter(
        (
            FakeResponse(200, {"access_key": "key-1", "access_id": "id-1"}),
            FakeResponse(200, {"access_key": "key-2", "access_id": "id-2"}),
            FakeResponse(200),
        )
    )
    monkeypatch.setattr(
        horn_module.requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs.get("json"))) or next(responses),
    )
    horn = Horn({"horn_url": "http://speaker.local/"})
    horn.status = False

    horn._send_heart()

    assert [url for url, _payload in calls] == [
        "http://speaker.local/login",
        "http://speaker.local/login",
        "http://speaker.local/online",
    ]
    assert calls[-1][1] == {"access_key": "key-2", "access_id": "id-2"}
    assert horn.status is True


def test_horn_play_reconnect_failure_skips_request(monkeypatch, caplog):
    calls = []
    responses = iter(
        (
            FakeResponse(200, {"access_key": "key", "access_id": "id"}),
            FakeResponse(500),
        )
    )
    monkeypatch.setattr(
        horn_module.requests,
        "post",
        lambda url, **kwargs: calls.append(url) or next(responses),
    )
    horn = Horn({"horn_url": "http://speaker.local"})
    horn.status = False

    with caplog.at_level(logging.WARNING):
        horn.play(7)

    assert calls == ["http://speaker.local/login", "http://speaker.local/login"]
    assert horn.status is False
    assert "设备离线且重连失败" in caplog.text


def test_horn_play_non_success_marks_device_offline(monkeypatch, caplog):
    calls = []
    responses = iter(
        (
            FakeResponse(200, {"access_key": "key", "access_id": "id"}),
            FakeResponse(401),
        )
    )
    monkeypatch.setattr(
        horn_module.requests,
        "post",
        lambda url, **kwargs: calls.append(url) or next(responses),
    )
    horn = Horn({"horn_url": "http://speaker.local///"})

    with caplog.at_level(logging.WARNING):
        horn.play(8)

    assert calls == ["http://speaker.local/login", "http://speaker.local/run_task"]
    assert horn.status is False
    assert "HTTP 401" in caplog.text
