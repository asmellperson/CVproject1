"""多路在线检测在请求与原图之间保持绑定，慢路不会阻塞其他摄像头。"""
from queue import Full, Queue
from threading import Event
import time
from unittest.mock import Mock

import numpy as np
import pytest


@pytest.fixture
def consumer_factory(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "pipeline_test",
        "MYSQL_DB_PASSWORD": "pipeline_test", "MYSQL_DB_NAME": "pipeline_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "pipeline-test-signing-key-00000000",
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.core.cache import config_cache
    from AiVision.features.registry import get_spec

    def create(feature, camera_count=2):
        spec = get_spec(feature)
        config = spec.config_schema().value.model_dump()
        if feature == "tailgating":
            config.update(roi_pos=[[0, 0], [1, 0], [1, 1], [0, 1]], line_points=[[0.5, 0], [0.5, 1]])
        else:
            config["record_enabled"] = False
        cameras = {
            (i, feature): {**config, "shm_name": f"camera_{i}", "name": f"摄像头{i}",
                           "department": "general_electric", "enable": True, "camera_enable": True}
            for i in range(1, camera_count + 1)
        }
        monkeypatch.setattr(config_cache, "get_all_function_configs", lambda: cameras)
        monkeypatch.setattr(config_cache, "get_function_config", lambda i, f: cameras.get((i, f)))
        submitted, results = Queue(), Queue()
        frames = {f"camera_{i}": np.full((12, 16, 3), i, dtype=np.uint8) for i in range(1, camera_count + 1)}
        now = time.time()
        consumer = spec.consumer_cls(
            spec=spec, infer_dict={spec.required_models[0]: submitted}, result_queue=results,
            latest_frames=frames, latest_frame_times=dict.fromkeys(frames, now),
            is_camera_active=lambda _: True,
        )
        return consumer, cameras, submitted, results, frames, now

    return create


@pytest.mark.parametrize("feature", ["tailgating", "recognize_face"])
def test_a_ready_camera_publishes_while_the_first_request_is_pending(feature, consumer_factory, monkeypatch):
    from AiVision.features._shared import consumer as base_consumer
    from AiVision.inference.contracts import build_inference_result

    consumer, _, submitted, results, frames, captured_at = consumer_factory(feature, camera_count=3)
    # 固定轮询休眠即使很长，真实结果到达仍须立即推进，并补投第三路。
    monkeypatch.setattr(base_consumer, "_CAMERA_ROUND_POLL_SECONDS", 5.0)
    consumer.max_inflight = 2
    blocked_authorization = Event()
    release_authorization = Event()
    if feature == "recognize_face":
        def lookup(departments, *, on_sampled=None):
            blocked_authorization.set()
            release_authorization.wait(4)
            if on_sampled is not None:
                on_sampled()
            return {name: set() for name in departments}

        monkeypatch.setattr(consumer.library, "get_allowed_person_ids_by_department", lookup)
    published = Event()
    after_process = consumer._after_process

    def note_publish(camera_id, result):
        after_process(camera_id, result)
        if camera_id == 2:
            published.set()

    monkeypatch.setattr(consumer, "_after_process", note_publish)
    consumer.start()
    try:
        pending = submitted.get(timeout=1)
        ready = submitted.get(timeout=1)
        assert [pending["camera_id"], ready["camera_id"]] == [1, 2]
        if feature == "recognize_face":
            assert blocked_authorization.wait(1)
        original = frames["camera_2"]
        frames["camera_2"] = np.zeros_like(original)
        consumer.latest_frame_times["camera_2"] = captured_at + 0.2
        results.put(build_inference_result(ready, status="ok"))
        assert published.wait(0.7)
        assert submitted.get_nowait()["camera_id"] == 3
        assert consumer.get_monitor_status("camera_1") is None
        state = consumer.get_monitor_status("camera_2")
        assert state["count"] == 0 and state["updated_at_s"] == captured_at
        if feature == "tailgating":
            assert consumer._preview("camera_2").source.sampled_at == captured_at
            assert consumer.result_dict["camera_2"] is None
            preview = consumer.get_live_preview("camera_2", frames["camera_2"], now=captured_at + 0.2)
            assert preview.any()
        else:
            assert consumer._preview_frames["camera_2"].sampled_at == captured_at
    finally:
        release_authorization.set()
        consumer.stop()
    assert not consumer._samples


def test_pipeline_rotates_and_invalidates_requests_on_configuration_change(consumer_factory):
    from AiVision.inference.contracts import build_inference_result

    consumer, configs, submitted, _, _, _ = consumer_factory("tailgating", camera_count=6)
    consumer._load_initial_configs()
    consumer.result_router.start()
    consumer.running = True
    try:
        consumer._before_camera_round()
        assert [submitted.get_nowait()["camera_id"] for _ in range(4)] == [1, 2, 3, 4]
        canceled = consumer._samples[1].request
        configs[1, "tailgating"] = {**configs[1, "tailgating"], "threshold": 0.8}
        consumer.update_config(1)
        assert 1 not in consumer._samples and canceled.result["status"] == "unavailable"
        consumer._before_camera_round()
        assert submitted.get_nowait()["camera_id"] == 5
        assert set(consumer._samples) == {2, 3, 4, 5}
        sample = consumer._samples[2]
        sample.request.result = build_inference_result({}, status="ok")
        consumer._process(sample.region, 2)
        consumer._before_camera_round()
        assert submitted.get_nowait()["camera_id"] == 6
    finally:
        consumer.stop()


def test_pipeline_retries_a_dropped_input_without_publishing_model_failure(consumer_factory):
    from AiVision.core.settings import settings

    class FullQueue:
        timeout = None

        def put(self, task, timeout):
            self.timeout = timeout
            raise Full

    consumer, _, submitted, _, _, _ = consumer_factory("tailgating", camera_count=1)
    consumer._load_initial_configs()
    consumer.result_router.start()
    consumer.running = True
    full = FullQueue()
    consumer.infer_dict["yolo_human"] = full
    try:
        consumer._before_camera_round()
        assert not consumer._samples
        assert consumer.result_router.snapshot()["pending_count"] == 0
        assert full.timeout == settings.runtime.inference_queue_submit_wait_seconds
        assert consumer._queue_retry_at[1] > time.monotonic()

        consumer.infer_dict["yolo_human"] = submitted
        consumer._queue_retry_at[1] = time.monotonic() - 1
        consumer._before_camera_round()
        assert submitted.get_nowait()["camera_id"] == 1
        assert 1 in consumer._samples
    finally:
        consumer.stop()


def test_worker_does_not_run_expired_queued_frame(consumer_factory):
    from AiVision.inference.base_worker import BaseModelWorker

    class Worker(BaseModelWorker):
        load_model = Mock()
        infer = Mock(return_value=[])

    worker = Worker({}, {}, "test", "")
    now = time.monotonic()
    result = worker._execute_task(object(), {"deadline_at_monotonic": now - 1, "submitted_at_monotonic": now - 2})
    assert result["status"] == "timeout"
    assert result["input_wait_ms"] >= 2000
    worker.infer.assert_not_called()


def test_tailgating_uses_capture_time_for_tracking_gap(consumer_factory):
    from AiVision.features._shared.pipelined_consumer import CameraSample
    from AiVision.features._shared.consumer import SubmittedInference

    consumer, configs, _, _, frames, captured_at = consumer_factory("tailgating", camera_count=1)
    consumer._load_initial_configs()
    frame = frames["camera_1"]
    now = time.monotonic()
    request = SubmittedInference(1, "yolo_human", now, now + 0.8,
                                 result={"status": "ok", "detections": []})
    for offset, reason in ((0.0, "clear"), (0.4, "clear"), (1.8, "sampling_gap")):
        consumer._samples[1] = CameraSample(frame, frame, configs[1, "tailgating"], captured_at + offset, request)
        _, detail = consumer._process(frame, 1)
        assert detail["updated_at_s"] == captured_at + offset
        assert detail["reason"] == reason


def test_face_refresh_failure_revokes_only_affected_department(consumer_factory, monkeypatch):
    from AiVision.features._shared.authorization_refresh import AuthorizationResult

    consumer, _, _, _, _, _ = consumer_factory("recognize_face", camera_count=1)
    now = time.monotonic()
    consumer._authorizations.update({"general_electric": (now + 2, {1}), "electronics_electrician": (now + 2, {2})})
    monkeypatch.setattr(consumer._authorization_refresh, "poll", lambda: AuthorizationResult(
        ("general_electric",), None, "TimeoutError", now, None,
    ))
    consumer._before_camera_round()
    assert "general_electric" not in consumer._authorizations
    assert consumer._authorizations["electronics_electrician"][1] == {2}
    assert consumer._next_authorization_attempt > now
