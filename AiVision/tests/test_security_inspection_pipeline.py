"""安检多路请求的有界投递、原图对应和失效清理回归验证。"""

from types import SimpleNamespace
import queue

import numpy as np
import pytest


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)

    from AiVision.core.settings import settings
    from AiVision.features.security_inspection.consumer import InspectionConsumer
    from AiVision.features.security_inspection.schema import InspectionValue
    from AiVision.inference.contracts import build_inference_result

    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr("time.monotonic", lambda: clock.now)
    monkeypatch.setattr("time.perf_counter", lambda: clock.now)
    monkeypatch.setattr("time.time", lambda: 1000.0 + clock.now)
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr(settings.runtime, "security_inspection_inflight", 4)
    frames = {f"camera_{camera}": np.zeros((12, 12, 3), dtype=np.uint8) for camera in range(1, 7)}
    consumer = InspectionConsumer(
        spec=SimpleNamespace(name="security_inspection", alarm_types=()), infer_dict={},
        result_queue=queue.Queue(), latest_frames=frames, is_camera_active=lambda _: True,
    )
    values = InspectionValue(staff_rois={"station": [[0., 0.], [1., 0.], [1., 1.], [0., 1.]]}).model_dump()

    class Session:
        def __init__(self):
            self.seen = []

        def step(self, frame, tracks, rois, now):
            self.seen.append((frame, now))
            return []

    for camera in range(1, 7):
        consumer.config_cache[camera] = {
            **values, "name": f"camera_{camera}", "shm_name": f"camera_{camera}",
            "department": "general_electric", "enable": True, "camera_enable": True,
        }
        consumer._generations[camera] = 1
        consumer._frame_shapes[camera] = frames[f"camera_{camera}"].shape
        consumer._trackers[camera] = SimpleNamespace(update=lambda *_: [])
        consumer._sessions[camera] = Session()

    tasks = {}
    ready_at = {}
    max_pending = []
    submissions_at_first_wait = []

    def put(task, timeout):
        tasks[task["request_id"]] = task
        ready_at[task["request_id"]] = clock.now + 0.1
        max_pending.append(consumer.result_router.snapshot()["pending_count"])

    consumer.infer_dict["yolo_human"] = SimpleNamespace(put=put)
    consumer.result_router._state = "running"
    original_wait = consumer.result_router.wait

    def wait(pending, timeout):
        if not submissions_at_first_wait:
            submissions_at_first_wait.append(len(tasks))
        task = tasks[pending.identity["request_id"]]
        completed_at = ready_at[task["request_id"]]
        clock.now = max(clock.now, completed_at)
        consumer.result_router._route(build_inference_result(
            task, status="ok", inference_ms=2.0, input_wait_ms=98.0,
            completed_at_monotonic=completed_at,
        ))
        return original_wait(pending, 0.0)

    monkeypatch.setattr(consumer.result_router, "wait", wait)
    monkeypatch.setattr(consumer, "_frame_changed", lambda *_: True)
    consumer.running = True
    yield SimpleNamespace(
        consumer=consumer, settings=settings, clock=clock, tasks=tasks,
        max_pending=max_pending, first_wait=submissions_at_first_wait,
    )
    consumer.running = False
    for pending in consumer._pending_inferences.values():
        consumer.cancel_inference(pending.request)
    consumer._pending_inferences.clear()


@pytest.mark.parametrize("inflight, expected_seconds", [(1, 0.6), (4, 0.2)])
def test_six_cameras_overlap_waits_with_a_fixed_inflight_limit(pipeline, monkeypatch, inflight, expected_seconds):
    consumer = pipeline.consumer
    monkeypatch.setattr(pipeline.settings.runtime, "security_inspection_inflight", inflight)
    original_after = consumer._after_process
    processed = []

    def after(camera_id, result):
        original_after(camera_id, result)
        processed.append(camera_id)
        if len(processed) == 6:
            consumer.running = False

    monkeypatch.setattr(consumer, "_after_process", after)
    consumer._run()
    assert processed == list(range(1, 7))
    assert pipeline.clock.now - 100.0 == pytest.approx(expected_seconds)
    assert pipeline.first_wait == [inflight]
    assert max(pipeline.max_pending) <= inflight
    assert consumer._pending_inferences == {}
    assert consumer.result_router.snapshot()["pending_count"] == 0
    assert consumer.inference_status()["totals"] == {"ok": 6}


def test_result_uses_captured_frame_and_capture_time_instead_of_newest_frame(pipeline):
    consumer = pipeline.consumer
    consumer._before_camera_round()
    pending = consumer._pending_inferences[1]
    captured = pending.frame
    consumer.latest_frames["camera_1"] = np.full_like(captured, 200)
    frame = consumer._get_roi(1, consumer.latest_frames["camera_1"])
    consumer._process(frame, 1)
    assert frame is captured
    assert consumer.frame_cache[1] is captured
    seen_frame, seen_at = consumer._sessions[1].seen[0]
    assert seen_frame is captured
    assert seen_at == pending.captured_at
    assert seen_at < 1000.0 + pipeline.clock.now


@pytest.mark.parametrize("change", ["invalidate", "offline", "stop"])
def test_invalidated_requests_are_unregistered_and_late_results_are_discarded(pipeline, change):
    from AiVision.inference.contracts import build_inference_result

    consumer = pipeline.consumer
    consumer._before_camera_round()
    pending = consumer._pending_inferences[1]
    task = pipeline.tasks[pending.request.pending.identity["request_id"]]
    if change == "invalidate":
        consumer._invalidate(1)
    elif change == "offline":
        consumer._platform_active = lambda _: False
        assert not consumer._camera_active("camera_1")
    else:
        consumer.stop()
    assert 1 not in consumer._pending_inferences
    consumer.result_router._route(build_inference_result(task, status="ok"))
    assert consumer.result_router.snapshot()["orphan_count"] == 1
    assert pending.request.result["status"] == "unavailable"
    if change == "stop":
        assert consumer._pending_inferences == {}
        assert not consumer._prefetch_camera_ids
        assert consumer.result_router.snapshot()["pending_count"] == 0
