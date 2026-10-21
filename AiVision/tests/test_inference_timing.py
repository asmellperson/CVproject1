"""推理分段计时、完整帧处理时间及摄像头统计清理的回归验证。"""

import json
import queue
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    # 计时测试不访问数据库，独立运行时也不依赖本机部署凭据。
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test",
        "MYSQL_DB_PASSWORD": "test", "MYSQL_DB_NAME": "test",
        "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)

    from AiVision.features._shared.consumer import BaseFunctionConsumer
    from AiVision.inference.base_worker import BaseModelWorker

    class Clock:
        now = 100.0

        def advance(self, seconds):
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr("time.monotonic", lambda: clock.now)
    monkeypatch.setattr("time.perf_counter", lambda: clock.now)

    class Consumer(BaseFunctionConsumer):
        def _process(self, frame, camera_id):
            clock.advance(0.020)
            return False, {}

        def post_process(self, camera_id, result):
            clock.advance(0.006)
            return self.frame_cache[camera_id]

    class Worker(BaseModelWorker):
        def load_model(self):
            return None

        def infer(self, model, frame, task):
            clock.advance(0.020)
            if task.get("fail"):
                raise RuntimeError("测试模型异常")
            return []

    consumer = Consumer(
        spec=SimpleNamespace(name="timing"), infer_dict={}, result_queue=queue.Queue(),
        latest_frames={}, is_camera_active=lambda _: True,
    )
    consumer.config_cache[7] = {"shm_name": "camera_7", "cap_interval": 0.1}
    worker = Worker.__new__(Worker)
    worker.model_name = "test_model"
    return SimpleNamespace(consumer=consumer, worker=worker, clock=clock)


@pytest.mark.parametrize("fail", [False, True])
def test_sync_separates_input_wait_execution_and_result_return(runtime, fail):
    consumer, worker, clock = runtime.consumer, runtime.worker, runtime.clock
    # 通过真实请求登记、结果匹配和注销路径，模拟输入、执行和回传的独立延迟。
    consumer.result_router._state = "running"

    class Transport:
        def put(self, task, timeout):
            clock.advance(0.004)
            result = worker._execute_task(None, task)
            clock.advance(0.006)
            consumer.result_router._route(result)

    consumer.infer_dict["test_model"] = Transport()
    result = consumer.dispatch_inference_sync(7, "test_model", np.zeros((4, 4, 3)), {"fail": fail})
    assert result["status"] == ("error" if fail else "ok")
    assert result["detections"] == []
    target = consumer.inference_status()["targets"][0]
    assert target["last_outcome"]["timing_ms"] == {
        "input_wait": 4.0, "worker": 20.0, "result_return": 6.0, "round_trip": 30.0,
    }
    assert target["counts"] == {result["status"]: 1}
    assert consumer.result_router.snapshot()["pending_count"] == 0
    json.dumps(consumer.inference_status(), allow_nan=False)


def test_unavailable_model_does_not_fabricate_worker_timing(runtime):
    consumer = runtime.consumer
    result = consumer.dispatch_inference_sync(7, "missing", np.zeros((4, 4, 3)))
    assert result["status"] == "unavailable"
    assert consumer.inference_status()["targets"][0]["last_outcome"]["timing_ms"] == {
        "input_wait": None, "worker": None, "result_return": None, "round_trip": 0.0,
    }


def test_worker_without_submission_clock_keeps_input_wait_unknown(runtime):
    result = runtime.worker._execute_task(None, {"frame": np.zeros((4, 4, 3))})
    assert result["input_wait_ms"] is None
    assert result["inference_ms"] == 20.0
    assert result["completed_at_monotonic"] == pytest.approx(100.020)


def test_frame_loop_records_actual_stages_and_preserves_unlocked_callback(runtime, monkeypatch):
    consumer, clock = runtime.consumer, runtime.clock

    class Frames(dict):
        def get(self, key):
            clock.advance(0.003)
            return np.zeros((4, 4, 3))

    def active(key):
        clock.advance(0.002)
        return True

    def roi(camera_id, frame):
        clock.advance(0.009)
        return frame

    def after(camera_id, result):
        assert not consumer._camera_state_lock._is_owned()
        clock.advance(0.002)
        consumer.running = False

    consumer.latest_frames = Frames()
    consumer.is_camera_active = active
    monkeypatch.setattr(consumer, "_should_process_now", lambda *_: True)
    monkeypatch.setattr(consumer, "_get_roi", roi)
    monkeypatch.setattr(consumer, "_frame_changed", lambda *_: True)
    monkeypatch.setattr(consumer, "_handle_alarm", lambda *_: clock.advance(0.001))
    monkeypatch.setattr(consumer, "_after_process", after)
    monkeypatch.setattr("time.sleep", lambda _: None)
    consumer.running = True
    consumer._run()

    timing = consumer._last_frame_timings[7]
    assert timing["interval_ms"] is None
    assert {key: timing[key] for key in (
        "state_check_ms", "frame_read_ms", "prepare_ms", "process_ms",
        "post_process_ms", "publish_alarm_ms", "after_process_ms", "total_ms",
    )} == {
        "state_check_ms": 2.0, "frame_read_ms": 3.0, "prepare_ms": 9.0, "process_ms": 20.0,
        "post_process_ms": 6.0, "publish_alarm_ms": 1.0, "after_process_ms": 2.0, "total_ms": 43.0,
    }
    consumer.running = True
    clock.advance(1.0)
    consumer._run()
    assert consumer._last_frame_timings[7]["interval_ms"] == 1043.0


def test_timing_snapshots_are_independent_and_camera_removal_clears_them(runtime):
    consumer = runtime.consumer
    consumer.dispatch_inference_sync(7, "missing", np.zeros((4, 4, 3)))
    consumer._record_frame_timing(7, {"start": 100.0, "process": 100.020})
    snapshot = consumer.inference_status()
    snapshot["targets"][0]["last_outcome"]["timing_ms"]["round_trip"] = 999.0
    snapshot["targets"][0]["last_frame_timing"]["process_ms"] = 999.0
    target = consumer.inference_status()["targets"][0]
    assert target["last_outcome"]["timing_ms"]["round_trip"] == 0.0
    assert target["last_frame_timing"]["process_ms"] == 20.0

    consumer.config_cache.pop(7)
    consumer._clear_camera_state(7, "camera_7")
    consumer._record_frame_timing(7, {"start": 101.0, "process": 101.020})
    assert consumer.inference_status()["targets"] == []
    assert consumer._last_frame_timings == {}
    assert consumer._last_frame_started_at == {}


def test_submitted_requests_match_their_camera_when_resolved_out_of_order(runtime):
    from AiVision.inference.contracts import build_inference_result

    consumer = runtime.consumer
    consumer.result_router._state = "running"
    tasks = []
    consumer.infer_dict["test_model"] = SimpleNamespace(put=lambda task, timeout: tasks.append(task))
    first = consumer.submit_inference(7, "test_model", np.zeros((4, 4, 3)))
    second = consumer.submit_inference(8, "test_model", np.zeros((4, 4, 3)))
    assert consumer.result_router.snapshot()["pending_count"] == 2
    for request, task in ((second, tasks[1]), (first, tasks[0])):
        consumer.result_router._route(build_inference_result(
            task, status="ok", detections=[{"camera": task["camera_id"]}],
        ))
        result = consumer.resolve_inference(request)
        assert result["detections"] == [{"camera": request.camera_id}]
    assert consumer.result_router.snapshot()["pending_count"] == 0


def test_cancel_removes_registration_and_discards_late_result(runtime):
    from AiVision.inference.contracts import build_inference_result

    consumer = runtime.consumer
    consumer.result_router._state = "running"
    tasks = []
    consumer.infer_dict["test_model"] = SimpleNamespace(put=lambda task, timeout: tasks.append(task))
    request = consumer.submit_inference(7, "test_model", np.zeros((4, 4, 3)))
    consumer.cancel_inference(request)
    consumer.result_router._route(build_inference_result(tasks[0], status="ok"))
    assert consumer.result_router.snapshot()["pending_count"] == 0
    assert consumer.result_router.snapshot()["orphan_count"] == 1
    assert consumer.resolve_inference(request)["status"] == "unavailable"


def test_submission_failure_unregisters_request(runtime):
    consumer = runtime.consumer
    consumer.result_router._state = "running"

    def fail(task, timeout):
        raise OSError("测试管道故障")

    consumer.infer_dict["test_model"] = SimpleNamespace(put=fail)
    with pytest.raises(OSError, match="测试管道故障"):
        consumer.submit_inference(7, "test_model", np.zeros((4, 4, 3)))
    assert consumer.result_router.snapshot()["pending_count"] == 0


def test_parallel_requests_share_their_original_timeout_budget(runtime, monkeypatch):
    from AiVision.inference.contracts import build_inference_result

    consumer, clock = runtime.consumer, runtime.clock
    consumer.result_router._state = "running"
    consumer.infer_dict["test_model"] = SimpleNamespace(put=lambda *args, **kwargs: None)
    requests = [consumer.submit_inference(camera, "test_model", np.zeros((4, 4, 3))) for camera in (7, 8, 9)]
    clock.advance(0.5)
    waits = []

    def wait(pending, timeout):
        waits.append(timeout)
        clock.advance(timeout)
        return build_inference_result(pending.identity, status="timeout", error_code="inference_timeout")

    monkeypatch.setattr(consumer.result_router, "wait", wait)
    for request in requests:
        assert consumer.resolve_inference(request)["status"] == "timeout"
    assert waits == pytest.approx([0.3, 0.0, 0.0])
    assert clock.now == pytest.approx(100.8)
    assert consumer.result_router.snapshot()["pending_count"] == 0
