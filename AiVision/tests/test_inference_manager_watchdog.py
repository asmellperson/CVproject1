from __future__ import annotations

import importlib
import queue

from platform.inference.manager import (
    InferenceManager,
    WorkerWatchdogState,
)


manager_module = importlib.import_module("platform.inference.manager")


class FakeWorker:
    def __init__(self, *, running: bool, alive: bool, failed: bool = False):
        self.running = running
        self.alive = alive
        self.failed = failed
        self.stop_calls = 0

    def is_running(self) -> bool:
        return self.running

    def is_alive(self) -> bool:
        return self.alive

    def is_failed(self) -> bool:
        return self.failed

    def stop(self) -> None:
        self.stop_calls += 1


def _manager_with_worker(worker: FakeWorker) -> InferenceManager:
    manager = InferenceManager()
    manager._model_configs = {
        "test-model": {
            "name": "test-model",
            "import_path": "tests.fake.Worker",
        }
    }
    manager._workers = {"test-model": worker}
    manager._worker_states = {"test-model": WorkerWatchdogState()}
    return manager


def test_watchdog_restarts_dead_worker_after_backoff(monkeypatch):
    monkeypatch.setattr(
        manager_module.settings.runtime,
        "model_worker_restart_max_attempts",
        3,
    )
    monkeypatch.setattr(
        manager_module.settings.runtime,
        "model_worker_restart_backoff_seconds",
        2.0,
    )
    monkeypatch.setattr(
        manager_module.settings.runtime,
        "model_worker_restart_max_backoff_seconds",
        30.0,
    )
    monkeypatch.setattr(
        manager_module.settings.runtime,
        "model_worker_ready_timeout_seconds",
        10.0,
    )
    dead_worker = FakeWorker(running=False, alive=False)
    replacement = FakeWorker(running=True, alive=True)
    manager = _manager_with_worker(dead_worker)
    manager.infer_queues["test-model"] = queue.Queue()
    manager.infer_queues["test-model"].put({"request_id": "stale-1"})
    manager.infer_queues["test-model"].put({"request_id": "stale-2"})
    alerts = []
    monkeypatch.setattr(manager, "_notify_runtime_alert", lambda *args: alerts.append(args))

    def start_replacement(_model_cfg):
        manager._workers["test-model"] = replacement
        return True

    monkeypatch.setattr(manager, "_start_one", start_replacement)

    manager._watchdog_tick(now=100.0)
    state = manager._worker_states["test-model"]
    assert state.next_restart_at == 102.0
    assert state.restart_attempts == 0
    assert manager.list_running() == []
    assert manager._workers["test-model"] is dead_worker

    manager._watchdog_tick(now=101.0)
    assert dead_worker.stop_calls == 0

    manager._watchdog_tick(now=102.0)
    assert dead_worker.stop_calls == 1
    assert manager._workers["test-model"] is replacement
    assert manager.infer_queues["test-model"].empty() is True
    assert state.restart_attempts == 1
    assert state.ready_deadline == 112.0

    manager._watchdog_tick(now=103.0)
    assert manager.list_running() == ["test-model"]
    assert state.ready_deadline == 0.0
    assert alerts[0][2] == "模型 Worker 退出"


def test_watchdog_stops_retrying_and_alerts_once_when_attempts_exhausted(monkeypatch):
    monkeypatch.setattr(
        manager_module.settings.runtime,
        "model_worker_restart_max_attempts",
        1,
    )
    manager = _manager_with_worker(FakeWorker(running=False, alive=False))
    manager._worker_states["test-model"].restart_attempts = 1
    alerts = []
    monkeypatch.setattr(manager, "_notify_runtime_alert", lambda *args: alerts.append(args))

    manager._watchdog_tick(now=200.0)
    manager._watchdog_tick(now=201.0)

    state = manager._worker_states["test-model"]
    assert state.exhausted is True
    assert state.next_restart_at == 0.0
    assert [item[2] for item in alerts] == ["模型 Worker 重启耗尽"]
    assert manager.runtime_status()["models"][0]["status"] == "exhausted"
