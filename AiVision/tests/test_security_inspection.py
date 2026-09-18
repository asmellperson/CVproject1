from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import queue
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth.auth import get_current_user
from AiVision.api.routes import security_inspection as api
from AiVision.cameras.orm import AiCameraConfig
from AiVision.core.system_config import AiSystemConfig
from AiVision.features.security_inspection.consumer import InspectionConsumer
from AiVision.features.security_inspection.geometry import bbox_in_roi
from AiVision.features.security_inspection.orm import InspectionSession
from AiVision.features.security_inspection.runtime import InspectionRuntime, InspectionTask
from AiVision.features.security_inspection.schema import (
    InspectionConfig,
    InspectionValue,
    InspectionVerdict,
    VlmHealth,
    VlmSettings,
)
from AiVision.features.security_inspection.service import InspectionService
from AiVision.features.security_inspection.sessions import PairSessionManager
from AiVision.features.security_inspection.spec import SPEC
from AiVision.features.security_inspection.vlm import encode_frames


def verdict(compliant=True):
    return InspectionVerdict(
        reason="测试判定证据",
        compliant=compliant,
        confidence=0.9,
    )


def task(camera_id=1, department="general_electric", **changes):
    values = dict(
        session_id=f"session-{camera_id}",
        camera_id=camera_id,
        camera_name=f"camera-{camera_id}",
        camera_key=f"cam-{camera_id}",
        department=department,
        roi_name="工位1",
        start_ts=100.0,
        end_ts=110.0,
        generation=1,
        frames=[b"image1", b"image2"],
        queued_at=time.monotonic(),
    )
    return InspectionTask(**(values | changes))


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.005)


@pytest.mark.parametrize("field", ["start_hold_frames", "video_id", "pending_queue_dir", "model"])
def test_configuration_rejects_legacy_and_unrelated_fields(field):
    with pytest.raises(ValidationError):
        InspectionValue.model_validate({field: 1})


def test_roi_and_wechat_validation():
    with pytest.raises(ValidationError):
        InspectionValue(staff_rois={"one": [[0.0, 0.0], [1.0, 1.0], [0.0, 1.0], [1.0, 0.0]]})
    with pytest.raises(ValidationError):
        InspectionValue(roi_enter_overlap_ratio=0.1, roi_hold_overlap_ratio=0.3)
    with pytest.raises(ValidationError):
        InspectionConfig(alarm={"wechat": {"enable": True, "parm": {"user": ""}}})
    assert SPEC.required_models == ("yolo_human",)


def test_concave_roi_does_not_admit_person_in_cutout():
    polygon = [[0.0, 0.0], [100.0, 0.0], [100.0, 30.0], [30.0, 30.0], [30.0, 100.0], [0.0, 100.0]]
    assert bbox_in_roi([0.0, 0.0, 20.0, 20.0], polygon, 0.3)
    assert not bbox_in_roi([40.0, 40.0, 80.0, 80.0], polygon, 0.1)
    assert bbox_in_roi([20.0, 20.0, 60.0, 60.0], polygon, 0.3)


def test_session_collects_frames_and_finishes_on_pair_loss():
    config = InspectionValue(pair_start_hold_frames=1, interact_motion_min_pixels=0.0)
    manager = PairSessionManager(config)
    frame = np.full((200, 200, 3), 120, np.uint8)
    rois = {"one": [[0.0, 0.0], [200.0, 0.0], [200.0, 200.0], [0.0, 200.0]]}
    tracks = [
        {"track_id": index, "x1": x, "y1": 20.0, "x2": x + 35, "y2": 180.0} for index, x in [(1, 20.0), (2, 85.0)]
    ]
    assert manager.step(frame, tracks, rois, 100.0) == []
    manager.step(frame, tracks, rois, 100.7)
    manager.step(frame, tracks, rois, 101.4)
    completed = manager.step(frame, [], rois, 105.0)
    assert len(completed) == 1
    assert len(completed[0].keyframes) == 2
    assert completed[0].start_ts == 100.0
    assert completed[0].end_ts == 105.0
    assert manager.step(frame, [], rois, 106.0) == []


def test_bounded_fair_queue_and_errors():
    completed, order = [], []
    first_entered, release = threading.Event(), threading.Event()

    def judge(frames, settings):
        order.append(frames[0])
        if len(order) == 1:
            first_entered.set()
            assert release.wait(2)
        return verdict(), 0.01

    runtime = InspectionRuntime(
        lambda *args: completed.append(args),
        SimpleNamespace(judge=judge, check_health=lambda _: VlmHealth(reachable=True)),
    )
    runtime.start(VlmSettings(max_concurrent=1, queue_capacity=3))
    try:
        wait_for(lambda: runtime.health_status().reachable is True)
        runtime.submit(task(frames=[b"first", b"b"]))
        assert first_entered.wait(2)
        runtime.submit(task(2, frames=[b"A1", b"b"]))
        runtime.submit(task(2, session_id="A2", frames=[b"A2", b"b"]))
        runtime.submit(task(3, "research_institute", frames=[b"B1", b"b"]))
        runtime.submit(task(4))
        assert completed[0][2] == "安检判定队列已满"
        release.set()
        deadline = time.monotonic() + 2
        while len(completed) < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert order == [b"first", b"A1", b"B1", b"A2"]
        assert len(completed) == 5
    finally:
        release.set()
        runtime.stop()


@pytest.mark.parametrize("invalid", ["stopped", "changed", "offline", "disabled"])
def test_late_vlm_result_cannot_alarm_after_camera_change(invalid):
    instance = InspectionConsumer(
        spec=SPEC,
        infer_dict={},
        result_queue=queue.Queue(),
        latest_frames={},
        is_camera_active=lambda _: invalid != "offline",
    )
    instance.running = invalid != "stopped"
    instance.config_cache[1] = {"camera_enable": invalid != "disabled", "enable": True}
    instance._generations[1] = 2 if invalid == "changed" else 1
    saved, alarms = [], []
    instance.service = SimpleNamespace(record=lambda *args, **kwargs: saved.append((args, kwargs)))
    instance._handle_alarm = lambda *args: alarms.append(args)
    instance._complete(task(), verdict(False), None, 0.2)
    assert saved[0][0][1] == "cancelled" and not alarms


def test_judgement_error_is_never_a_noncompliance_alarm():
    instance = InspectionConsumer(
        spec=SPEC, infer_dict={}, result_queue=queue.Queue(), latest_frames={}, is_camera_active=lambda _: True
    )
    instance.running = True
    instance.config_cache[1] = {"camera_enable": True, "enable": True}
    instance._generations[1] = 1
    saved, alarms = [], []
    instance.service = SimpleNamespace(record=lambda *args, **kwargs: saved.append(args))
    instance._handle_alarm = lambda *args: alarms.append(args)
    instance._complete(task(), None, "模型请求超时", 45.0)
    assert saved[0][1] == "error" and not alarms


def test_history_and_settings_use_database(monkeypatch):
    from AiVision.features.security_inspection import service as module

    engine = create_engine("sqlite://")
    for model in (AiCameraConfig, AiSystemConfig, InspectionSession):
        model.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def transaction():
        with factory.begin() as session:
            yield session

    monkeypatch.setattr(module, "get_session", factory)
    monkeypatch.setattr(module, "session_scope", transaction)
    with factory.begin() as session:
        session.add(AiCameraConfig(id=1, name="cam", shm_name="cam", url="test", department="general_electric"))
    service = InspectionService()
    service.save_settings(VlmSettings(max_concurrent=2))
    assert service.get_settings().max_concurrent == 2
    service.record(task(), "compliant", verdict())
    service.record(task(session_id="failed"), "error", error="timeout")
    result = service.history("general_electric", camera_id=1, limit=1, offset=0)
    assert result["stats"]["total"] == 2 and result["stats"]["rate"] == 100.0
    assert len(result["items"]) == 1
    assert service.history("research_institute", camera_id=None, limit=10, offset=0)["items"] == []


def test_native_api_department_permissions_and_admin_settings():
    app = FastAPI()
    app.include_router(api.router)
    user = {"role": "viewer", "departments": ["general_electric"]}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[api.get_consumer] = lambda: None
    app.dependency_overrides[api.get_service] = lambda: SimpleNamespace(get_settings=VlmSettings)
    with TestClient(app) as client:
        assert client.get("/api/security-inspection/status?department=general_electric").status_code == 200
        assert client.get("/api/security-inspection/status?department=research_institute").status_code == 403
        assert client.get("/api/security-inspection/settings").status_code == 403
        user["role"] = "admin"
        assert client.get("/api/security-inspection/settings").status_code == 200


@pytest.fixture
def inspection_alarms(monkeypatch):
    from AiVision.alarms.dispatcher import AlarmDispatcher
    from AiVision.features._shared import consumer as base
    from AiVision.features.security_inspection import consumer as inspection

    dispatcher = AlarmDispatcher()
    records = []

    def save_now(**values):
        records.append(values)
        return SimpleNamespace(id=42)

    dispatcher.violation_writer = SimpleNamespace(save_now=save_now)
    dispatcher.wechat = object()
    dispatcher.evidence_recorder = SimpleNamespace(
        start_alarm=lambda *args: pytest.fail("异步判定不能录制返回时的画面")
    )
    monkeypatch.setattr(base, "alarm_dispatcher", dispatcher)
    monkeypatch.setattr(inspection, "alarm_dispatcher", dispatcher)
    instance = InspectionConsumer(
        spec=SPEC, infer_dict={}, result_queue=queue.Queue(), latest_frames={}, is_camera_active=lambda _: True
    )
    instance.running = True
    config = InspectionValue(
        staff_rois={
            f"工位{index}": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]] for index in (1, 2, 3)
        },
    )
    for camera_id in (1, 2):
        instance.config_cache[camera_id] = dict(
            config.model_dump(),
            camera_enable=True,
            enable=True,
            name="安检",
            shm_name=f"cam-{camera_id}",
            department="general_electric",
            sql_enable=True,
            wechat_enable=True,
            wechat_user="test-user",
        )
        instance._generations[camera_id] = 1
    saved = []
    instance.service = SimpleNamespace(record=lambda *args: saved.append(args))
    frames = encode_frames([np.full((64, 64, 3), 120, np.uint8)] * 2, VlmSettings())
    return instance, dispatcher, records, saved, frames


def test_noncompliance_uses_shared_alarm_writer_and_wechat_queue(inspection_alarms):
    instance, dispatcher, records, saved, frames = inspection_alarms
    result = verdict(False)
    result.reason = "完整判定原因超过五十字：" + "现场存在明确违规证据。" * 10
    instance._complete(task(frames=frames), result, None, 0.2)
    request, recipient, record = dispatcher._wechat_queue.get_nowait()
    assert saved[0][1] == "non_compliant"
    assert request.feature_name == "security_inspection" and request.violation_type == 12
    assert request.evidence.mode == "snapshot"
    assert recipient == "test-user" and record.id == 42
    assert records[0]["event_metadata"]["verdict"]["reason"] == result.reason
    assert len(records[0]["reason"]) <= 50 and records[0]["video_path"] is None
    instance._complete(task(session_id="second", frames=frames), result, None, 0.2)
    assert dispatcher._wechat_queue.empty() and len(records) == 1


@pytest.mark.parametrize("phase", ["record", "cancelled_record", "evidence", "alarm"])
def test_slow_completion_io_does_not_lock_other_cameras(monkeypatch, inspection_alarms, phase):
    instance, dispatcher, _, saved, frames = inspection_alarms
    entered, release = threading.Event(), threading.Event()

    def slow(operation):
        def run(*args, **kwargs):
            entered.set()
            assert release.wait(2)
            return operation(*args, **kwargs)
        return run

    if phase in {"record", "cancelled_record"}:
        monkeypatch.setattr(instance.service, "record", slow(lambda *args, **kwargs: saved.append((args, kwargs))))
    elif phase == "evidence":
        monkeypatch.setattr(instance, "_evidence_image", slow(instance._evidence_image))
    else:
        monkeypatch.setattr(dispatcher.violation_writer, "save_now", slow(dispatcher.violation_writer.save_now))
    if phase == "cancelled_record":
        instance._generations[1] += 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        completion = pool.submit(instance._complete, task(frames=frames), verdict(False), None, 0.2)
        try:
            assert entered.wait(1)
            pool.submit(instance.update_status, 2, False).result(timeout=1)
            assert 2 not in instance.config_cache
        finally:
            release.set()
            completion.result(timeout=2)


@pytest.mark.parametrize("change", ["disabled", "reconfigured", "offline", "stopped"])
def test_state_change_during_slow_record_prevents_alarm(monkeypatch, inspection_alarms, change):
    instance, dispatcher, records, _, frames = inspection_alarms
    entered, release = threading.Event(), threading.Event()

    def record(*_args):
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(instance.service, "record", record)

    def change_state():
        if change == "disabled":
            instance.update_status(1, False)
        else:
            with instance._camera_state_lock:
                if change == "reconfigured":
                    instance._invalidate(1)
                elif change == "offline":
                    instance._platform_active = lambda _: False
                else:
                    instance.running = False

    with ThreadPoolExecutor(max_workers=2) as pool:
        completion = pool.submit(instance._complete, task(frames=frames), verdict(False), None, 0.2)
        try:
            assert entered.wait(1)
            pool.submit(change_state).result(timeout=1)
        finally:
            release.set()
            completion.result(timeout=2)
    assert not records and dispatcher._wechat_queue.empty()


def test_alarm_uses_copied_config_without_rereading_cache(monkeypatch, inspection_alarms):
    instance, dispatcher, records, _, frames = inspection_alarms

    def record(*_args):
        with instance._camera_state_lock:
            instance.config_cache[1]["wechat_user"] = "different-user"
            instance.config_cache[1]["name"] = "different-name"
            instance.config_cache[1]["shm_name"] = "different-key"

    monkeypatch.setattr(instance.service, "record", record)
    instance._complete(task(frames=frames), verdict(False), None, 0.2)
    request, recipient, _ = dispatcher._wechat_queue.get_nowait()
    assert recipient == "test-user" and request.camera_name == "安检"
    assert request.camera_key == "cam-1" and request.evidence.source_key == "cam-1"
    assert len(records) == 1


def test_queue_cancellation_returns_before_history_io_and_keeps_capacity_bound(monkeypatch, inspection_alarms):
    instance, _, _, _, frames = inspection_alarms
    judging, release_judgment = threading.Event(), threading.Event()
    recording, release_record = threading.Event(), threading.Event()
    saved = []

    def judge(*_args):
        judging.set()
        assert release_judgment.wait(2)
        return verdict(), 0.1

    def record(current, status, *args, **kwargs):
        if current.camera_id == 1:
            recording.set()
            assert release_record.wait(2)
        saved.append((current.session_id, status, args, kwargs))

    monkeypatch.setattr(instance.service, "record", record)
    runtime = InspectionRuntime(instance._complete, SimpleNamespace(
        check_health=lambda _: VlmHealth(reachable=True), judge=judge,
    ))
    instance.vlm_runtime = runtime
    runtime.start(VlmSettings(max_concurrent=1, queue_capacity=1))
    try:
        wait_for(lambda: runtime.health_status().reachable is True)
        runtime.submit(task(2, frames=frames))
        assert judging.wait(1)
        runtime.submit(task(frames=frames))
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                pool.submit(instance.update_status, 1, False).result(timeout=1)
                assert not recording.is_set()
                runtime.submit(task(2, session_id="rejected", frames=frames))
                assert saved[0][0:2] == ("rejected", "error")
                assert saved[0][2][1] == "安检判定队列已满"
                release_judgment.set()
                assert recording.wait(1)
                pool.submit(instance.update_status, 2, False).result(timeout=1)
            finally:
                release_judgment.set()
                release_record.set()
        wait_for(lambda: len(saved) == 3)
        assert next(row[1] for row in saved if row[0] == "session-1") == "cancelled"
    finally:
        release_judgment.set()
        release_record.set()
        runtime.stop()


def test_frame_submission_rejection_records_outside_state_lock(monkeypatch, inspection_alarms):
    instance, _, _, _, frames = inspection_alarms
    entered, release = threading.Event(), threading.Event()
    instance.latest_frames["cam-1"] = np.zeros((64, 64, 3), np.uint8)
    monkeypatch.setattr(instance, "_process", lambda *_: (False, {"tracks": [], "tasks": [task(frames=frames)]}))

    def record(*_args):
        entered.set()
        assert release.wait(2)
        instance.running = False

    monkeypatch.setattr(instance.service, "record", record)
    with ThreadPoolExecutor(max_workers=2) as pool:
        processing = pool.submit(instance._run)
        try:
            assert entered.wait(1)
            pool.submit(instance.update_status, 2, False).result(timeout=1)
        finally:
            instance.running = False
            release.set()
            processing.result(timeout=2)


def test_alarm_cooldown_is_independent_per_camera_and_roi(monkeypatch, inspection_alarms):
    instance, dispatcher, records, saved, frames = inspection_alarms
    events = [
        (100.0, 1, "工位1", True),
        (110.0, 1, "工位2", True),
        (110.0, 1, "工位3", True),
        (110.0, 2, "工位1", True),
        (129.9, 1, "工位1", False),
        (130.0, 1, "工位1", True),
        (130.0, 1, "工位2", False),
        (130.0, 1, "工位3", False),
        (130.0, 2, "工位1", False),
        (140.0, 1, "工位2", True),
    ]
    for index, (now, camera_id, roi_name, accepted) in enumerate(events):
        monkeypatch.setattr("AiVision.alarms.dispatcher.time.time", lambda: now)
        before = len(records)
        instance._complete(
            task(camera_id, session_id=f"session-{index}", roi_name=roi_name, frames=frames),
            verdict(False), None, 0.2,
        )
        assert len(records) == before + int(accepted)
        if accepted:
            request, _, _ = dispatcher._wechat_queue.get_nowait()
            assert (request.cooldown_subject_type, request.cooldown_subject_id, request.violation_type) == (
                "security_inspection_roi", f"{camera_id}:{roi_name}", 12,
            )
            assert request.subject_type == "camera" and request.camera_id == camera_id
            assert records[-1]["event_metadata"]["roi_name"] == roi_name
        assert dispatcher._wechat_queue.empty()
    assert len(saved) == len(events)


@pytest.mark.parametrize("action", ["update_config", "remove_camera", "disable"])
def test_camera_changes_clear_only_its_inspection_roi_cooldowns(monkeypatch, inspection_alarms, action):
    from AiVision.features._shared import consumer as base

    instance, dispatcher, _, _, frames = inspection_alarms
    monkeypatch.setattr("AiVision.alarms.dispatcher.time.time", lambda: 100.0)
    requests = []
    for camera_id, roi_name in ((1, "工位1"), (1, "工位2"), (1, "工位3"), (2, "工位1")):
        instance._complete(task(camera_id, roi_name=roi_name, frames=frames), verdict(False), None, 0.2)
        requests.append(dispatcher._wechat_queue.get_nowait()[0])
    # 修改工位名称或删除工位也必须清理旧名称对应的冷却。
    updated = instance.config_cache[1] | {"staff_rois": {"新工位": instance.config_cache[1]["staff_rois"]["工位1"]}}
    monkeypatch.setattr(base.config_cache, "get_function_config", lambda *_: updated)
    if action == "disable":
        instance.update_status(1, False)
    else:
        getattr(instance, action)(1)
    for request in requests:
        assert dispatcher.maybe_dispatch(request, alarm_interval=30) is (request.camera_id == 1)


def test_native_processing_uses_shared_person_model(monkeypatch):
    instance = InspectionConsumer(
        spec=SPEC, infer_dict={}, result_queue=queue.Queue(), latest_frames={}, is_camera_active=lambda _: True
    )
    config = InspectionValue(staff_rois={"工位": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]}).model_dump()
    instance.config_cache[1] = config | {"name": "安检", "shm_name": "cam-1", "department": "general_electric"}
    calls = []

    def infer(camera_id, model, frame, params):
        calls.append((model, frame.shape, params))
        return {"status": "ok", "detections": []}

    monkeypatch.setattr(instance, "dispatch_inference_sync", infer)
    frame = np.zeros((200, 320, 3), np.uint8)
    assert instance._process(frame, 1) == (False, {"tracks": [], "tasks": []})
    assert calls == [("yolo_human", frame.shape, {"conf": 0.35, "iou": 0.6, "imgsz": 640})]


def test_missing_person_weights_cannot_trigger_download(tmp_path, monkeypatch):
    from AiVision.inference.workers.yolo_detector import YoloDetectorWorker
    import sys

    monkeypatch.setitem(
        sys.modules,
        "ultralytics",
        SimpleNamespace(YOLO=lambda *args: pytest.fail("missing model must not reach Ultralytics")),
    )
    worker = YoloDetectorWorker({}, {}, "yolo_human", str(tmp_path / "yolo11s.pt"))
    with pytest.raises(ValueError):
        worker.load_model()


def test_queue_errors_are_department_scoped_and_shutdown_survives_storage_failure():
    completed = threading.Event()

    def fail_judgment(*_args):
        raise ValueError("general_electric model response")

    def fail_storage(*_args):
        completed.set()
        raise RuntimeError("database unavailable")

    runtime = InspectionRuntime(
        fail_storage,
        SimpleNamespace(judge=fail_judgment, check_health=lambda _: VlmHealth(reachable=True)),
    )
    runtime.start(VlmSettings(max_concurrent=1))
    wait_for(lambda: runtime.health_status().reachable is True)
    runtime.submit(task())
    assert completed.wait(2)
    runtime.stop()
    assert runtime.status("general_electric")["error"] is not None
    assert runtime.status("research_institute")["error"] is None
    runtime.submit(task(2))
    assert runtime.status("general_electric")["running"] is False
    assert not any(thread.is_alive() for thread in runtime._threads.values())
