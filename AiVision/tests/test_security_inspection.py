from contextlib import contextmanager
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
    VlmSettings,
)
from AiVision.features.security_inspection.service import InspectionService
from AiVision.features.security_inspection.sessions import PairSessionManager
from AiVision.features.security_inspection.spec import SPEC
from AiVision.features.security_inspection.vlm import VlmClient, encode_frames


def verdict(compliant=True):
    return InspectionVerdict(
        scene_summary="安检员与被检人互动",
        staff_visible=True,
        passenger_visible=True,
        interaction_observed=compliant,
        passenger_cooperation_posture=compliant,
        non_compliance_evidence=None if compliant else "安检员全程未检查",
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


def test_internal_client_sends_images_and_rejects_non_json(monkeypatch):
    from AiVision.features.security_inspection import vlm

    calls = []

    @contextmanager
    def post(url, **kwargs):
        calls.append((url, kwargs))
        yield SimpleNamespace(
            status_code=200, json=lambda: {"choices": [{"message": {"content": verdict().model_dump_json()}}]}
        )

    monkeypatch.setattr(vlm.requests, "post", post)
    settings = VlmSettings()
    images = encode_frames([np.zeros((20, 20, 3), np.uint8)] * 2, settings)
    result, latency = VlmClient().judge(images, settings)
    assert result.compliant and latency >= 0
    assert calls[0][0] == settings.base_url + "/chat/completions"
    request = calls[0][1]
    assert request["allow_redirects"] is False
    assert request["json"]["model"] == "fuda-qwen36-27b"
    assert request["json"]["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    with pytest.raises(ValidationError):
        InspectionVerdict.model_validate_json("```json\n{}\n```")
    with pytest.raises(ValidationError):
        InspectionVerdict.model_validate(verdict().model_dump() | {"compliant": False})


def test_bounded_fair_queue_and_errors():
    completed, order = [], []
    first_entered, release = threading.Event(), threading.Event()

    def judge(frames, settings):
        order.append(frames[0])
        if len(order) == 1:
            first_entered.set()
            assert release.wait(2)
        return verdict(), 0.01

    runtime = InspectionRuntime(lambda *args: completed.append(args), SimpleNamespace(judge=judge))
    runtime.start(VlmSettings(max_concurrent=1, queue_capacity=3))
    try:
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


def test_noncompliance_uses_shared_alarm_writer_and_wechat_queue(monkeypatch):
    from AiVision.alarms.dispatcher import AlarmDispatcher
    from AiVision.features._shared import consumer as base

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
    instance = InspectionConsumer(
        spec=SPEC, infer_dict={}, result_queue=queue.Queue(), latest_frames={}, is_camera_active=lambda _: True
    )
    instance.running = True
    config = InspectionConfig(enable=True).model_dump()
    instance.config_cache[1] = dict(
        config["value"],
        camera_enable=True,
        enable=True,
        name="安检",
        shm_name="cam-1",
        department="general_electric",
        sql_enable=True,
        wechat_enable=True,
        wechat_user="test-user",
    )
    instance._generations[1] = 1
    saved = []
    instance.service = SimpleNamespace(record=lambda *args: saved.append(args))
    frames = encode_frames([np.full((64, 64, 3), 120, np.uint8)] * 2, VlmSettings())
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
    assert instance._process(frame, 1) == (False, [])
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

    runtime = InspectionRuntime(fail_storage, SimpleNamespace(judge=fail_judgment))
    runtime.start(VlmSettings(max_concurrent=1))
    runtime.submit(task())
    assert completed.wait(2)
    runtime.stop()
    assert runtime.status("general_electric")["error"] is not None
    assert runtime.status("research_institute")["error"] is None
    runtime.submit(task(2))
    assert runtime.status("general_electric")["running"] is False
    assert not any(thread.is_alive() for thread in runtime._threads.values())
