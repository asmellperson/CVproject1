"""围栏流水线与喇叭的时序回归，不连接数据库、模型或真实设备。"""
from concurrent.futures import Future
from datetime import datetime, timezone
from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock
import time

import numpy as np
import pytest


PERSON = {"bbox": [20.0, 20.0, 180.0, 190.0], "confidence": 0.99, "class_id": 0}
FACE = {"bbox": [60.0, 30.0, 140.0, 110.0], "matched": True, "person_id": 123,
        "person_name": "回归测试人员", "similarity": 0.95,
        "quality": {"size": 80.0, "sharpness": 100.0, "asymmetry": 0.0, "landmarks_valid": True}}


@pytest.fixture
def fence_modules(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "fence_test",
        "MYSQL_DB_PASSWORD": "fence_test", "MYSQL_DB_NAME": "fence_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "fence-test-signing-key-0000000000",
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.features.security_fence import consumer
    from AiVision.features.security_fence.spec import SPEC
    from AiVision.alarms.devices import runtime_manager
    monkeypatch.setattr(consumer.settings.runtime, "fence_inflight", 4)
    monkeypatch.setattr(consumer.settings.runtime, "fence_horn_retry_seconds", 1.0)
    monkeypatch.setattr(consumer, "datetime", SimpleNamespace(
        now=lambda tz: datetime(2026, 11, 4, 4, 0, tzinfo=timezone.utc),
    ))
    return consumer, SPEC, runtime_manager


@pytest.fixture
def make_consumer(fence_modules):
    module, spec, _ = fence_modules
    instances = []

    def make(count=1, *, forbidden=False, confirmation_frames=3):
        frames = {f"camera_{camera}": np.zeros((200, 200, 3), dtype=np.uint8)
                  for camera in range(1, count + 1)}
        consumer = module.FenceConsumer(
            spec=spec, infer_dict={"yolo_human": Queue(), "insightface": Queue()},
            result_queue=Queue(), latest_frames=frames,
            latest_frame_times={key: time.time() for key in frames}, is_camera_active=lambda key: True,
        )
        value = spec.config_schema().value.model_dump()
        value.update(roi_pos=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                     forbidden_start="00:00", forbidden_end="00:00" if forbidden else "00:01",
                     confirmation_frames=confirmation_frames)
        for camera in range(1, count + 1):
            cfg = {**value, "shm_name": f"camera_{camera}", "name": f"测试相机{camera}",
                   "department": "general_electric", "enable": True, "camera_enable": True,
                   "sql_enable": True, "horn_enable": True, "horn_interval": 0.0}
            consumer.config_cache[camera] = cfg
            consumer.preview.configure(camera, cfg)
        consumer.library = Mock(get_allowed_person_ids=Mock(return_value=set()))
        consumer.running = True
        consumer.result_router.start()
        instances.append(consumer)
        return consumer

    yield make
    for consumer in instances:
        consumer.stop()


def complete(consumer, camera, model, detections, *, status="ok"):
    from AiVision.inference.contracts import build_inference_result
    pending = consumer._pending_inferences[camera]
    request = pending.people if model == "yolo_human" else pending.face
    consumer.result_queue.put(build_inference_result(request.pending.identity, status=status, detections=detections))
    assert request.pending.event.wait(1), "模拟结果未被路由到原请求"


def process(consumer, camera):
    frame = consumer._get_roi(camera, consumer.latest_frames[f"camera_{camera}"])
    return consumer._process(frame, camera)


def refresh_frame(consumer, camera):
    key = f"camera_{camera}"
    consumer.latest_frames[key] = consumer.latest_frames[key].copy()
    consumer.latest_frame_times[key] = time.time()
    consumer._submitted_at[camera] = time.monotonic() - consumer.config_cache[camera]["cap_interval"]


def test_parallel_submission_is_bounded_and_round_robin(make_consumer, fence_modules, monkeypatch):
    module, _, _ = fence_modules
    monkeypatch.setattr(module.settings.runtime, "fence_inflight", 2)
    consumer = make_consumer(4)
    consumer._before_camera_round()
    assert set(consumer._pending_inferences) == {1, 2}
    assert consumer.infer_dict["yolo_human"].qsize() == 2
    assert consumer.infer_dict["insightface"].qsize() == 2
    complete(consumer, 2, "yolo_human", [PERSON])
    complete(consumer, 2, "insightface", [FACE])
    process(consumer, 2)
    refresh_frame(consumer, 2)
    consumer._before_camera_round()
    assert set(consumer._pending_inferences) == {1, 3}
    complete(consumer, 3, "yolo_human", [])
    complete(consumer, 3, "insightface", [])
    process(consumer, 3)
    consumer._before_camera_round()
    assert set(consumer._pending_inferences) == {1, 4}


def test_slow_face_does_not_block_another_camera_in_real_loop(make_consumer):
    consumer = make_consumer(2, confirmation_frames=1)
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [PERSON])
    complete(consumer, 2, "yolo_human", [PERSON])
    complete(consumer, 2, "insightface", [FACE])
    alarm = Event()
    consumer._handle_alarm = lambda camera, result, frame: alarm.set() if camera == 2 and result[0] else None
    consumer._thread = Thread(target=consumer._run)
    consumer._thread.start()
    assert alarm.wait(0.5), "慢摄像头不应阻塞已经就绪的其他摄像头"
    assert not consumer._pending_inferences[1].face.pending.event.is_set()
    assert consumer.inference_status()["targets"]


def test_forbidden_alarm_does_not_wait_for_face_or_database(make_consumer):
    consumer = make_consumer(forbidden=True)
    consumer.library.get_allowed_person_ids.side_effect = RuntimeError("数据库不可用")
    consumer._before_camera_round()
    pending = consumer._pending_inferences[1]
    complete(consumer, 1, "yolo_human", [PERSON])
    assert consumer._should_process_now(1, consumer.config_cache[1])
    result = process(consumer, 1)
    assert result[0] and result[1]["persons"][0]["reason"] == "forbidden_time"
    assert not result[1]["error"] and not result[1]["identity_only"]
    assert result[1]["updated_at_s"] == pending.captured_at
    assert 1 in consumer._pending_inferences
    consumer.library.get_allowed_person_ids.assert_not_called()


def test_late_identity_only_patches_original_event(make_consumer, monkeypatch):
    from AiVision.features._shared.consumer import BaseFunctionConsumer
    consumer = make_consumer(forbidden=True, confirmation_frames=1)
    dispatched = Mock(return_value=True)
    monkeypatch.setattr(BaseFunctionConsumer, "_handle_alarm", dispatched)
    consumer._horn_attempt = Mock(return_value=lambda success: None)
    consumer._complete_alarm_identity = Mock()
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [PERSON])
    early = process(consumer, 1)
    consumer._handle_alarm(1, early, None)
    event = next(iter(consumer.runtimes[1].events.values()))
    event.record_dispatched = True
    consumer._before_camera_round()
    complete(consumer, 1, "insightface", [FACE])
    # 最新画面已经改变，身份仍只能与原来的人体和截图配对。
    old_frame = consumer._pending_inferences[1].frame
    refresh_frame(consumer, 1)
    late = process(consumer, 1)
    consumer._handle_alarm(1, late, None)
    assert late[1]["identity_only"] and late[1]["persons"][0]["person_id"] == 123
    assert late[1]["updated_at_s"] == early[1]["updated_at_s"]
    assert consumer.frame_cache[1] is old_frame
    assert next(iter(consumer.runtimes[1].events.values())).key == event.key
    assert dispatched.call_count == 1 and consumer._horn_attempt.call_count == 1
    assert consumer._complete_alarm_identity.call_count == 1


def test_forbidden_cameras_do_not_wait_for_other_faces(make_consumer, fence_modules, monkeypatch):
    module, _, _ = fence_modules
    monkeypatch.setattr(module.settings.runtime, "fence_inflight", 2)
    consumer = make_consumer(4, forbidden=True)
    consumer._before_camera_round()
    assert set(consumer._pending_inferences) == {1, 2}
    assert consumer.infer_dict["insightface"].empty()
    for camera in (1, 2):
        complete(consumer, camera, "yolo_human", [PERSON])
        assert process(consumer, camera)[0]
    consumer._before_camera_round()
    assert set(consumer._pending_inferences) == {1, 2, 3, 4}
    assert consumer.infer_dict["insightface"].qsize() == 2
    for camera in (3, 4):
        complete(consumer, camera, "yolo_human", [PERSON])
        assert process(consumer, camera)[0]
    assert all(not consumer._pending_inferences[camera].face.pending.event.is_set() for camera in (1, 2))
    assert all(consumer._pending_inferences[camera].face is None for camera in (3, 4))


@pytest.mark.parametrize("people", [[], [{**PERSON, "bbox": [0.0, 0.0, 10.0, 10.0]}]])
def test_forbidden_no_violation_keeps_sampling_new_people(make_consumer, people):
    consumer = make_consumer(forbidden=True)
    consumer.config_cache[1]["roi_pos"] = [[0.2, 0.2], [1.0, 0.2], [1.0, 1.0], [0.2, 1.0]]
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", people)
    assert not process(consumer, 1)[0]
    assert not consumer._pending_inferences and consumer.infer_dict["insightface"].empty()
    refresh_frame(consumer, 1)
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [PERSON])
    assert process(consumer, 1)[0]


def test_whitelist_keeps_three_distinct_identity_observations(make_consumer):
    consumer = make_consumer()
    for index in range(3):
        consumer._before_camera_round()
        complete(consumer, 1, "yolo_human", [PERSON])
        assert not consumer._should_process_now(1, consumer.config_cache[1])
        complete(consumer, 1, "insightface", [FACE])
        result = process(consumer, 1)
        assert result[0] == (index == 2)
        assert not result[1]["identity_only"]
        refresh_frame(consumer, 1)


def test_allowed_identity_still_passes(make_consumer):
    consumer = make_consumer(confirmation_frames=1)
    consumer.library.get_allowed_person_ids.return_value = {123}
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [PERSON])
    complete(consumer, 1, "insightface", [FACE])
    result = process(consumer, 1)
    assert not result[0] and result[1]["persons"][0]["identity"] == "allowed"


@pytest.mark.parametrize("angle", [-25, 0, 25])
def test_face_quality_accepts_clear_face_with_in_plane_tilt(fence_modules, angle):
    from AiVision.inference.workers.face_recognizer import FaceRecognizerWorker

    frame = np.random.default_rng(42).integers(0, 256, (200, 200, 3), dtype=np.uint8)
    points = np.array([[80, 55], [120, 55], [100, 73], [85, 90], [115, 90]], dtype=float)
    radians = np.deg2rad(angle)
    rotation = np.array([[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]])
    face = SimpleNamespace(bbox=FACE["bbox"], kps=(points - [100, 70]) @ rotation.T + [100, 70])
    quality = FaceRecognizerWorker._face_quality(face, frame)
    assert quality["landmarks_valid"]
    assert quality["size"] == 80 and quality["sharpness"] >= 60
    assert quality["asymmetry"] < 0.35


@pytest.mark.parametrize("include_quality", [False, True])
@pytest.mark.parametrize("valid_landmarks", [False, True])
def test_shared_worker_only_adds_quality_when_requested(fence_modules, include_quality, valid_landmarks):
    from AiVision.inference.workers.face_recognizer import FaceRecognizerWorker

    frame = np.random.default_rng(42).integers(0, 256, (200, 200, 3), dtype=np.uint8)
    points = [[80, 55], [120, 55], [100, 73], [85, 90], [115, 90]] if valid_landmarks else [[100, 70]] * 5
    face = SimpleNamespace(bbox=FACE["bbox"], kps=points, det_score=0.99, normed_embedding=np.zeros(512))
    worker = object.__new__(FaceRecognizerWorker)
    worker._index_refreshed_at = time.monotonic()
    worker._index_available = True
    worker.index = Mock(match=Mock(return_value={key: FACE[key] for key in (
        "matched", "person_id", "person_name", "similarity",
    )}))
    model = SimpleNamespace(get_faces=Mock(return_value=[face]))
    rows = worker.infer(model, frame, {"include_face_quality": include_quality, "conf": 0.7})
    assert len(rows) == 1 and rows[0]["person_id"] == 123
    assert ("quality" in rows[0]) == include_quality
    if include_quality:
        assert rows[0]["quality"]["landmarks_valid"] == valid_landmarks
    model.get_faces.assert_called_once_with(frame, detection_threshold=0.7)


@pytest.mark.parametrize("points", [
    None,
    [[100, 70]] * 5,
    [[98, 55], [102, 55], [100, 73], [85, 90], [115, 90]],
    [[80, 55], [120, 55], [100, 55], [85, 55], [115, 55]],
    [[80, 55], [120, 55], [100, 40], [85, 90], [115, 90]],
    [[80, 55], [120, 55], [100, 73], [85, 65], [115, 65]],
    [[80, 55], [120, 55], [100, 73], [100, 90], [100, 90]],
    [[80, 55], [120, 55], [100, 73], [115, 90], [85, 90]],
    [[80, 55], [120, 55], [150, 73], [85, 90], [115, 90]],
    [[80, 55], [120, 55], [float("nan"), 73], [85, 90], [115, 90]],
    [[80, 55], [120, 55], [100, 73]],
])
def test_degenerate_face_landmarks_never_confirm_identity(make_consumer, points):
    from AiVision.inference.workers.face_recognizer import FaceRecognizerWorker

    consumer = make_consumer(confirmation_frames=1)
    consumer.library.get_allowed_person_ids.return_value = {123}
    frame = consumer.latest_frames["camera_1"] = np.random.default_rng(42).integers(
        0, 256, (200, 200, 3), dtype=np.uint8,
    )
    quality = FaceRecognizerWorker._face_quality(SimpleNamespace(bbox=FACE["bbox"], kps=points), frame)
    assert not quality["landmarks_valid"]
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [PERSON])
    complete(consumer, 1, "insightface", [{**FACE, "quality": quality}])
    result = process(consumer, 1)
    assert not result[0] and result[1]["persons"][0]["identity"] == "pending"
    assert result[1]["persons"][0]["person_id"] is None
    assert result[1]["pending_count"] == 1 and not result[1]["faces"]


@pytest.mark.parametrize("matched", [True, False])
@pytest.mark.parametrize("quality", [
    None,
    {**FACE["quality"], "landmarks_valid": False},
    {**FACE["quality"], "landmarks_valid": None},
    {**FACE["quality"], "size": 79.0},
    {**FACE["quality"], "sharpness": 59.0},
    {**FACE["quality"], "asymmetry": 0.36},
    {**FACE["quality"], "size": float("inf")},
    {**FACE["quality"], "asymmetry": float("nan")},
])
def test_fence_rejects_poor_quality_for_known_and_unknown_faces(make_consumer, matched, quality):
    consumer = make_consumer(confirmation_frames=1)
    face = {**FACE, "quality": quality, "matched": matched,
            "person_id": 123 if matched else None, "similarity": 0.95 if matched else 0.1}
    for _ in range(3):
        consumer._before_camera_round()
        complete(consumer, 1, "yolo_human", [PERSON])
        complete(consumer, 1, "insightface", [face])
        result = process(consumer, 1)
        assert not result[0] and result[1]["persons"][0]["identity"] == "pending"
        assert not result[1]["faces"]
        assert next(iter(consumer.runtimes[1].identities.values())).observations == 0
        refresh_frame(consumer, 1)


def test_rejected_face_keeps_forbidden_body_alarm_and_snapshot(make_consumer):
    consumer = make_consumer(forbidden=True, confirmation_frames=1)
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [PERSON])
    early = process(consumer, 1)
    assert early[0]
    consumer._before_camera_round()
    complete(consumer, 1, "insightface", [{**FACE, "quality": {**FACE["quality"], "landmarks_valid": False}}])
    result = process(consumer, 1)
    assert result[0] and result[1]["persons"][0]["reason"] == "forbidden_time"
    assert result[1]["persons"][0]["identity"] == "pending" and not result[1]["faces"]
    consumer.unidentified_slots[1] = {result[1]["persons"][0]["track_id"]: 0}
    context = consumer._alarm_context(1, (True, result[1]["persons"][0]))
    assert context["metadata"]["snapshot"] == {"kind": "full_frame", "bbox": [0, 0, 200, 200]}
    np.testing.assert_array_equal(context["snapshot_frame"], consumer.frame_cache[1])


def test_rejected_match_cannot_move_another_person_identity_or_event(make_consumer):
    from AiVision.features.security_fence.runtime import FenceRuntime
    from AiVision.features.security_fence.schema import FenceValue

    runtime = FenceRuntime(FenceValue(confirmation_frames=1))
    people = [PERSON, {**PERSON, "bbox": [220.0, 20.0, 380.0, 190.0]}]
    faces = [FACE, {**FACE, "bbox": [260.0, 30.0, 340.0, 110.0], "person_id": 456}]
    now = datetime(2026, 11, 9, 4, 0, tzinfo=timezone.utc)
    persons = runtime.update(people, faces, (200, 400, 3), now=now, monotonic=100)
    event_keys = [runtime.events[person.track_id].key for person in persons]
    rejected = [{**face, "person_id": person_id, "quality": {**FACE["quality"], "landmarks_valid": False}}
                for face, person_id in zip(faces, [456, 123])]
    persons = runtime.update(people, rejected, (200, 400, 3), now=now, monotonic=103)
    assert [runtime.events[person.track_id].key for person in persons] == event_keys
    assert all(person.identity == "pending" and person.person_id is None for person in persons)


@pytest.mark.parametrize("kind", ["known_face", "unknown_face", "no_face"])
@pytest.mark.parametrize("shape", [(200, 200, 3), (240, 480, 3)])
def test_alarm_png_and_video_keep_full_frame(make_consumer, fence_modules, monkeypatch, tmp_path, kind, shape):
    import cv2
    from AiVision.alarms.dispatcher import AlarmDispatcher
    from AiVision.alarms.records.service import AsyncViolationWriter
    from AiVision.features._shared import consumer as shared_consumer

    consumer = make_consumer(forbidden=kind == "no_face", confirmation_frames=1)
    consumer.config_cache[1]["horn_enable"] = False
    raw = np.random.default_rng(42).integers(0, 256, shape, dtype=np.uint8)
    consumer.latest_frames["camera_1"] = raw
    original = raw.copy()
    dispatcher = AlarmDispatcher()
    writer = dispatcher.violation_writer = AsyncViolationWriter()
    writer._data_path = tmp_path
    recorder = dispatcher.evidence_recorder = Mock()
    recorder.start_alarm.return_value = "/test/full-frame.mp4"
    monkeypatch.setattr(shared_consumer, "alarm_dispatcher", dispatcher)
    monkeypatch.setattr(fence_modules[0], "alarm_dispatcher", dispatcher)

    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [PERSON])
    if kind != "no_face":
        face = FACE if kind == "known_face" else {
            **FACE, "matched": False, "person_id": None, "person_name": None, "similarity": 0.1,
        }
        complete(consumer, 1, "insightface", [face])
    # 推理期间到达的新画面不能替代报警对应的旧输入帧。
    consumer.latest_frames["camera_1"] = np.full_like(raw, 255)
    result = process(consumer, 1)
    assert result[0]
    annotated = consumer.post_process(1, result)
    consumer._handle_alarm(1, result, annotated)

    item = writer._queue.get_nowait()
    try:
        row = writer._save_alarm_snapshot(item)
    finally:
        writer._queue.task_done()
    assert row is not None and writer._queue.empty()
    np.testing.assert_array_equal(cv2.imread(row["image_path"]), original)
    assert row["event_metadata"]["snapshot"] == {"kind": "full_frame", "bbox": [0, 0, shape[1], shape[0]]}
    assert row["video_path"] == "/test/full-frame.mp4" and row["video_status"] == "pending"
    recorder.start_alarm.assert_called_once()
    assert recorder.start_alarm.call_args.args[0] == "camera_1"
    assert recorder.start_alarm.call_args.args[1] is annotated
    assert annotated.shape == raw.shape
    np.testing.assert_array_equal(raw, original)


def test_full_frame_alarms_keep_each_person_metadata_with_or_without_faces(make_consumer):
    from AiVision.features.security_fence.runtime import FenceRuntime
    from AiVision.features.security_fence.schema import FenceValue

    consumer = make_consumer(confirmation_frames=1)
    runtime = consumer.runtimes[1] = FenceRuntime(FenceValue(confirmation_frames=1))
    frame = consumer.frame_cache[1] = np.random.default_rng(42).integers(0, 256, (200, 400, 3), dtype=np.uint8)
    second = {**PERSON, "bbox": [220.0, 20.0, 380.0, 190.0]}
    second_face = {**FACE, "bbox": [260.0, 30.0, 340.0, 110.0], "person_id": 456}
    now = datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)
    persons = runtime.update([PERSON, second], [second_face, FACE], frame.shape, now=now, monotonic=100)
    for person in persons:
        context = consumer._alarm_context(1, (True, person.model_dump()))
        np.testing.assert_array_equal(context["snapshot_frame"], frame)
        assert context["metadata"]["snapshot"] == {"kind": "full_frame", "bbox": [0, 0, 400, 200]}
        assert context["metadata"]["person"] == person.model_dump()
        assert context["metadata"]["event_key"] == runtime.events[person.track_id].key
        assert not np.shares_memory(context["snapshot_frame"], frame)

    persons = runtime.update([PERSON, second], [], frame.shape, now=now, monotonic=100.2)
    for person in persons:
        assert person.alarm
        context = consumer._alarm_context(1, (True, person.model_dump()))
        np.testing.assert_array_equal(context["snapshot_frame"], frame)
        assert context["metadata"]["snapshot"]["kind"] == "full_frame"
        assert context["metadata"]["person"] == person.model_dump()


def test_ambiguous_face_keeps_full_frame_for_each_person_alarm(make_consumer):
    from AiVision.features.security_fence.runtime import FenceRuntime
    from AiVision.features.security_fence.schema import FenceValue

    consumer = make_consumer(forbidden=True)
    runtime = consumer.runtimes[1] = FenceRuntime(FenceValue(forbidden_start="00:00", forbidden_end="00:00"))
    frame = consumer.frame_cache[1] = np.zeros((200, 200, 3), dtype=np.uint8)
    people = [PERSON, {**PERSON, "bbox": [80.0, 20.0, 195.0, 190.0]}]
    persons = runtime.update(people, [FACE], frame.shape,
                             now=datetime(2026, 11, 6, tzinfo=timezone.utc), monotonic=100)
    consumer.unidentified_slots[1] = {person.track_id: index for index, person in enumerate(persons)}
    for person in persons:
        context = consumer._alarm_context(1, (True, person.model_dump()))
        assert context["metadata"]["snapshot"] == {"kind": "full_frame", "bbox": [0, 0, 200, 200]}
        np.testing.assert_array_equal(context["snapshot_frame"], frame)


def test_same_department_cameras_have_independent_whitelists(make_consumer):
    consumer = make_consumer(2, confirmation_frames=1)
    consumer.library.get_allowed_person_ids.side_effect = lambda *, camera_id: {123} if camera_id == 1 else set()
    consumer._before_camera_round()
    for camera in (1, 2):
        complete(consumer, camera, "yolo_human", [PERSON])
        complete(consumer, camera, "insightface", [FACE])
    first, second = process(consumer, 1), process(consumer, 2)
    assert not first[0] and first[1]["persons"][0]["identity"] == "allowed"
    assert second[0] and second[1]["persons"][0]["identity"] == "unauthorized"
    assert consumer._allowed_person_ids == {1: {123}, 2: set()}


def test_authorization_cache_refresh_and_cleanup_are_per_camera(make_consumer):
    consumer = make_consumer(2)
    allowed = {1: {123}, 2: {456}}
    consumer.library.get_allowed_person_ids.side_effect = lambda *, camera_id: allowed[camera_id].copy()
    assert consumer._camera_allowed_people(1) == {123}
    assert consumer._camera_allowed_people(2) == {456}
    allowed[1].clear()
    assert consumer._camera_allowed_people(1) == {123}
    consumer._authorization_refresh_at[1] = 0
    assert consumer._camera_allowed_people(1) == set()
    assert consumer._camera_allowed_people(2) == {456}
    consumer._clear_camera_state(1, "camera_1")
    assert 1 not in consumer._authorization_refresh_at
    assert consumer._allowed_person_ids == {2: {456}}


def test_timeout_uses_submission_deadline_without_another_wait(make_consumer):
    consumer = make_consumer()
    consumer._before_camera_round()
    job = consumer._pending_inferences[1]
    job.people.deadline_at = job.face.deadline_at = time.monotonic() - 1
    assert consumer._should_process_now(1, consumer.config_cache[1])
    result = process(consumer, 1)
    assert not result[0] and result[1]["error"]
    assert consumer.result_router.snapshot()["pending_count"] == 0
    assert all(target["last_outcome"]["status"] == "timeout" for target in consumer.inference_status()["targets"])


def test_configuration_change_cancels_both_old_requests(make_consumer, monkeypatch):
    from AiVision.features._shared.consumer import config_cache
    consumer = make_consumer()
    consumer._before_camera_round()
    new_config = {**consumer.config_cache[1], "threshold": 0.8}
    monkeypatch.setattr(config_cache, "get_function_config", lambda *args: new_config)
    consumer.update_config(1)
    assert not consumer._pending_inferences
    assert consumer.result_router.snapshot()["pending_count"] == 0
    assert consumer.config_cache[1] is new_config
    assert consumer.get_monitor_status("camera_1") is None


def test_time_mode_change_discards_old_pending_result(make_consumer, fence_modules, monkeypatch):
    module, _, _ = fence_modules
    consumer = make_consumer()
    consumer._before_camera_round()
    monkeypatch.setattr(module, "datetime", SimpleNamespace(
        now=lambda tz: datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc),
    ))
    consumer._before_camera_round()
    assert not consumer._pending_inferences
    assert consumer.result_router.snapshot()["pending_count"] == 0


def test_ready_results_keep_input_frame_and_capture_time(make_consumer):
    consumer = make_consumer(confirmation_frames=1)
    consumer._before_camera_round()
    job = consumer._pending_inferences[1]
    complete(consumer, 1, "yolo_human", [PERSON])
    complete(consumer, 1, "insightface", [FACE])
    refresh_frame(consumer, 1)
    result = process(consumer, 1)
    assert consumer.frame_cache[1] is job.frame
    assert consumer._frame_sampled_at[1] == result[1]["updated_at_s"] == job.captured_at


def test_face_failure_revokes_an_old_allowed_identity(make_consumer):
    consumer = make_consumer(confirmation_frames=1)
    consumer.library.get_allowed_person_ids.return_value = {123}
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [PERSON])
    complete(consumer, 1, "insightface", [FACE])
    assert process(consumer, 1)[1]["persons"][0]["identity"] == "allowed"
    refresh_frame(consumer, 1)
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [PERSON])
    complete(consumer, 1, "insightface", [], status="error")
    result = process(consumer, 1)
    assert result[1]["persons"][0]["identity"] == "pending"
    assert result[1]["error"] and not result[0]


@pytest.mark.parametrize("action", ["disable", "remove", "stop", "offline", "resolution",
                                    "feature_off", "camera_off", "missing_frame"])
def test_pending_requests_cannot_survive_camera_invalidation(make_consumer, action):
    consumer = make_consumer()
    consumer._before_camera_round()
    if action == "disable":
        consumer.update_status(1, False)
    elif action == "remove":
        consumer.remove_camera(1)
    elif action == "stop":
        consumer.stop()
    else:
        if action == "offline":
            consumer.is_camera_active = lambda key: False
        elif action == "resolution":
            consumer.latest_frames["camera_1"] = np.zeros((100, 100, 3), dtype=np.uint8)
        elif action == "feature_off":
            consumer.config_cache[1]["enable"] = False
        elif action == "camera_off":
            consumer.config_cache[1]["camera_enable"] = False
        else:
            consumer.latest_frames.pop("camera_1")
        consumer._before_camera_round()
    assert not consumer._pending_inferences
    assert consumer.result_router.snapshot()["pending_count"] == 0


def test_expired_result_cannot_trigger_new_horn_alarm(make_consumer, monkeypatch):
    from AiVision.features._shared.consumer import BaseFunctionConsumer
    consumer = make_consumer(forbidden=True)
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [PERSON])
    result = process(consumer, 1)
    result[1]["updated_at_s"] = time.time() - 6
    dispatch = Mock()
    monkeypatch.setattr(BaseFunctionConsumer, "_handle_alarm", dispatch)
    consumer._handle_alarm(1, result, None)
    dispatch.assert_not_called()


def test_sampling_interval_and_same_frame_are_respected(make_consumer):
    consumer = make_consumer()
    consumer._before_camera_round()
    complete(consumer, 1, "yolo_human", [])
    complete(consumer, 1, "insightface", [])
    process(consumer, 1)
    consumer._before_camera_round()
    assert not consumer._pending_inferences
    consumer.latest_frames["camera_1"] = consumer.latest_frames["camera_1"].copy()
    consumer._submitted_at[1] = time.monotonic()
    consumer._before_camera_round()
    assert not consumer._pending_inferences
    consumer._submitted_at[1] -= consumer.config_cache[1]["cap_interval"]
    consumer._before_camera_round()
    assert set(consumer._pending_inferences) == {1}


def test_same_audio_shares_inflight_playback_and_completion(fence_modules):
    _, _, module = fence_modules
    manager = module.HornRuntimeManager()
    horn = object()
    manager._active = True
    manager._entries[1] = ({}, horn)
    first, second = Mock(), Mock()
    assert manager.enqueue_play(1, 7, on_complete=first)
    job = manager._queue.get_nowait()
    job.started = True
    assert manager.enqueue_play(1, 7, on_complete=second)
    assert manager._queue.empty()
    assert not manager.enqueue_play(1, 8, on_complete=Mock())
    manager._finish_playback(job, True)
    manager._finish_playback(job, True)
    first.assert_called_once_with(True)
    second.assert_called_once_with(True)
    assert not manager._pending


def test_failed_horn_retry_uses_own_short_interval(make_consumer, fence_modules, monkeypatch):
    module, _, _ = fence_modules
    clock = SimpleNamespace(at=0.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.at))
    consumer = make_consumer()
    event = SimpleNamespace(horn_future=None, horn_next_at=0.0)
    config = {"horn_enable": True, "horn_interval": 30.0, "alarm_interval": 30.0}
    complete_playback = consumer._horn_attempt(event, config)
    assert isinstance(event.horn_future, Future)
    assert consumer._horn_attempt(event, config) is None
    complete_playback(False)
    clock.at = 0.1
    assert consumer._horn_attempt(event, config) is None
    assert event.horn_next_at == 1.0
    clock.at = 1.0
    assert consumer._horn_attempt(event, config) is not None
