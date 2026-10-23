"""AGV 请求进度、真实回传内容与平台访问权限的回归验证。"""
import asyncio
import signal
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import requests
import uvicorn
from fastapi.testclient import TestClient


@pytest.fixture
def agv_status(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "tests", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "tests", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.api import app as app_module, deps
    from AiVision.api.routes import agv_person_check as route
    from AiVision.features.agv_person_check import http_adapter, service as service_module
    from AiVision.features.agv_person_check.schema import AgvPersonCheckValueSchema, PersonCheckResult

    service = service_module.AgvPersonCheckService()
    config = AgvPersonCheckValueSchema(
        sample_count=2, cap_interval=.05,
        http={"present_value": 1, "absent_value": 0},
    ).model_dump()
    camera = {"camera_id": 1, "shm_name": "camera_1", "name": "AGV 入口", "enabled": True,
              "department": "general_electric", "functions": {"agv_person_check": True}}
    user = {"role": "viewer", "departments": ["general_electric"],
            "feature_access": {"general_electric": ["agv_person_check"]}}
    consumer = SimpleNamespace(service=service, running=True, is_camera_active=Mock(return_value=True),
                               submit=lambda key: service.submit(1, key, config))
    orchestrator = SimpleNamespace(consumers={"agv_person_check": consumer})
    manager = SimpleNamespace(get_camera=lambda key: camera if key == camera["shm_name"] else None)
    monkeypatch.setattr(app_module, "get_current_user_from_request", lambda request: user)
    app = app_module.create_app()
    app.dependency_overrides.update({
        deps.get_camera_config_manager: lambda: manager,
        deps.get_current_orchestrator: lambda: orchestrator,
        deps.get_optional_orchestrator: lambda: orchestrator,
    })
    client = TestClient(app)

    def submit():
        return service.submit(1, "camera_1", config)

    def complete(request, present=False, during_sample=None):
        def sample(item):
            assert item is request
            if during_sample:
                during_sample(item)
            return np.zeros((2, 2, 3), dtype=np.uint8), PersonCheckResult(person_present=present)

        service.run(sample, lambda: not request.future.done(), lambda *args: None)

    yield SimpleNamespace(service=service, service_module=service_module, config=config, camera=camera, user=user,
                          consumer=consumer, orchestrator=orchestrator, route=route, app_module=app_module,
                          client=client, submit=submit, complete=complete, http_adapter=http_adapter,
                          PersonCheckError=service_module.PersonCheckError)
    service.stop()
    client.close()


def status(agv):
    response = agv.client.get("/api/agv-person-check/cameras/camera_1/status")
    assert response.status_code == 200, response.text
    return response.json()


def test_status_query_does_not_start_detection_or_wait_for_service_lock(agv_status):
    agv = agv_status
    with ThreadPoolExecutor(max_workers=1) as executor:
        with agv.service._lock:
            result = executor.submit(status, agv).result(timeout=2.)
    assert result == {"camera_key": "camera_1", "state": "waiting", "active_request": None, "latest_result": None}
    assert agv.service.detecting_camera_ids() == set()


@pytest.mark.parametrize("present, samples", [(True, 1), (False, 2)])
def test_real_sampling_progress_and_latest_result_remain_after_release(agv_status, present, samples):
    agv = agv_status
    request = agv.submit()
    initial = status(agv)
    assert initial["state"] == "detecting"
    assert initial["active_request"]["sample_count"] == 0
    assert initial["active_request"]["sample_target"] == 2
    observed = []
    agv.complete(request, present=present, during_sample=lambda _: observed.append(status(agv)))
    assert [item["active_request"]["sample_count"] for item in observed] == list(range(samples))
    assert request.future.result().person_present is present
    finished = status(agv)
    assert finished["state"] == "returning"
    latest = finished["latest_result"]
    assert latest["state"] == "completed"
    assert latest["person_present"] is present
    assert latest["sample_count"] == samples
    assert latest["finished_at"] >= latest["started_at"]
    assert latest["duration_seconds"] >= 0
    agv.service.release(request)
    waiting = status(agv)
    assert waiting["state"] == "waiting"
    assert waiting["active_request"] is None
    assert waiting["latest_result"] == latest
    following = agv.submit()
    assert status(agv)["active_request"]["request_id"] == following.request_id
    assert status(agv)["latest_result"] == latest


@pytest.mark.parametrize("body_template, expected", [
    ({"result": "${result}", "camera": "${camera_key}"}, {"result": 0, "camera": "camera_1"}),
    ("${result}", False), ("${result}", ""),
])
def test_sync_monitor_stores_exact_public_response_including_false_zero_and_empty_text(agv_status, monkeypatch, body_template, expected):
    agv = agv_status
    agv.config["http"]["body_template"] = body_template
    agv.config["http"]["absent_value"] = expected if not isinstance(expected, dict) else 0

    def submit(key):
        request = agv.service.submit(1, key, agv.config)
        agv.complete(request)
        return request

    agv.consumer.submit = submit
    response = agv.client.post("/api/public/agv/person-check/camera_1")
    assert response.status_code == 200
    assert response.json() == expected
    latest = status(agv)["latest_result"]
    assert latest["response_body"] == expected
    assert type(latest["response_body"]) is type(expected)
    assert latest["delivery_state"] == "ready"
    assert latest["delivery_status_code"] == 200
    assert latest["person_present"] is False


@pytest.mark.parametrize("failure", [None, "http", "network", "unexpected"])
def test_callback_progress_delivery_status_and_judgment_are_separate(agv_status, monkeypatch, failure):
    agv = agv_status
    agv.config["http"].update(mode="callback", callback_url="https://example.invalid/callback",
                             headers={"Authorization": "test-credential"})
    captured = []

    def submit(key):
        request = agv.service.submit(1, key, agv.config)
        agv.complete(request)
        return request

    def callback(config, body):
        captured.append(status(agv))
        assert body == {"result": 0}
        if failure == "http":
            raise agv.http_adapter.CallbackError("AGV 回调返回非成功状态 HTTP 502", 502)
        if failure == "network":
            raise agv.http_adapter.CallbackError("AGV 回调通信失败：Timeout")
        if failure == "unexpected":
            raise RuntimeError("测试回调异常")
        return 204

    agv.consumer.submit = submit
    monkeypatch.setattr(agv.route, "send_callback", callback)
    response = agv.client.post("/api/public/agv/person-check/camera_1")
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert captured[0]["state"] == "returning"
    assert captured[0]["latest_result"]["delivery_state"] == "sending"
    final = status(agv)
    assert final["state"] == "waiting"
    latest = final["latest_result"]
    assert latest["request_id"] == response.json()["request_id"]
    assert latest["person_present"] is False
    assert latest["state"] == "completed"
    assert latest["response_body"] == {"result": 0}
    assert latest["delivery_state"] == ("failed" if failure else "succeeded")
    assert latest["delivery_status_code"] == (502 if failure == "http" else None if failure else 204)
    assert bool(latest["delivery_error"]) is bool(failure)
    assert "example.invalid" not in str(final) and "test-credential" not in str(final)


@pytest.mark.parametrize("code", ["timeout", "inference_failed", "unavailable", "cancelled"])
def test_failed_detection_is_never_reported_as_absent(agv_status, code):
    agv = agv_status
    request = agv.submit()

    def sample(_):
        raise agv.PersonCheckError(code, "本次未获得有效判定")

    agv.service.run(sample, lambda: not request.future.done(), lambda *args: None)
    with pytest.raises(agv.PersonCheckError):
        request.future.result()
    agv.service.release(request)
    result = status(agv)["latest_result"]
    assert result["person_present"] is None
    assert result["error_code"] == code
    assert result["state"] == ("cancelled" if code == "cancelled" else "error")
    assert result["delivery_state"] == "not_sent"
    assert result["response_body"] is None


def test_api_wait_timeout_records_http_error_and_clears_active_request(agv_status, monkeypatch):
    agv = agv_status

    async def timeout(_):
        raise agv.PersonCheckError("timeout", "检测超时，未获得有效结果")

    monkeypatch.setattr(agv.route, "_wait_result", timeout)
    response = agv.client.post("/api/public/agv/person-check/camera_1")
    assert response.status_code == 504
    value = status(agv)
    assert value["state"] == "waiting"
    assert value["latest_result"]["person_present"] is None
    assert value["latest_result"]["error_code"] == "timeout"
    assert value["latest_result"]["response_body"] == response.json()
    assert value["latest_result"]["delivery_status_code"] == 504


def test_callback_detection_timeout_never_sends_absent_payload(agv_status, monkeypatch):
    agv = agv_status
    agv.config["http"].update(mode="callback", callback_url="https://example.invalid/callback")
    request = agv.submit()
    agv.service.fail(request, agv.PersonCheckError("timeout", "检测超时"))
    callback = Mock()
    monkeypatch.setattr(agv.route, "send_callback", callback)
    asyncio.run(agv.route._deliver_callback(agv.consumer, request))
    callback.assert_not_called()
    assert status(agv)["latest_result"]["delivery_state"] == "not_sent"


def test_busy_rejection_cannot_replace_inflight_request(agv_status):
    agv = agv_status
    request = agv.submit()
    response = agv.client.post("/api/public/agv/person-check/camera_1")
    assert response.status_code == 409
    assert status(agv)["active_request"]["request_id"] == request.request_id
    assert status(agv)["latest_result"] is None


def test_snapshots_are_detached_and_late_old_delivery_cannot_overwrite_new_result(agv_status):
    agv = agv_status
    first = agv.submit()
    agv.complete(first)
    body = {"result": [0]}
    agv.service.monitor.delivery(first, state="ready", body=body)
    body["result"].append(1)
    _, snapshot = agv.service.monitor.status(1)
    snapshot.response_body["result"].append(2)
    assert status(agv)["latest_result"]["response_body"] == {"result": [0]}
    agv.service.release(first)
    second = agv.submit()
    agv.complete(second, present=True)
    agv.service.monitor.delivery(first, state="failed", error="旧回调失败")
    latest = status(agv)["latest_result"]
    assert latest["request_id"] == second.request_id
    assert latest["person_present"] is True
    assert latest["delivery_state"] == "pending"


@pytest.mark.parametrize("condition, expected", [
    ("camera_disabled", "disabled"), ("feature_disabled", "disabled"),
    ("stopped", "unavailable"), ("missing_consumer", "unavailable"), ("offline", "offline"),
])
def test_status_explains_camera_and_service_availability(agv_status, condition, expected):
    agv = agv_status
    if condition == "camera_disabled":
        agv.camera["enabled"] = False
    elif condition == "feature_disabled":
        agv.camera["functions"]["agv_person_check"] = False
    elif condition == "stopped":
        agv.consumer.running = False
    elif condition == "missing_consumer":
        agv.orchestrator.consumers.clear()
    else:
        agv.consumer.is_camera_active.return_value = False
    assert status(agv)["state"] == expected


def test_status_retains_real_authentication_department_and_feature_checks(agv_status, monkeypatch):
    agv = agv_status
    from auth.auth import AuthError

    def unauthenticated(_):
        raise AuthError("请登录")

    monkeypatch.setattr(agv.app_module, "get_current_user_from_request", unauthenticated)
    path = "/api/agv-person-check/cameras/camera_1/status"
    assert agv.client.get(path).status_code == 401
    monkeypatch.setattr(agv.app_module, "get_current_user_from_request", lambda _: agv.user)
    agv.user["departments"] = ["electronics_electrician"]
    assert agv.client.get(path).status_code == 403
    agv.user["departments"] = ["general_electric"]
    agv.user["feature_access"] = {"general_electric": []}
    assert agv.client.get(path).status_code == 403
    assert agv.client.get(path.replace("camera_1", "missing")).status_code == 404


@pytest.mark.parametrize("cleanup", ["camera", "stop"])
def test_camera_removal_and_stop_release_retained_status(agv_status, cleanup):
    agv = agv_status
    request = agv.submit()
    agv.complete(request)
    agv.service.release(request)
    if cleanup == "camera":
        agv.service.monitor.clear_camera(1)
    else:
        agv.service.stop()
    assert agv.service.monitor.status(1) == (None, None)


@pytest.mark.parametrize("code", [200, 204, 302, 500])
def test_callback_adapter_records_only_status_code_and_never_reads_remote_body(agv_status, monkeypatch, code):
    agv = agv_status
    from AiVision.features.agv_person_check.schema import HttpConfigSchema

    response = Mock(status_code=code)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(agv.http_adapter.requests, "request", Mock(return_value=response))
    config = HttpConfigSchema(mode="callback", callback_url="https://example.invalid/callback")
    if code < 300:
        assert agv.http_adapter.send_callback(config, {"result": 0}) == code
    else:
        with pytest.raises(agv.http_adapter.CallbackError) as caught:
            agv.http_adapter.send_callback(config, {"result": 0})
        assert caught.value.status_code == code
    response.json.assert_not_called()


@pytest.mark.parametrize("mode", ["sync", "callback"])
def test_server_shutdown_finishes_accepted_detection_and_callback_before_returning(agv_status, monkeypatch, mode):
    """用真实 HTTP 连接覆盖退出时的检测、响应和后台回调等待顺序。"""
    from AiVision.api.server import GracefulServer

    agv = agv_status
    agv.config["http"].update(mode=mode, callback_url="https://example.invalid/callback" if mode == "callback" else "")
    accepted = threading.Event()
    allow_sample = threading.Event()
    callback_entered = threading.Event()
    allow_callback = threading.Event()
    running = threading.Event()
    running.set()
    received = []

    def submit(key):
        request = agv.service.submit(1, key, agv.config)
        received.append(request)
        accepted.set()
        return request

    def sample(_):
        if not allow_sample.is_set():
            return None
        from AiVision.features.agv_person_check.schema import PersonCheckResult
        return np.zeros((2, 2, 3), dtype=np.uint8), PersonCheckResult(person_present=False)

    def callback(config, body):
        assert body == {"result": 0}
        callback_entered.set()
        assert allow_callback.wait(3), "测试必须释放回调"
        return 204

    agv.consumer.submit = submit
    monkeypatch.setattr(agv.route, "send_callback", callback)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{listener.getsockname()[1]}/api/public/agv/person-check/camera_1"
    server = GracefulServer(
        uvicorn.Config(agv.client.app, lifespan="off", access_log=False, timeout_graceful_shutdown=3),
        on_shutdown=lambda: agv.service.begin_shutdown(3),
    )
    with ThreadPoolExecutor(max_workers=3) as executor:
        worker = executor.submit(agv.service.run, sample, running.is_set, lambda *args: None)
        serving = executor.submit(server.run, sockets=[listener])
        try:
            deadline = time.monotonic() + 3
            while not server.started and not serving.done() and time.monotonic() < deadline:
                time.sleep(.01)
            assert server.started
            response = executor.submit(requests.post, url, timeout=5)
            assert accepted.wait(3)
            server.handle_exit(signal.SIGTERM, None)
            assert not serving.done()
            # 即使已有连接进入路由，也不能在停止通知之后登记新请求。
            rejected = agv.client.post("/api/public/agv/person-check/camera_1")
            assert rejected.status_code == 503
            assert "重试" in rejected.json()["detail"]
            assert len(received) == 1
            allow_sample.set()
            assert received[0].future.result(timeout=3).person_present is False
            if mode == "callback":
                assert callback_entered.wait(3)
                assert not serving.done(), "判定完成后仍须等待后台回调"
                assert agv.service.monitor.status(1)[0] is not None
                allow_callback.set()
            result = response.result(timeout=3)
            assert result.status_code == (202 if mode == "callback" else 200)
            if mode == "sync":
                assert result.json() == {"result": 0}
            serving.result(timeout=3)
            assert agv.service.wait_for_idle(0)
            latest = agv.service.monitor.status(1)[1]
            assert latest.delivery_state == ("succeeded" if mode == "callback" else "ready")
            assert latest.person_present is False
        finally:
            allow_sample.set()
            allow_callback.set()
            running.clear()
            server.should_exit = True
            agv.service.stop()
            worker.result(timeout=3)
            serving.result(timeout=5)
            listener.close()


def test_shutdown_deadline_is_not_extended_and_stop_never_creates_absent_result(agv_status):
    agv = agv_status
    request = agv.submit()
    agv.service.begin_shutdown(.03)
    deadline = agv.service._shutdown_deadline
    agv.service.begin_shutdown(10)
    assert agv.service._shutdown_deadline == deadline
    assert not agv.service.wait_for_idle(10)
    assert not request.future.done()
    agv.service.stop()
    with pytest.raises(agv.PersonCheckError, match="已停止") as caught:
        request.future.result()
    assert caught.value.code == "unavailable"
    with pytest.raises(agv.PersonCheckError):
        agv.submit()
    agv.service.start()
    following = agv.submit()
    agv.service.release(following)


def test_main_keeps_algorithm_and_manager_alive_until_http_finishes(agv_status, monkeypatch):
    """主入口必须先完成 HTTP 排空，再释放推理和跨进程共享资源。"""
    from AiVision import main
    from AiVision.api import server as server_module
    from AiVision.runtime import bootstrap, orchestrator as orchestrator_module

    events = []
    orchestrator = SimpleNamespace(
        start=lambda: events.append("start"),
        begin_shutdown=lambda: events.append("admission_closed"),
        stop=lambda: events.append("algorithm_stopped"),
    )

    class Server:
        def __init__(self, config, *, on_shutdown):
            assert config.timeout_graceful_shutdown > 0
            self.on_shutdown = on_shutdown

        def run(self):
            self.on_shutdown()
            assert "algorithm_stopped" not in events
            assert "manager_stopped" not in events
            events.append("http_finished")

    monkeypatch.setattr(main, "_load_env_file", lambda: None)
    monkeypatch.setattr(main, "_set_spawn_start_method", lambda: None)
    monkeypatch.setattr(main, "_configure_opencv_threads", lambda value: value)
    monkeypatch.setattr(main.mp, "Manager", lambda: SimpleNamespace(shutdown=lambda: events.append("manager_stopped")))
    monkeypatch.setattr(main.signal, "signal", lambda *args: None)
    monkeypatch.setattr(bootstrap, "bootstrap_database", lambda: None)
    monkeypatch.setattr(orchestrator_module, "init_orchestrator", lambda manager: orchestrator)
    monkeypatch.setattr(agv_status.app_module, "create_app", lambda: agv_status.client.app)
    monkeypatch.setattr(server_module, "GracefulServer", Server)
    monkeypatch.setattr("sys.argv", ["AiVision.main"])
    main.main()
    assert events == ["start", "admission_closed", "http_finished", "algorithm_stopped", "manager_stopped"]
