from contextlib import contextmanager
from datetime import datetime, timezone
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import requests

from auth.auth import get_current_user
from AiVision.api.routes import security_inspection as api
from AiVision.features.security_inspection import runtime as module
from AiVision.features.security_inspection.runtime import InspectionRuntime
from AiVision.features.security_inspection.schema import VlmHealth, VlmSettings
from AiVision.features.security_inspection.vlm import HEALTH_CHECK_TIMEOUT_SEC, VlmClient
from AiVision.tests.test_security_inspection import task, verdict, wait_for


@pytest.mark.parametrize(
    "code, models, reachable",
    [
        (200, [{"id": "fuda-qwen36-27b"}], True),
        (200, [{"id": "other-model"}], False),
        (401, [], False),
        (503, [], False),
        (200, [{}], False),
    ],
)
def test_health_probe_checks_configured_model_and_auth_without_inference(monkeypatch, code, models, reachable):
    calls = []

    @contextmanager
    def get(url, **kwargs):
        calls.append((url, kwargs))
        yield SimpleNamespace(status_code=code, json=lambda: {"data": models})

    monkeypatch.setenv("SECURITY_VLM_API_KEY", "test-key")
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: pytest.fail("健康检查不生成内容"))
    settings = VlmSettings()
    health = VlmClient().check_health(settings)
    assert health.reachable is reachable
    assert health.last_success is None
    assert bool(health.last_error) is not reachable
    assert calls[0][0] == settings.base_url + "/models"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0][1]["timeout"] == (HEALTH_CHECK_TIMEOUT_SEC, HEALTH_CHECK_TIMEOUT_SEC)
    assert calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("error", [requests.ConnectionError("connection refused"), requests.Timeout("timed out")])
def test_health_probe_reports_connection_failures(monkeypatch, error):
    def get(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(requests, "get", get)
    health = VlmClient().check_health(VlmSettings())
    assert health.reachable is False
    assert health.last_error == (
        "千问接口连接或响应超时" if isinstance(error, requests.Timeout) else "无法连接千问接口，请检查模型服务和地址"
    )


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now[0]))

    def advance(runtime, seconds):
        with runtime._condition:
            now[0] += seconds
            runtime._condition.notify_all()

    return now, advance


def test_startup_probe_is_async_and_outage_rejects_without_queue_growth(clock):
    entered, release = threading.Event(), threading.Event()
    completed, checks = [], []

    def check(_settings):
        checks.append(clock[0][0])
        entered.set()
        assert release.wait(2)
        return VlmHealth(reachable=False, last_error="connection refused")

    runtime = InspectionRuntime(
        lambda *args: completed.append(args),
        SimpleNamespace(check_health=check, judge=lambda *_: pytest.fail("不可用时不请求模型")),
    )
    runtime.start(VlmSettings())
    try:
        assert entered.wait(2)
        status = runtime.status("general_electric")
        assert status["running"] and status["vlm"]["checking"]
        assert status["vlm"]["reachable"] is None and status["vlm"]["last_success"] is None
        runtime.submit(task())
        assert runtime.status("general_electric")["queue"] == 0
        release.set()
        wait_for(lambda: runtime.health_status().circuit_state == "open")
        for index in range(100):
            runtime.submit(task(session_id=f"outage-{index}"))
        assert len(completed) == 101 and all(item[1] is None and item[2] for item in completed)
        assert runtime.status("general_electric")["queue"] == 0
        assert checks == [100.0]
        for delay in (5, 10, 20, 40, 60, 60):
            assert runtime.health_status().retry_after_sec == delay
            before = len(checks)
            clock[1](runtime, delay)
            wait_for(lambda: len(checks) == before + 1 and not runtime.health_status().checking)
        assert checks == [100.0, 105.0, 115.0, 135.0, 175.0, 235.0, 295.0]
    finally:
        release.set()
        runtime.stop()
    assert not runtime._health_thread.is_alive()


def test_consecutive_failures_drain_queue_and_half_open_allows_only_one_trial(clock):
    entered, release = threading.Event(), threading.Event()
    trial_entered, trial_release = threading.Event(), threading.Event()
    completed, calls = [], []
    mode = ["fail"]

    def judge(*_args):
        calls.append(mode[0])
        if len(calls) == 1:
            entered.set()
            assert release.wait(2)
        if mode[0] == "trial":
            trial_entered.set()
            assert trial_release.wait(2)
        if mode[0] != "success":
            raise ValueError("private general_electric image description")
        return verdict(), 0.1

    runtime = InspectionRuntime(
        lambda *args: completed.append(args),
        SimpleNamespace(check_health=lambda _: VlmHealth(reachable=True), judge=judge),
    )
    runtime.start(VlmSettings(max_concurrent=1))
    try:
        wait_for(lambda: runtime.health_status().reachable is True)
        runtime.submit(task(session_id="first"))
        assert entered.wait(2)
        for index in range(8):
            runtime.submit(task(session_id=f"queued-{index}"))
        release.set()
        wait_for(lambda: len(completed) == 9 and runtime.status("general_electric")["active"] == 0)
        health = runtime.health_status()
        assert len(calls) == 3 and health.consecutive_failures == 3
        assert health.circuit_state == "open" and health.retry_after_sec == 5
        assert "private" not in health.last_error
        assert runtime.status("research_institute")["error"] is None
        assert runtime.status("general_electric")["queue"] == 0

        clock[1](runtime, 5)
        wait_for(lambda: runtime.health_status().circuit_state == "half_open")
        assert runtime.health_status().last_success is None
        mode[0] = "trial"
        runtime.submit(task(session_id="trial"))
        assert trial_entered.wait(2)
        for index in range(20):
            runtime.submit(task(session_id=f"blocked-{index}"))
        assert len(calls) == 4 and runtime.status("general_electric")["queue"] == 0
        # /models 持续正常也不能替代半开状态的真实推理验证。
        clock[1](runtime, 30)
        wait_for(lambda: not runtime.health_status().checking)
        assert runtime.health_status().circuit_state == "half_open"
        trial_release.set()
        wait_for(lambda: runtime.health_status().circuit_state == "open")
        assert runtime.health_status().retry_after_sec == 10
        clock[1](runtime, 10)
        wait_for(lambda: runtime.health_status().circuit_state == "half_open")
        mode[0] = "success"
        runtime.submit(task(session_id="recovery"))
        wait_for(lambda: runtime.health_status().circuit_state == "closed")
        health = runtime.health_status()
        assert health.reachable is True and health.last_success is not None
        assert health.consecutive_failures == 0 and health.last_error is None
        runtime.submit(task(session_id="normal-1"))
        runtime.submit(task(session_id="normal-2"))
        wait_for(lambda: len(calls) == 7)
    finally:
        release.set()
        trial_release.set()
        runtime.stop()


def test_reconfigure_ignores_old_health_probe_and_checks_new_settings():
    entered, release = threading.Event(), threading.Event()
    checked = []

    def check(settings):
        checked.append(settings.model)
        if len(checked) == 1:
            entered.set()
            assert release.wait(2)
            return VlmHealth(reachable=True)
        return VlmHealth(reachable=False, last_error="new model unavailable")

    runtime = InspectionRuntime(lambda *_: None, SimpleNamespace(check_health=check))
    runtime.start(VlmSettings())
    try:
        assert entered.wait(2)
        runtime.configure(VlmSettings(model="new-model"))
        assert runtime.health_status().reachable is None
        release.set()
        wait_for(lambda: runtime.health_status().circuit_state == "open")
        assert checked == ["fuda-qwen36-27b", "new-model"]
        assert runtime.health_status().reachable is False
        assert runtime.health_status().last_error == "new model unavailable"
    finally:
        release.set()
        runtime.stop()


def test_periodic_probe_detects_outage_without_any_session(clock):
    checks = []

    def check(_settings):
        checks.append(clock[0][0])
        return (
            VlmHealth(reachable=True)
            if len(checks) == 1
            else VlmHealth(
                reachable=False,
                last_error="connection refused",
            )
        )

    runtime = InspectionRuntime(lambda *_: None, SimpleNamespace(check_health=check))
    runtime.start(VlmSettings())
    try:
        wait_for(lambda: runtime.health_status().reachable is True)
        clock[1](runtime, module.HEALTH_CHECK_INTERVAL_SEC)
        wait_for(lambda: runtime.health_status().circuit_state == "open")
        assert checks == [100.0, 130.0]
        assert runtime.health_status().reachable is False
    finally:
        runtime.stop()


def test_old_inflight_success_cannot_close_newly_opened_circuit():
    entered = threading.Barrier(5)
    fail_release, success_release = threading.Event(), threading.Event()
    completed = []

    def judge(frames, _settings):
        entered.wait(2)
        if frames[0] == b"success":
            assert success_release.wait(2)
            return verdict(), 0.1
        assert fail_release.wait(2)
        raise RuntimeError("model unavailable")

    runtime = InspectionRuntime(
        lambda *args: completed.append(args),
        SimpleNamespace(
            check_health=lambda _: VlmHealth(reachable=True),
            judge=judge,
        ),
    )
    runtime.start(VlmSettings(max_concurrent=4))
    try:
        wait_for(lambda: runtime.health_status().reachable is True)
        for index in range(4):
            runtime.submit(task(session_id=str(index), frames=[b"success" if index == 3 else b"fail", b"b"]))
        entered.wait(2)
        fail_release.set()
        wait_for(lambda: runtime.health_status().circuit_state == "open")
        success_release.set()
        wait_for(lambda: len(completed) == 4)
        assert runtime.health_status().circuit_state == "open"
        assert runtime.health_status().last_success is None
    finally:
        fail_release.set()
        success_release.set()
        runtime.stop()


def test_reconfigure_discards_queued_and_inflight_old_model_results():
    entered, release = threading.Event(), threading.Event()
    completed, calls = [], []

    def judge(_frames, settings):
        calls.append(settings.model)
        entered.set()
        assert release.wait(2)
        return verdict(False), 0.1

    runtime = InspectionRuntime(
        lambda *args: completed.append(args),
        SimpleNamespace(check_health=lambda _: VlmHealth(reachable=True), judge=judge),
    )
    runtime.start(VlmSettings(max_concurrent=1))
    try:
        wait_for(lambda: runtime.health_status().reachable is True)
        runtime.submit(task(session_id="inflight"))
        assert entered.wait(2)
        runtime.submit(task(session_id="queued"))
        runtime.configure(VlmSettings(model="new-model", max_concurrent=1))
        release.set()
        wait_for(lambda: len(completed) == 2)
        assert calls == ["fuda-qwen36-27b"]
        assert all(item[1] is None and "模型设置已变更" in item[2] for item in completed)
        assert runtime.health_status().last_success is None
    finally:
        release.set()
        runtime.stop()


def test_storage_and_queue_timeout_do_not_trip_model_circuit():
    recorded = []

    def save(*args):
        recorded.append(args)
        raise RuntimeError("database unavailable")

    runtime = InspectionRuntime(
        save,
        SimpleNamespace(
            check_health=lambda _: VlmHealth(reachable=True),
            judge=lambda *_: (verdict(), 0.1),
        ),
    )
    runtime.start(VlmSettings())
    try:
        wait_for(lambda: runtime.health_status().reachable is True)
        runtime.submit(task(queued_at=0))
        wait_for(lambda: len(recorded) == 1)
        assert recorded[0][2] == "安检任务排队超时"
        assert runtime.health_status().last_success is None
        runtime.submit(task(session_id="storage-failure"))
        wait_for(lambda: len(recorded) == 2)
        health = runtime.health_status()
        assert health.last_success is not None and health.consecutive_failures == 0
        assert health.circuit_state == "closed" and health.last_error is None
    finally:
        runtime.stop()


def test_stop_during_probe_does_not_publish_late_health_result():
    entered, release = threading.Event(), threading.Event()

    def check(_settings):
        entered.set()
        assert release.wait(2)
        return VlmHealth(reachable=True)

    runtime = InspectionRuntime(lambda *_: None, SimpleNamespace(check_health=check))
    runtime.start(VlmSettings())
    assert entered.wait(2)
    stopper = threading.Thread(target=runtime.stop)
    stopper.start()
    wait_for(lambda: not runtime.status("general_electric")["running"])
    release.set()
    stopper.join(2)
    assert not stopper.is_alive() and not runtime._health_thread.is_alive()
    assert runtime.health_status().reachable is None
    assert not runtime.health_status().checking


@pytest.mark.parametrize("has_consumer", [False, True])
def test_saving_settings_checks_health_even_when_detection_is_stopped(has_consumer):
    saved, checks = [], []

    def check(settings):
        checks.append(settings.model)
        return VlmHealth(reachable=False, last_error="connection refused")

    runtime = InspectionRuntime(lambda *_: None, SimpleNamespace(check_health=check))
    consumer = SimpleNamespace(running=False, vlm_runtime=runtime) if has_consumer else None
    service = SimpleNamespace(save_settings=saved.append, check_model=check)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    app.dependency_overrides[api.get_service] = lambda: service
    app.dependency_overrides[api.get_consumer] = lambda: consumer
    with TestClient(app) as client:
        response = client.put("/api/security-inspection/settings", json=VlmSettings().model_dump())
        assert response.status_code == 200
        assert response.json()["vlm"]["reachable"] is False
        assert response.json()["vlm"]["last_error"] == "connection refused"
        assert response.json()["settings"]["model"] == "fuda-qwen36-27b"
        assert checks == ["fuda-qwen36-27b"] and len(saved) == 1
        response = client.get("/api/security-inspection/status?department=general_electric")
        assert response.status_code == 200 and response.json()["running"] is False


def test_status_api_serializes_real_inference_success_time():
    runtime = InspectionRuntime(lambda *_: None)
    timestamp = datetime.now(timezone.utc)
    runtime._health = VlmHealth(reachable=True, last_success=timestamp)
    consumer = SimpleNamespace(running=True, vlm_runtime=runtime)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    app.dependency_overrides[api.get_consumer] = lambda: consumer
    with TestClient(app) as client:
        response = client.get("/api/security-inspection/status?department=general_electric")
    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["vlm"]["last_success"]) == timestamp
