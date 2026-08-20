from __future__ import annotations

import queue
from types import SimpleNamespace

import numpy as np

from features._base.consumer import BaseFunctionConsumer
from platform.inference.base_worker import BaseModelWorker
from platform.inference.contracts import (
    INFERENCE_ERROR_MODEL,
    INFERENCE_ERROR_QUEUE_FULL,
    INFERENCE_ERROR_TIMEOUT,
    INFERENCE_ERROR_UNAVAILABLE,
    INFERENCE_STATUS_DROPPED,
    INFERENCE_STATUS_ERROR,
    INFERENCE_STATUS_OK,
    INFERENCE_STATUS_TIMEOUT,
    INFERENCE_STATUS_UNAVAILABLE,
)


class OutcomeConsumer(BaseFunctionConsumer):
    def _process(self, roi_list, camera_id):
        return []

    def post_process(self, camera_id, result):
        return None


class OutcomeWorker(BaseModelWorker):
    def __init__(self, *, should_fail: bool = False):
        super().__init__(
            infer_queue=queue.Queue(),
            result_queues={},
            model_cfg={"name": "yolo_human", "path": "unused-test-model.pt"},
            initial_configs={},
        )
        self.should_fail = should_fail

    def load_model(self):
        return object()

    def infer(self, model, frame, task_meta):
        if self.should_fail:
            raise RuntimeError("broken inference")
        return [{"type": "person", "confidence": 0.9}]


def _consumer(infer_dict: dict, result_queue: queue.Queue | None = None) -> OutcomeConsumer:
    return OutcomeConsumer(
        spec=SimpleNamespace(name="outcome-test"),
        infer_dict=infer_dict,
        result_queue=result_queue or queue.Queue(),
        latest_frames={},
        is_camera_active=lambda _name: True,
    )


def _task(roi_id: int = 0) -> dict:
    return {
        "roi_id": roi_id,
        "camera_id": 7,
        "frame": np.zeros((8, 8, 3), dtype=np.uint8),
        "function_name": "outcome-test",
        "request_id": "outcome-test:7:123",
        "model_name": "test-model",
    }


def test_worker_distinguishes_success_from_model_error():
    success = OutcomeWorker()._execute_task(object(), _task())
    failure = OutcomeWorker(should_fail=True)._execute_task(object(), _task())

    assert success["status"] == INFERENCE_STATUS_OK
    assert success["error_code"] is None
    assert success["detections"] == [{"type": "person", "confidence": 0.9}]
    assert success["inference_ms"] is not None

    assert failure["status"] == INFERENCE_STATUS_ERROR
    assert failure["error_code"] == INFERENCE_ERROR_MODEL
    assert failure["error_message"] == "broken inference"
    assert failure["detections"] == []


def test_dispatch_reports_model_unavailable_for_every_roi():
    consumer = _consumer({})

    results = consumer.dispatch_inference_sync(
        7,
        "missing-model",
        [np.zeros((4, 4, 3), dtype=np.uint8) for _ in range(2)],
    )

    assert [item["roi_id"] for item in results] == [0, 1]
    assert {item["status"] for item in results} == {INFERENCE_STATUS_UNAVAILABLE}
    assert {item["error_code"] for item in results} == {INFERENCE_ERROR_UNAVAILABLE}


def test_dispatch_reports_queue_full_without_losing_roi_identity():
    infer_queue = queue.Queue(maxsize=1)
    infer_queue.put({"occupied": True})
    consumer = _consumer({"test-model": infer_queue})

    results = consumer.dispatch_inference_sync(
        7,
        "test-model",
        [np.zeros((4, 4, 3), dtype=np.uint8)],
    )

    assert results[0]["roi_id"] == 0
    assert results[0]["status"] == INFERENCE_STATUS_DROPPED
    assert results[0]["error_code"] == INFERENCE_ERROR_QUEUE_FULL
    assert results[0]["detections"] == []


def test_dispatch_keeps_partial_result_roi_and_marks_other_roi_timeout(monkeypatch):
    monkeypatch.setattr("features._base.consumer.time.monotonic_ns", lambda: 123)
    infer_queue = queue.Queue()
    result_queue = queue.Queue()
    result_queue.put({
        "roi_id": 1,
        "camera_id": 7,
        "function_name": "outcome-test",
        "request_id": "outcome-test:7:123",
        "detections": [{"type": "person"}],
    })
    consumer = _consumer({"test-model": infer_queue}, result_queue)

    results = consumer.dispatch_inference_sync(
        7,
        "test-model",
        [np.zeros((4, 4, 3), dtype=np.uint8) for _ in range(2)],
        timeout=0.001,
    )

    assert [item["roi_id"] for item in results] == [0, 1]
    assert results[0]["status"] == INFERENCE_STATUS_TIMEOUT
    assert results[0]["error_code"] == INFERENCE_ERROR_TIMEOUT
    assert results[1]["status"] == INFERENCE_STATUS_OK
    assert results[1]["detections"] == [{"type": "person"}]
    assert consumer.inference_outcome_counts == {
        INFERENCE_STATUS_TIMEOUT: 1,
        INFERENCE_STATUS_OK: 1,
    }


def test_consecutive_failures_emit_one_alert_and_are_exposed(monkeypatch):
    monkeypatch.setattr(
        "features._base.consumer.settings.runtime.inference_alert_consecutive_failures",
        2,
    )
    monkeypatch.setattr(
        "features._base.consumer.settings.runtime.inference_alert_cooldown_seconds",
        300.0,
    )
    consumer = _consumer({"test-model": queue.Queue()})
    consumer.config_cache[7] = {"name": "东门摄像头"}
    alerts = []
    monkeypatch.setattr(
        consumer,
        "_notify_runtime_alert",
        lambda event_type, detail, **kwargs: alerts.append((event_type, detail, kwargs)),
    )

    for _index in range(2):
        consumer.dispatch_inference_sync(
            7,
            "test-model",
            [np.zeros((4, 4, 3), dtype=np.uint8)],
            timeout=0,
        )

    snapshot = consumer.inference_status()
    assert snapshot["totals"] == {INFERENCE_STATUS_TIMEOUT: 2}
    assert snapshot["targets"] == [{
        "model_name": "test-model",
        "camera_id": 7,
        "counts": {INFERENCE_STATUS_TIMEOUT: 2},
        "consecutive_failures": 2,
        "last_outcome": {
            "status": INFERENCE_STATUS_TIMEOUT,
            "error_code": INFERENCE_ERROR_TIMEOUT,
            "updated_at": snapshot["targets"][0]["last_outcome"]["updated_at"],
        },
    }]
    assert len(alerts) == 1
    assert alerts[0][0] == "推理连续异常"
    assert "东门摄像头" in alerts[0][1]
    assert alerts[0][2]["target_key"] == "outcome-test:test-model:7"

    consumer._record_inference_outcomes(
        camera_id=7,
        model_name="test-model",
        outcomes=[{"status": INFERENCE_STATUS_OK}],
    )
    assert consumer.inference_status()["targets"][0]["consecutive_failures"] == 0
