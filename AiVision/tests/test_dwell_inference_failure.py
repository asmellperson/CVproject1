"""人脸与两事业部人员逗留共用的推理故障、计时与恢复规则。"""
from copy import deepcopy
from dataclasses import asdict
from functools import partial
import queue
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from AiVision.features import get_spec
from AiVision.features._base import consumer as base_consumer
from AiVision.features._base import dwell_consumer
from AiVision.inference.contracts import INFERENCE_FAILURE_STATUSES
from AiVision.platform.orchestrator import Orchestrator


@pytest.fixture(params=["detect_face", "detect_human"])
def scene(request, monkeypatch):
    spec = get_spec(request.param)
    now = [100.0]
    monkeypatch.setattr(dwell_consumer, "monotonic", lambda: now[0])
    monkeypatch.setattr(dwell_consumer.time, "time", lambda: now[0] + 1000)
    alarms = Mock()
    monkeypatch.setattr(base_consumer, "alarm_dispatcher", alarms)
    consumer = spec.consumer_cls(spec=spec, infer_dict={}, result_queue=queue.Queue(),
                                 latest_frames={}, is_camera_active=lambda _: True)
    config = spec.config_schema(value={"MAX_LOST": 2, "MAX_TIME": 10}).value.model_dump()
    if "MIN_BOX_AREA" in config:
        config.update(MIN_BOX_AREA=0, ASPECT_RATIO_RANGE=[0, 10])
    frame = np.full((200, 200, 3), 20, dtype=np.uint8)
    for camera_id in [1, 2]:
        consumer.config_cache[camera_id] = {
            **deepcopy(config), "shm_name": f"camera-{camera_id}",
            "name": f"camera-{camera_id}", "department": spec.departments[(camera_id - 1) % len(spec.departments)],
        }
        consumer.frame_cache[camera_id] = frame
        consumer._get_roi(camera_id, frame)
    real_dispatch = consumer.dispatch_inference_sync
    consumer.dispatch_inference_sync = Mock()
    box = {"bbox": [20, 20, 60, 80], "confidence": .9, "class_id": 0,
           "type": "face" if request.param == "detect_face" else "person"}
    valid = {"status": "ok", "detections": [box]}

    def step(at, outcome=valid, *, camera_id=1):
        now[0] = at
        consumer.dispatch_inference_sync.return_value = outcome
        result = consumer._process(frame, camera_id)
        annotated = consumer.post_process(camera_id, result)
        consumer._handle_alarm(camera_id, result, annotated)
        return result, consumer.get_monitor_status(f"camera-{camera_id}"), annotated

    return SimpleNamespace(consumer=consumer, now=now, step=step, valid=valid, box=box,
                           alarms=alarms, frame=frame, real_dispatch=real_dispatch)


def test_successful_empty_detections_advance_loss_count_and_delete_track(scene):
    scene.step(100)
    tracker = scene.consumer._trackers[1]
    for lost in [1, 2, 3]:
        result, snapshot, _ = scene.step(100 + lost, {"status": "ok", "detections": []})
        assert result == (False, None)
        assert snapshot["count"] == 0 and snapshot["reason"] == "normal"
        if lost <= 2:
            assert tracker.tracks[1].lost == lost
        else:
            assert not tracker.tracks


@pytest.mark.parametrize("status", sorted(INFERENCE_FAILURE_STATUSES))
def test_continuous_failures_preserve_tracks_and_show_unknown_without_alarm(scene, status, monkeypatch):
    scene.step(100)
    scene.step(104)
    track = scene.consumer._trackers[1].tracks[1]
    before = asdict(track)
    rectangle, text = Mock(), Mock()
    monkeypatch.setattr(dwell_consumer.cv2, "rectangle", rectangle)
    monkeypatch.setattr(dwell_consumer.cv2, "putText", text)
    for i in range(20):
        # 即使错误响应错误地携带了框，也不能进入跟踪与告警。
        result, snapshot, _ = scene.step(105 + i * 10, {**scene.valid, "status": status})
        assert result == (False, None)
        assert snapshot["count"] is None and snapshot["reason"] == "unknown"
        assert snapshot["duration_seconds"] is None and snapshot["alarm"] is False
        assert asdict(track) == before
    assert scene.consumer._trackers[1].tracks == {1: track}
    assert scene.consumer._observation_clocks[1].elapsed == 4
    scene.alarms.maybe_dispatch.assert_not_called()
    rectangle.assert_not_called()
    assert all("UNKNOWN" in call.args[1] for call in text.call_args_list)


def test_recovery_resumes_observed_duration_and_keeps_previous_alarm_state(scene):
    scene.step(100)
    scene.step(104)
    scene.step(105, {"status": "error", "detections": []})
    scene.step(120, {"status": "timeout", "detections": []})
    result, snapshot, _ = scene.step(130)
    assert list(scene.consumer._trackers[1].tracks) == [1]
    assert result[0] is False and snapshot["duration_seconds"] == 4
    result, snapshot, _ = scene.step(136)
    assert result[0] is True and result[1][0]["dwell_time"] == 10
    assert snapshot["duration_seconds"] == 10 and snapshot["alarm"] is True
    scene.alarms.maybe_dispatch.assert_called_once()
    scene.alarms.reset_mock()
    scene.step(137, {"status": "unavailable", "detections": []})
    assert scene.consumer._trackers[1].tracks[1].alarmed is True
    scene.alarms.maybe_dispatch.assert_not_called()
    result, snapshot, _ = scene.step(200)
    assert result[0] is True and snapshot["duration_seconds"] == 10
    scene.alarms.maybe_dispatch.assert_called_once()


def test_recovery_empty_result_counts_one_loss_and_new_target_starts_at_zero(scene):
    scene.step(100)
    scene.step(104)
    scene.step(105, {"status": "timeout", "detections": []})
    scene.step(140, {"status": "ok", "detections": []})
    tracker = scene.consumer._trackers[1]
    assert tracker.tracks[1].lost == 1 and tracker.tracks[1].dwell_time == 4
    far_target = {**scene.box, "bbox": [140, 140, 180, 190]}
    result, snapshot, _ = scene.step(141, {"status": "ok", "detections": [far_target]})
    assert tracker.tracks[1].lost == 2
    assert tracker.tracks[2].dwell_time == 0
    assert snapshot["count"] == 1 and snapshot["duration_seconds"] == 0
    assert result[0] is False
    scene.step(142, {"status": "ok", "detections": [far_target]})
    assert list(tracker.tracks) == [2]


def test_failure_before_first_success_does_not_create_tracker_or_accumulate_time(scene):
    for at in [100, 110, 150]:
        _, snapshot, _ = scene.step(at, {"status": "timeout", "detections": []})
        assert 1 not in scene.consumer._trackers and snapshot["reason"] == "unknown"
    result, snapshot, _ = scene.step(200)
    assert result[0] is False and snapshot["duration_seconds"] == 0


def test_wall_clock_changes_do_not_change_observed_dwell_time(scene, monkeypatch):
    scene.step(100)
    monkeypatch.setattr(dwell_consumer.time, "time", lambda: 999999)
    result, snapshot, _ = scene.step(104)
    assert snapshot["duration_seconds"] == 4 and result[0] is False
    monkeypatch.setattr(dwell_consumer.time, "time", lambda: 500)
    assert scene.step(106)[1]["duration_seconds"] == 6


@pytest.mark.parametrize("invalid", [None, {}, {"detections": []}, {"status": "ok"},
                                    {"status": "ok", "detections": None},
                                    {"status": "ok", "detections": {}}])
def test_missing_or_invalid_result_is_unknown_and_never_ages_tracks(scene, invalid):
    scene.step(100)
    track = scene.consumer._trackers[1].tracks[1]
    before = asdict(track)
    _, snapshot, _ = scene.step(120, invalid)
    assert snapshot["reason"] == "unknown" and asdict(track) == before
    assert scene.step(140)[1]["duration_seconds"] == 0


@pytest.mark.parametrize("invalid", [
    {"bbox": [0, 0, 0, 10]}, {"bbox": [20, 10, 0, 30]}, {"bbox": [0, 0, 10]},
    {"bbox": [0, 0, float("nan"), 20]}, {"bbox": [False, 0, 10, 20]},
    {"confidence": float("inf")}, {"confidence": 1.1}, {"type": None}, {"class_id": "0"},
])
def test_one_invalid_detection_invalidates_whole_frame_before_tracker_update(scene, invalid):
    scene.step(100)
    tracker = scene.consumer._trackers[1]
    before = asdict(tracker.tracks[1])
    payload = {"status": "ok", "detections": [scene.box, {**scene.box, **invalid}]}
    _, snapshot, _ = scene.step(120, payload)
    assert snapshot["count"] is None and snapshot["alarm"] is False
    assert list(tracker.tracks) == [1] and asdict(tracker.tracks[1]) == before
    assert scene.step(130)[1]["duration_seconds"] == 0


def test_unexpected_dispatch_exception_pauses_instead_of_exposing_old_alarm(scene):
    scene.step(100)
    scene.step(110)
    scene.alarms.reset_mock()
    scene.consumer.dispatch_inference_sync.side_effect = RuntimeError("queue connection failed")
    result, snapshot, _ = scene.step(120)
    assert result[0] is False and snapshot["reason"] == "unknown"
    scene.alarms.maybe_dispatch.assert_not_called()
    scene.consumer.dispatch_inference_sync.side_effect = None
    assert scene.step(200)[1]["duration_seconds"] == 10


@pytest.mark.parametrize("available", [False, True])
def test_real_dispatch_unavailable_and_timeout_remain_failures_after_recovery(scene, available):
    scene.step(100)
    scene.step(104)
    mock_dispatch = scene.consumer.dispatch_inference_sync
    if available:
        scene.consumer.infer_dict[scene.consumer.spec.required_models[0]] = queue.Queue()
    scene.consumer.dispatch_inference_sync = partial(scene.real_dispatch, timeout=.002)
    _, snapshot, _ = scene.step(120)
    assert snapshot["count"] is None and snapshot["reason"] == "unknown"
    assert scene.consumer.inference_outcome_counts["timeout" if available else "unavailable"] == 1
    assert scene.consumer._trackers[1].tracks[1].lost == 0
    scene.consumer.dispatch_inference_sync = mock_dispatch
    assert scene.step(140)[1]["duration_seconds"] == 4


def test_camera_failure_does_not_pause_other_camera_and_cleanup_removes_clock(scene):
    scene.step(100)
    scene.step(100, camera_id=2)
    scene.step(104)
    scene.step(105, {"status": "error", "detections": []})
    assert scene.step(111, camera_id=2)[1]["duration_seconds"] == 11
    assert scene.step(120)[1]["duration_seconds"] == 4
    scene.consumer.remove_camera(1)
    assert set(scene.consumer._observation_clocks) == {2}
    assert set(scene.consumer._trackers) == {2}
    assert scene.consumer.get_monitor_status("camera-1") is None


def test_roi_change_clears_frozen_tracks_clock_and_snapshot(scene):
    scene.step(100)
    scene.step(104)
    scene.step(105, {"status": "error", "detections": []})
    scene.consumer.config_cache[1]["roi_pos"] = [[.1, .1], [.9, .1], [.9, .9], [.1, .9]]
    scene.consumer._get_roi(1, scene.frame)
    assert 1 not in scene.consumer._trackers and 1 not in scene.consumer._observation_clocks
    assert scene.consumer.get_monitor_status("camera-1") is None
    assert scene.step(140)[1]["duration_seconds"] == 0


def test_fresh_monitor_status_propagates_unknown_through_orchestrator(scene):
    scene.step(100)
    scene.step(120, {"status": "error", "detections": []})
    orchestrator = object.__new__(Orchestrator)
    orchestrator.camera_runtime_manager = SimpleNamespace(list_running=lambda: ["camera-1"])
    orchestrator.consumers = {scene.consumer.feature_name: scene.consumer}
    status = orchestrator.get_feature_monitor_status("camera-1", scene.consumer.feature_name)
    assert status["online"] is True and status["updated_at"] is not None
    assert status["count"] is None and status["duration_seconds"] is None
    assert status["reason"] == "unknown" and status["alarm"] is False
