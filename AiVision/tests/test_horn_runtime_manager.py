import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from AiVision.core.alarm.dispatcher import AlarmDispatcher, AlarmRequest
from AiVision.core.settings import settings
from AiVision.platform.alarm_device.runtime_manager import HornRuntimeManager


class FakeHorn:
    def __init__(self, config, *, connect_on_init):
        assert connect_on_init is False
        self.config = config
        self.started = False
        self.stopped = False
        self.played = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def start_heartbeat(self):
        self.started = True

    def request_stop(self):
        self.stopped = True

    def stop_heartbeat(self, timeout=2):
        self.request_stop()

    def snapshot(self):
        return {"state": "stopped" if self.stopped else "online", "online": not self.stopped,
                "heartbeat_alive": self.started and not self.stopped}

    def check_connection(self):
        return self.snapshot()

    def play(self, event_id, *, expires_at=None):
        self.entered.set()
        assert self.release.wait(3)
        if not self.stopped:
            self.played.append(event_id)


def config(**values):
    return dict({"id": 1, "url": "http://device.local", "username": "operator",
                 "password": "test-only", "enable": True}, **values)


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(settings.alarm, "horn_reconcile_interval_seconds", 60)
    configs = {1: config()}
    created = []

    def factory(*args, **kwargs):
        horn = FakeHorn(*args, **kwargs)
        created.append(horn)
        return horn

    def load(horn_id=None):
        return [dict(value) for key, value in configs.items() if horn_id is None or horn_id == key]

    manager = HornRuntimeManager(load, factory)
    yield SimpleNamespace(manager=manager, configs=configs, created=created)
    for horn in created:
        horn.release.set()
    manager.stop()


def test_hot_sync_create_credentials_disable_enable_delete(runtime):
    manager = runtime.manager
    manager.start()
    first = runtime.created[-1]
    manager.start()
    assert len(runtime.created) == 1
    runtime.configs[2] = config(id=2, enable=False)
    manager.sync(2)
    assert len(runtime.created) == 1
    runtime.configs[2]["enable"] = True
    manager.sync(2)
    assert runtime.created[-1].started
    for field, value in [("url", "http://changed.local"), ("username", "changed"), ("password", "changed")]:
        old = runtime.created[-1]
        runtime.configs[2][field] = value
        manager.sync(2)
        assert old.stopped and runtime.created[-1] is not old
    runtime.configs[1]["description"] = "note"
    manager.sync(1)
    assert manager._entries[1][1] is first
    runtime.configs[1]["enable"] = False
    manager.sync(1)
    assert first.stopped and not manager.enqueue_play(1, 7)
    assert manager.status(runtime.configs[1])["state"] == "disabled"
    runtime.configs[1]["enable"] = True
    manager.sync(1)
    replacement = manager._entries[1][1]
    assert replacement is not first
    del runtime.configs[1]
    manager.sync(1)
    assert replacement.stopped and 1 not in manager._entries
    manager.stop()
    assert not manager._entries and all(horn.stopped for horn in runtime.created)
    assert all(not thread.is_alive() for thread in manager._threads)


def test_configuration_updates_before_runtime_start_are_loaded_on_start(runtime):
    runtime.manager.sync(1)
    assert runtime.created == []
    assert runtime.manager.status(runtime.configs[1])["state"] == "not_started"
    runtime.configs[1]["password"] = "latest"
    runtime.manager.start()
    assert runtime.created[0].config["password"] == "latest"


def test_sync_failure_closes_old_runtime_then_retries_latest_config(runtime, monkeypatch):
    manager = runtime.manager
    manager.start()
    old = runtime.created[-1]
    load = manager._load

    def fail(_id):
        raise RuntimeError("sensitive database details")

    monkeypatch.setattr(manager, "_load", fail)
    manager.sync(1)
    assert old.stopped and manager.status(runtime.configs[1])["state"] == "failed"
    assert not manager.enqueue_play(1, 1)
    runtime.configs[1]["password"] = "latest"
    monkeypatch.setattr(manager, "_load", load)
    manager.sync()
    assert manager.status(runtime.configs[1])["state"] == "online"
    assert runtime.created[-1].config["password"] == "latest"


def test_background_reconciliation_retries_failed_sync(runtime, monkeypatch):
    monkeypatch.setattr(settings.alarm, "horn_reconcile_interval_seconds", 0.01)
    attempted = threading.Event()
    real_load = runtime.manager._load

    def load(horn_id=None):
        if not attempted.is_set():
            attempted.set()
            raise RuntimeError("temporary failure")
        return real_load(horn_id)

    monkeypatch.setattr(runtime.manager, "_load", load)
    runtime.manager.start()
    deadline = time.monotonic() + 2
    while not runtime.created and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    assert runtime.created and runtime.created[-1].started


def test_bounded_queue_and_invalidated_old_jobs(runtime, monkeypatch):
    monkeypatch.setattr(settings.alarm, "horn_queue_size", 1)
    manager = runtime.manager
    manager.start()
    old = runtime.created[-1]
    old.release.clear()
    assert manager.enqueue_play(1, 1)
    assert old.entered.wait(1)
    assert manager.enqueue_play(1, 2)
    assert not manager.enqueue_play(1, 3)
    runtime.configs[1]["url"] = "http://changed.local"
    manager.sync(1)
    current = runtime.created[-1]
    old.release.set()
    manager._queue.join()
    assert old.played == [] and current.played == []
    assert manager.enqueue_play(1, 4)
    manager._queue.join()
    assert current.played == [4]


def test_expired_play_is_discarded(runtime, monkeypatch):
    monkeypatch.setattr(settings.alarm, "horn_queue_ttl_seconds", 0.01)
    manager = runtime.manager
    manager.start()
    horn = runtime.created[-1]
    horn.release.clear()
    assert manager.enqueue_play(1, 1)
    assert horn.entered.wait(1)
    assert manager.enqueue_play(1, 2)
    threading.Event().wait(0.03)
    horn.release.set()
    manager._queue.join()
    assert horn.played == [1]


def test_slow_device_cannot_block_sql_or_wechat(runtime):
    runtime.manager.start()
    horn = runtime.created[-1]
    horn.release.clear()
    writes = []
    dispatcher = AlarmDispatcher()
    dispatcher.horn_runtime_manager = runtime.manager
    dispatcher.wechat = object()
    dispatcher.violation_writer = SimpleNamespace(save_now=lambda **kwargs: writes.append(kwargs) or SimpleNamespace(id=1))
    request = AlarmRequest(feature_name="blocks", department='research_institute', camera_id=1, camera_name="camera",
        frame=np.zeros((2, 2, 3), dtype=np.uint8), violation_type=1,
        alarm_config={"horn": {"enable": True, "parm": {"horn_id": 1, "horn_event_id": 1}},
                      "sql": {"enable": True}, "wechat": {"enable": True, "parm": {"user": "tester"}}})
    finished = threading.Event()

    def dispatch():
        dispatcher._execute(request)
        finished.set()

    worker = threading.Thread(target=dispatch)
    worker.start()
    try:
        assert horn.entered.wait(1)
        assert finished.wait(1), "设备网络阻塞了其他告警通道"
        assert writes and not dispatcher._wechat_queue.empty()
    finally:
        horn.release.set()
        worker.join(2)


def test_saved_connection_probe_reuses_running_session(runtime):
    runtime.manager.start()
    existing = runtime.created[-1]
    assert runtime.manager.test_connection(runtime.configs[1])["online"]
    assert len(runtime.created) == 1 and not existing.stopped
    unsaved = config(password="unsaved")
    assert runtime.manager.test_connection(unsaved)["online"]
    assert runtime.created[-1].stopped and not runtime.created[-1].started
    assert not existing.stopped
