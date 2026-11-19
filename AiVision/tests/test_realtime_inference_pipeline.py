"""多路在线检测在请求与原图之间保持绑定，慢路不会阻塞其他摄像头。"""
from queue import Queue
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
    from AiVision.inference.contracts import build_inference_result

    consumer, _, submitted, results, frames, captured_at = consumer_factory(feature)
    blocked_authorization = Event()
    release_authorization = Event()
    if feature == "recognize_face":
        def lookup(departments):
            blocked_authorization.set()
            release_authorization.wait(4)
            return {name: set() for name in departments}

        monkeypatch.setattr(consumer.library, "get_allowed_person_ids_by_department", lookup)
    published = Event()
    monkeypatch.setattr(consumer, "_after_process", lambda camera_id, _: published.set() if camera_id == 2 else None)
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
        assert consumer.get_monitor_status("camera_1") is None
        state = consumer.get_monitor_status("camera_2")
        assert state["count"] == 0 and state["updated_at_s"] == captured_at
        preview = consumer._preview_frames["camera_2"]
        assert preview.sampled_at == captured_at
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
