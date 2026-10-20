"""摄像头冷启动限制并发，慢路、失败路与退出过程相互隔离。"""

import threading
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def store(monkeypatch, tmp_path):
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "test",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path), "AUTO_CREATE_DB": "false",
    }.items():
        monkeypatch.setenv(key, value)
    from AiVision.cameras import runtime_manager as module

    created = []

    class Capture:
        def __init__(self, config, active_index, frame_seq, event_queue=None):
            self.shm_name = config["shm_name"]
            self.name = config["name"]
            self.shape = (10, 20, 3)
            self.status = True
            self.msg = ""
            self.stop = Mock()
            created.append(self)

        def start(self, active_index):
            return None

    proxies = SimpleNamespace(
        dict=dict, Value=lambda kind, value: SimpleNamespace(value=value), Queue=Queue,
    )
    manager = module.CameraRuntimeManager(proxies)
    reader = SimpleNamespace(register=Mock(return_value=True), unregister=Mock())
    monkeypatch.setattr(module, "CameraRuntime", Capture)
    monkeypatch.setattr(module, "frame_reader_registry", reader)
    monkeypatch.setattr(module.settings.runtime, "camera_start_workers", 2)
    monkeypatch.setattr(manager, "_start_watchdog", Mock())
    monkeypatch.setattr(manager, "_stop_watchdog", Mock())
    return SimpleNamespace(manager=manager, module=module, capture=Capture, created=created, reader=reader)


def configure(manager, switches):
    manager.initialize_configs([
        {"name": f"入口{i}", "shm_name": f"camera_{i}", "url": "rtsp://example.invalid/live", "enable": enabled}
        for i, enabled in enumerate(switches, start=1)
    ])


def start_thread(action):
    errors = []

    def run():
        try:
            action()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    return thread, errors


def test_slow_camera_does_not_block_other_slots_and_concurrency_is_bounded(store, monkeypatch):
    configure(store.manager, [True] * 5 + [False])
    release = threading.Event()
    fast_done = threading.Event()
    lock = threading.Lock()
    active = peak = completed = 0

    def start(capture, active_index):
        nonlocal active, peak, completed
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            if capture.shm_name == "camera_1":
                assert release.wait(5), "测试未释放慢摄像头"
            else:
                with lock:
                    completed += 1
                    if completed == 4:
                        fast_done.set()
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(store.capture, "start", start)
    thread, errors = start_thread(store.manager.start_all)
    try:
        assert fast_done.wait(3), "慢摄像头占用一路时，其余摄像头仍应继续启动"
        assert thread.is_alive()
        store.manager._start_watchdog.assert_not_called()
        assert peak == 2
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive() and not errors
    assert set(store.manager.list_running()) == {f"camera_{i}" for i in range(1, 6)}
    assert len(store.created) == 5
    assert store.reader.register.call_count == 5
    for capture in store.created:
        config, index, sequence = store.manager._shared_configs[capture.shm_name]
        assert config["shape"] == capture.shape
        assert sequence.value == 0
        store.reader.register.assert_any_call(capture.shm_name, capture.shape, index, sequence)
    store.manager._start_watchdog.assert_called_once()


@pytest.mark.parametrize("switches", [[], [False, False]])
def test_no_enabled_camera_skips_startup_pool(store, monkeypatch, switches):
    configure(store.manager, switches)
    pool = Mock(side_effect=AssertionError("无需采集时不能创建启动线程池"))
    monkeypatch.setattr(store.module, "ThreadPoolExecutor", pool)
    store.manager.start_all()
    assert not store.created and not store.manager.list_running()
    store.manager._start_watchdog.assert_called_once()


def test_failed_camera_preserves_retry_state_without_blocking_healthy_camera(store, monkeypatch):
    configure(store.manager, [True, True])
    initialize = store.capture.__init__

    def initialize_with_failure(capture, *args, **kwargs):
        initialize(capture, *args, **kwargs)
        if capture.shm_name == "camera_1":
            capture.status = False
            capture.msg = "网络不可达"

    monkeypatch.setattr(store.capture, "__init__", initialize_with_failure)
    alerts = Mock()
    store.manager.configure_runtime_alerts(alerts)
    store.manager.start_all()
    assert store.manager.list_running() == ["camera_2"]
    assert "camera_1" in store.manager._last_start_attempts
    assert store.manager._shared_configs["camera_1"][0]["enable"] is True
    alerts.assert_called_once()
    store.manager._start_watchdog.assert_called_once()


def test_unexpected_startup_exception_is_propagated(store, monkeypatch):
    configure(store.manager, [True])
    monkeypatch.setattr(store.manager, "_start_one", Mock(side_effect=RuntimeError("启动调度异常")))
    with pytest.raises(RuntimeError, match="启动调度异常"):
        store.manager.start_all()
    store.manager._start_watchdog.assert_not_called()


def test_stop_during_startup_skips_queued_cameras_and_reclaims_started_capture(store, monkeypatch):
    configure(store.manager, [True, True])
    monkeypatch.setattr(store.module.settings.runtime, "camera_start_workers", 1)
    entered = threading.Event()
    release = threading.Event()
    stopping = threading.Event()

    def start(capture, active_index):
        entered.set()
        assert release.wait(5), "测试未释放启动等待"

    monkeypatch.setattr(store.capture, "start", start)
    store.manager._stop_watchdog.side_effect = stopping.set
    starting_thread, start_errors = start_thread(store.manager.start_all)
    stopping_thread = None
    try:
        assert entered.wait(3)
        stopping_thread, stop_errors = start_thread(store.manager.stop_all)
        assert stopping.wait(3)
    finally:
        release.set()
        starting_thread.join(timeout=5)
        if stopping_thread is not None:
            stopping_thread.join(timeout=5)
    assert not starting_thread.is_alive() and not stopping_thread.is_alive()
    assert not start_errors and not stop_errors
    assert [capture.shm_name for capture in store.created] == ["camera_1"]
    store.created[0].stop.assert_called_once()
    assert not store.manager.list_running()
    store.manager._start_watchdog.assert_not_called()
