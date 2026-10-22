"""安检多路请求的有界投递、原图对应和失效清理回归验证。"""

from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
import queue

import cv2
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
        spec=SimpleNamespace(name="security_inspection", alarm_types=(12,)), infer_dict={},
        result_queue=queue.Queue(), latest_frames=frames, is_camera_active=lambda _: True,
    )
    values = InspectionValue(staff_rois={"station": [[0., 0.], [1., 0.], [1., 1.], [0., 1.]]}).model_dump()

    class Session:
        def __init__(self):
            self.seen = []
            self.roi_states = {}

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


@pytest.fixture
def recorded_pipeline(pipeline, monkeypatch):
    from AiVision.alarms.dispatcher import AlarmDispatcher
    from AiVision.alarms.evidence.evidence_recorder import AlarmEvidenceRecorder
    from AiVision.features.security_inspection import consumer as consumer_module
    from AiVision.features.security_inspection.evidence import InspectionSessionEvidence
    from AiVision.features.security_inspection.schema import InspectionVerdict

    recorder = Mock(spec=AlarmEvidenceRecorder)
    recorder.enabled = True
    recorder.begin_episode.side_effect = [f"token-{index}" for index in range(1, 10)]
    recorder.seal_episode.return_value = True
    recorder.finish_episode.side_effect = lambda token: f"/test/{token}.mp4"
    dispatcher = AlarmDispatcher()
    dispatcher.evidence_recorder = recorder
    dispatcher.violation_writer = Mock()
    monkeypatch.setattr(consumer_module, "alarm_dispatcher", dispatcher)
    monkeypatch.setattr("AiVision.features._shared.consumer.alarm_dispatcher", dispatcher)
    consumer = pipeline.consumer
    consumer._session_evidence = InspectionSessionEvidence(recorder)
    consumer.service.record = Mock()
    for cfg in consumer.config_cache.values():
        cfg["sql_enable"] = True

    def session_task(session_id="session-1", camera_id=1):
        frame = consumer.latest_frames[f"camera_{camera_id}"]
        session = SimpleNamespace(
            session_id=session_id, roi_name="station", start_ts=1000.0 + pipeline.clock.now,
            end_ts=1002.0 + pipeline.clock.now, keyframes=[frame.copy(), frame.copy()],
        )
        state = SimpleNamespace(active=session)
        completed = []
        consumer._sessions[camera_id] = SimpleNamespace(
            roi_states={"station": state}, step=lambda *_: completed,
        )
        consumer._process(frame, camera_id)
        state.active = None
        completed.append(session)
        return consumer._process(frame, camera_id)[1]["tasks"][0]

    yield SimpleNamespace(
        pipeline=pipeline, consumer=consumer, recorder=recorder, dispatcher=dispatcher, task=session_task,
        verdict=InspectionVerdict(compliant=False, confidence=0.95, reason="未完成规范安检动作"),
    )
    consumer._session_evidence.clear()


def test_non_compliant_alarm_uses_its_sealed_session_video(recorded_pipeline):
    case = recorded_pipeline
    task = case.task()
    case.recorder.begin_episode.assert_called_once()
    assert case.recorder.begin_episode.call_args.args[0] == "camera_1"
    case.recorder.seal_episode.assert_called_once_with("token-1")
    case.recorder.finish_episode.assert_not_called()
    case.pipeline.clock.now += 120
    case.consumer._complete(task, case.verdict, None, 120.0)
    case.recorder.finish_episode.assert_called_once_with("token-1")
    record = case.dispatcher.violation_writer.enqueue.call_args.kwargs
    assert record["video_path"] == "/test/token-1.mp4" and record["video_status"] == "pending"
    assert record["event_metadata"]["session_id"] == task.session_id
    assert record["event_metadata"]["ended_at"] == task.end_ts
    assert case.consumer.service.record.call_args.args[1] == "non_compliant"
    assert case.consumer.service.record.call_args.kwargs["image_data"].startswith(b"\xff\xd8")
    assert case.consumer._session_evidence.token_for(task.session_id) is None


@pytest.mark.parametrize("outcome", ["compliant", "error", "cancelled", "save_failed"])
def test_sessions_without_an_accepted_alarm_release_video(recorded_pipeline, outcome):
    case = recorded_pipeline
    task = case.task()
    verdict, error = case.verdict, None
    if outcome == "compliant":
        verdict = verdict.model_copy(update={"compliant": True})
    elif outcome == "error":
        verdict, error = None, "判定超时"
    elif outcome == "cancelled":
        case.consumer._invalidate(task.camera_id)
    else:
        case.consumer.service.record.side_effect = RuntimeError("数据库不可用")
    if outcome == "save_failed":
        with pytest.raises(RuntimeError, match="数据库不可用"):
            case.consumer._complete(task, verdict, error, None)
    else:
        case.consumer._complete(task, verdict, error, None)
    case.recorder.finish_episode.assert_not_called()
    case.recorder.cancel_episode.assert_called_once_with("token-1")
    case.dispatcher.violation_writer.enqueue.assert_not_called()


def test_alarm_cooldown_keeps_session_image_but_releases_suppressed_video(recorded_pipeline):
    case = recorded_pipeline
    for session_id in ("session-1", "session-2"):
        case.consumer._complete(case.task(session_id), case.verdict, None, 1.0)
    assert case.consumer.service.record.call_count == 2
    case.dispatcher.violation_writer.enqueue.assert_called_once()
    case.recorder.finish_episode.assert_called_once_with("token-1")
    assert any(call.args == ("token-2",) for call in case.recorder.cancel_episode.call_args_list)


@pytest.mark.parametrize("change", ["invalidate", "offline", "stop"])
def test_lifecycle_changes_release_active_and_waiting_videos(recorded_pipeline, change):
    case = recorded_pipeline
    task = case.task()
    case.consumer._session_evidence.sync(1, "camera_1", np.zeros((12, 12, 3), np.uint8), {"next-session"}, set())
    if change == "invalidate":
        case.consumer._invalidate(1)
    elif change == "offline":
        case.consumer._platform_active = lambda _: False
        assert not case.consumer._camera_active("camera_1")
    else:
        case.consumer.stop()
    assert {call.args[0] for call in case.recorder.cancel_episode.call_args_list} == {"token-1", "token-2"}
    case.consumer._complete(task, case.verdict, None, 1.0)
    case.recorder.finish_episode.assert_not_called()
    assert case.consumer.service.record.call_args.args[1] == "cancelled"


def test_missing_or_disabled_video_does_not_create_a_clip_from_the_verdict_time(recorded_pipeline):
    case = recorded_pipeline
    case.recorder.begin_episode.side_effect = None
    case.recorder.begin_episode.return_value = None
    task = case.task()
    case.consumer._complete(task, case.verdict, None, 1.0)
    case.recorder.start_alarm.assert_not_called()
    case.recorder.finish_episode.assert_not_called()
    record = case.dispatcher.violation_writer.enqueue.call_args.kwargs
    assert record["video_path"] is None and record["video_status"] is None
    assert case.consumer.service.record.call_args.kwargs["image_data"]


def test_disabled_alarm_channels_do_not_reserve_recording_capacity(recorded_pipeline):
    case = recorded_pipeline
    case.consumer.config_cache[1]["sql_enable"] = False
    task = case.task()
    case.consumer._complete(task, case.verdict, None, 1.0)
    case.recorder.begin_episode.assert_not_called()
    case.dispatcher.violation_writer.enqueue.assert_not_called()
    assert case.consumer.service.record.call_args.kwargs["image_data"]


def test_insufficient_keyframes_release_the_aborted_session_video(recorded_pipeline):
    case = recorded_pipeline
    evidence = case.consumer._session_evidence
    frame = np.zeros((12, 12, 3), np.uint8)
    evidence.sync(1, "camera_1", frame, {"short-session"}, set())
    evidence.sync(1, "camera_1", frame, set(), set())
    case.recorder.cancel_episode.assert_called_once_with("token-1")
    case.recorder.seal_episode.assert_not_called()
    assert evidence.token_for("short-session") is None


@pytest.fixture
def session_recorder(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.alarms.evidence.evidence_recorder import AlarmEvidenceRecorder
    from AiVision.core.settings import settings
    from AiVision.features.security_inspection.evidence import InspectionSessionEvidence

    monkeypatch.setattr(settings.storage, "alarm_clip_workers", 1)
    monkeypatch.setattr(settings.storage, "alarm_clip_max_tasks", 2)
    monkeypatch.setattr(settings.storage, "data_path", str(tmp_path))
    clock = SimpleNamespace(now=1000.0)
    statuses = []
    recorder = AlarmEvidenceRecorder(
        tmp_path, enabled=True, fps=4, pre_seconds=1, max_width=160,
        clock=lambda: clock.now, status_callback=lambda path, status: statuses.append((path, status)),
    )
    evidence = InspectionSessionEvidence(recorder)
    yield SimpleNamespace(recorder=recorder, evidence=evidence, clock=clock, statuses=statuses)
    evidence.clear()
    recorder.stop()
    for path in recorder.output_dir.glob("*.mp4"):
        path.unlink()
    (tmp_path / "inspection.jpg").unlink(missing_ok=True)
    if recorder.output_dir.exists():
        recorder.output_dir.rmdir()


def test_session_video_encodes_the_inspection_and_excludes_model_wait_frames(session_recorder, monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from AiVision.alarms.dispatcher import AlarmDispatcher, AlarmEvidenceRequest, AlarmRequest
    from AiVision.alarms.records import service as record_service
    from AiVision.alarms.records.orm import AiAlarmEvent, AiAlarmDisposition
    from AiVision.api.routes import alarms
    from AiVision.core.db import Base

    case = session_recorder
    frame = np.full((120, 160, 3), (20, 30, 120), dtype=np.uint8)
    case.evidence.sync(1, "camera_1", frame, {"session-1"}, set())
    for _ in range(20):
        case.clock.now += 0.25
        case.recorder.record_frame("camera_1", frame)
    case.evidence.sync(1, "camera_1", frame, set(), {"session-1"})
    token = case.evidence.token_for("session-1")
    assert token is not None
    # 模型等待期间继续有其他人员经过，封存录像不能混入这些画面。
    waiting_frame = np.full_like(frame, (0, 250, 0))
    for _ in range(12):
        case.clock.now += 10.0
        case.recorder.record_frame("camera_1", waiting_frame)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AiAlarmEvent.__table__, AiAlarmDisposition.__table__])
    factory = sessionmaker(engine)
    monkeypatch.setattr(record_service, "session_scope", factory.begin)
    monkeypatch.setattr(alarms, "get_session", factory)
    writer = record_service.AsyncViolationWriter()

    def save_alarm(**values):
        image = values.pop("frame")
        image_path = tmp_path / "inspection.jpg"
        assert cv2.imwrite(str(image_path), image)
        with factory.begin() as session:
            session.add(AiAlarmEvent(id=1, image_path=str(image_path), **values))

    def video_finished(path, status):
        case.statuses.append((path, status))
        writer.update_video_status(path, status)

    case.recorder.set_status_callback(video_finished)
    dispatcher = AlarmDispatcher()
    dispatcher.evidence_recorder = case.recorder
    dispatcher.violation_writer = SimpleNamespace(enqueue=save_alarm)
    assert dispatcher.maybe_dispatch(AlarmRequest(
        feature_name="security_inspection", camera_id=1, camera_name="安检工位", camera_key="camera_1",
        department="general_electric", frame=frame, violation_type=12, alarm_config={"sql": {"enable": True}},
        cooldown_subject_type="security_inspection_roi", cooldown_subject_id="1:station",
        metadata={"session_id": "session-1"}, evidence=AlarmEvidenceRequest("camera_1", "episode", token),
    ))
    case.recorder._write_queue.join()
    with factory() as session:
        row = session.get(AiAlarmEvent, 1)
        path = row.video_path
        assert row.video_status == "ready" and row.event_metadata["session_id"] == "session-1"
    assert case.statuses == [(path, "ready")]
    assert Path(path).is_file()
    capture = cv2.VideoCapture(path)
    try:
        assert capture.get(cv2.CAP_PROP_FPS) == pytest.approx(4)
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 21
        while True:
            ok, decoded = capture.read()
            if not ok:
                break
            assert decoded[:, :, 1].mean() < 50
    finally:
        capture.release()
    app = FastAPI()
    app.include_router(alarms.router)
    app.dependency_overrides[alarms.get_current_user] = lambda: {"role": "admin"}
    try:
        with TestClient(app) as client:
            detail = client.get("/api/alarms/1")
            assert detail.status_code == 200 and detail.json()["video_status"] == "ready"
            video_url = detail.json()["video_url"]
            response = client.get(video_url)
            assert response.status_code == 200 and response.headers["content-type"] == "video/mp4"
            assert response.content == Path(path).read_bytes()
            app.dependency_overrides[alarms.get_current_user] = lambda: {
                "role": "viewer", "departments": ["electronics_electrician"],
            }
            assert client.get(video_url).status_code == 403
    finally:
        engine.dispose()


def test_sealed_sessions_share_capacity_and_release_it_on_cancellation(session_recorder):
    case = session_recorder
    frame = np.zeros((120, 160, 3), np.uint8)
    case.evidence.sync(1, "camera_1", frame, {"one", "two"}, set())
    case.evidence.sync(1, "camera_1", frame, set(), {"one", "two"})
    assert case.recorder.begin_episode("camera_2", frame) is None
    case.evidence.cancel_camera(1)
    token = case.recorder.begin_episode("camera_2", frame)
    assert token is not None
    assert case.recorder.cancel_episode(token)
    assert not list(case.recorder.output_dir.glob("*.mp4"))
