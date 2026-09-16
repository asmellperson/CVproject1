"""以虚构人员、内存照片、SQLite 和 Mock 验证整条身份识别链路。"""
from datetime import datetime, timedelta
from contextlib import contextmanager
import os
from pathlib import Path
import queue
import sys
import time
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from AiVision.core import db
from AiVision.core.media_cleanup import MediaCleaner
from AiVision.core.settings import settings
from AiVision.features.face_recognition.spec import SPEC
from AiVision.features.face_recognition import records
from AiVision.features.face_recognition.consumer import FaceRecognitionConsumer
from AiVision.features.face_recognition.orm import FaceRecognitionConfig, FaceRecognitionRecord
from AiVision.features.face_recognition.schema import FaceRecognitionConfigSchema
from AiVision.cameras.orm import AiCameraConfig
from AiVision.alarms.devices.orm import AiHornConfig
from AiVision.features.face_recognition.library import PersonSyncError, service
from AiVision.features.face_recognition.library.constants import EMBEDDING_DIM, INDEX_REFRESH_SECONDS, MODEL_FILES, MODEL_NAME
from AiVision.features.face_recognition.library.embedding import generate_embeddings
from AiVision.features.face_recognition.library.index import FaceIndex, decode_embedding, encode_embedding, photo_signature
from AiVision.features.face_recognition.library.orm import FaceEmbedding, FacePerson
from AiVision.inference import model_paths
from AiVision.inference.workers import face_recognizer


def vector(position=0):
    value = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    value[position] = 1.0
    return value


def face(position=0, bbox=(10, 20, 50, 70)):
    return SimpleNamespace(normed_embedding=vector(position), bbox=np.array(bbox), det_score=0.99)


@pytest.fixture
def library(monkeypatch, tmp_path):
    monkeypatch.setattr(settings.storage, "data_path", str(tmp_path))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [FacePerson.__table__, FaceEmbedding.__table__, FaceRecognitionRecord.__table__,
              AiCameraConfig.__table__, AiHornConfig.__table__, FaceRecognitionConfig.__table__]
    db.Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (db, service, records):
        monkeypatch.setattr(module, "get_session", factory)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    yield SimpleNamespace(service=service.FaceLibraryService(), factory=factory, statements=statements)
    engine.dispose()


@pytest.fixture
def recorder(library):
    instance = records.RecognitionRecorder()
    yield instance
    instance.stop()


def add_person(library, person_id=1, source="one", active=True, pic_uri="/pic?token=fake", server="image-server"):
    with library.factory.begin() as session:
        session.add(FacePerson(
            id=person_id, hik_source=source, hik_person_id="person-a", person_name=f"测试人员{person_id}",
            job_no=f"JOB-{person_id}", person_code=f"CODE-{person_id}", org_index_code="ORG-A",
            is_active=active, pic_uri=pic_uri, server_index_code=server, last_synced_at=datetime.now(),
        ))
    return person_id


def save_vector(library, person_id=1, position=0):
    with library.factory() as session:
        person = session.get(FacePerson, person_id)
        signature = photo_signature(person.pic_uri, person.server_index_code)
    library.service.save_embedding(person_id, vector(position), model_name=MODEL_NAME, signature=signature)


def picture_api():
    image = np.full((40, 60, 3), 127, dtype=np.uint8)
    success, content = cv2.imencode(".png", image)
    assert success
    return Mock(get_picture=Mock(return_value=SimpleNamespace(content=content.tobytes())))


def test_float32_blob_and_unique_person_persistence(library):
    add_person(library)
    save_vector(library)
    with library.factory() as session:
        stored = session.query(FaceEmbedding).one()
        assert len(stored.embedding) == 512 * 4
        decoded = decode_embedding(stored.embedding, stored.embedding_dim)
        assert decoded.dtype == np.float32
        np.testing.assert_array_equal(decoded, vector())
        assert stored.model_name == MODEL_NAME
        assert stored.created_at and stored.updated_at
    with pytest.raises(IntegrityError), library.factory.begin() as session:
        session.add(FaceEmbedding(person_id=1, embedding=encode_embedding(vector()), embedding_dim=512,
                                  model_name=MODEL_NAME, photo_signature="duplicate"))


@pytest.mark.parametrize("value", [np.zeros(512), np.ones(511), np.full(512, np.nan), np.full(512, np.inf)])
def test_invalid_embeddings_are_rejected(value):
    with pytest.raises(ValueError):
        encode_embedding(value)


def test_single_face_photo_decoded_in_memory_and_sources_independent(library):
    add_person(library, source="one")
    add_person(library, person_id=2, source="two")
    recognizer = Mock(get_faces=Mock(return_value=[face()]))
    apis = {"one": picture_api(), "two": picture_api()}
    counts = generate_embeddings(library.service, recognizer, apis)
    assert counts["one"].generated == counts["two"].generated == 1
    assert recognizer.get_faces.call_args.args[0].shape == (40, 60, 3)
    assert recognizer.get_faces.call_args.args[0].dtype == np.uint8
    assert apis["one"].get_picture.call_args.args[0].server_index_code == "image-server"
    with library.factory() as session:
        assert session.query(FaceEmbedding).count() == 2


@pytest.mark.parametrize("faces", [[], [face(), face(1)]])
def test_registration_photo_zero_or_multiple_faces_fails(library, faces):
    add_person(library)
    counts = generate_embeddings(library.service, Mock(get_faces=Mock(return_value=faces)), {"one": picture_api()})
    assert counts["one"].failed == 1
    with library.factory() as session:
        assert session.query(FaceEmbedding).count() == 0


def test_unchanged_photo_skips_requests_and_database_updates(library):
    add_person(library)
    save_vector(library)
    library.statements.clear()
    recognizer, api = Mock(), Mock()
    counts = generate_embeddings(library.service, recognizer, {"one": api})
    assert counts["one"].skipped == 1
    recognizer.get_faces.assert_not_called()
    api.get_picture.assert_not_called()
    assert not any(statement.startswith("UPDATE") for statement in library.statements)


@pytest.mark.parametrize("field,value", [("pic_uri", "/pic?token=changed"), ("server_index_code", "changed-server")])
def test_changed_photo_regenerates_current_embedding(library, field, value):
    add_person(library)
    save_vector(library)
    with library.factory.begin() as session:
        setattr(session.get(FacePerson, 1), field, value)
    counts = generate_embeddings(library.service, Mock(get_faces=Mock(return_value=[face(1)])), {"one": picture_api()})
    assert counts["one"].generated == 1
    with library.factory() as session:
        stored = session.query(FaceEmbedding).one()
        np.testing.assert_array_equal(decode_embedding(stored.embedding, stored.embedding_dim), vector(1))


def test_changed_model_regenerates(library):
    add_person(library)
    save_vector(library)
    with library.factory.begin() as session:
        session.query(FaceEmbedding).one().model_name = "different-model"
    counts = generate_embeddings(library.service, Mock(get_faces=Mock(return_value=[face()])), {"one": picture_api()})
    assert counts["one"].generated == 1


@pytest.mark.parametrize("failure", ["zero", "multiple", "decode", "download", "invalid-vector"])
def test_embedding_failure_preserves_existing_data(library, failure):
    add_person(library)
    save_vector(library)
    with library.factory.begin() as session:
        session.get(FacePerson, 1).pic_uri = "/pic?changed"
        stored = session.query(FaceEmbedding).one()
        before = (stored.embedding, stored.photo_signature, stored.updated_at)
    api = picture_api()
    faces = [] if failure == "zero" else [face(), face()] if failure == "multiple" else [face()]
    if failure == "decode":
        api.get_picture.return_value.content = b"not an image"
    if failure == "download":
        api.get_picture.side_effect = RuntimeError("test download error")
    if failure == "invalid-vector":
        faces[0].normed_embedding = np.zeros(512)
    counts = generate_embeddings(library.service, Mock(get_faces=Mock(return_value=faces)), {"one": api})
    assert counts["one"].failed == 1
    with library.factory() as session:
        stored = session.query(FaceEmbedding).one()
        assert (stored.embedding, stored.photo_signature, stored.updated_at) == before


@pytest.mark.parametrize("field,value", [("is_active", False), ("pic_uri", None), ("server_index_code", None)])
def test_inactive_or_missing_picture_is_skipped(library, field, value):
    add_person(library)
    with library.factory.begin() as session:
        setattr(session.get(FacePerson, 1), field, value)
    recognizer = Mock()
    counts = generate_embeddings(library.service, recognizer, {})
    assert counts["one"].generated == counts["one"].failed == 0
    recognizer.get_faces.assert_not_called()


def test_concurrent_photo_change_rejects_stale_embedding(library):
    add_person(library)
    candidate = library.service.list_embedding_candidates()[0]
    with library.factory.begin() as session:
        session.get(FacePerson, 1).pic_uri = "/changed"
    with pytest.raises(PersonSyncError, match="照片发生变化"):
        library.service.save_embedding(1, vector(), model_name=MODEL_NAME,
                                       signature=photo_signature(candidate.pic_uri, candidate.server_index_code))


def test_index_matches_known_unknown_and_does_not_query_per_face(library):
    add_person(library)
    add_person(library, person_id=2, source="two")
    save_vector(library, 1, 0)
    save_vector(library, 2, 1)
    index = FaceIndex()
    assert index.refresh() == 2
    library.statements.clear()
    for _ in range(10):
        known = index.match(vector(0), 0.5)
        assert known["person_id"] == 1
        assert known["job_no"] == "JOB-1"
        assert known["person_code"] == "CODE-1"
        assert known["org_index_code"] == "ORG-A"
        assert index.match(vector(1), 0.5)["person_name"] == "测试人员2"
        unknown = index.match(vector(2), 0.5)
        assert unknown == {"matched": False, "person_id": None, "person_name": "未知人员", "similarity": 0.0,
                           "job_no": None, "person_code": None, "org_index_code": None}
    assert library.statements == []


@pytest.mark.parametrize("field,value", [("is_active", False), ("pic_uri", "/changed"), ("server_index_code", None)])
def test_index_excludes_inactive_or_outdated_photo(library, field, value):
    add_person(library)
    save_vector(library)
    with library.factory.begin() as session:
        setattr(session.get(FacePerson, 1), field, value)
    index = FaceIndex()
    assert index.refresh() == 0
    assert index.match(vector(), .5)["matched"] is False


def test_worker_recognizes_every_face_and_refreshes_on_interval(library, monkeypatch, removed_face_environment):
    add_person(library)
    add_person(library, person_id=2, source="two")
    save_vector(library, 1, 0)
    save_vector(library, 2, 1)
    backend = Mock(get_faces=Mock(return_value=[face(), face(1), face(2)]))
    monkeypatch.setattr(face_recognizer, "InsightFaceRecognizer", lambda _: backend)
    worker = face_recognizer.FaceRecognizerWorker({}, {}, "insightface", "/mock/models")
    assert worker.load_model() is backend
    library.statements.clear()
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    for camera_id, conf in [(1, .2), (2, .8), (1, .3), (2, .7), (1, .5)]:
        results = worker.infer(backend, image, {"camera_id": camera_id, "conf": conf, "similarity_threshold": 0.5})
        backend.get_faces.assert_called_with(image, detection_threshold=conf)
        assert [item["person_id"] for item in results] == [1, 2, None]
        assert all(item["type"] == "face_identity" for item in results)
    assert library.statements == []
    with library.factory.begin() as session:
        session.get(FacePerson, 1).is_active = False
    worker._index_refreshed_at -= INDEX_REFRESH_SECONDS + 1
    assert worker.infer(backend, None, {})[0]["person_id"] is None
    backend.get_faces.assert_called_with(None, detection_threshold=0.5)


def test_index_refresh_failure_is_not_retried_every_frame(monkeypatch):
    worker = face_recognizer.FaceRecognizerWorker({}, {}, "insightface", "/mock/models")
    worker.index = Mock(refresh=Mock(side_effect=RuntimeError("database unavailable")))
    worker._index_refreshed_at = float("-inf")
    worker._index_available = True
    for _ in range(3):
        with pytest.raises(RuntimeError):
            worker.infer(Mock(), None, {})
    worker.index.refresh.assert_called_once()


def test_recorder_cools_known_people_and_preserves_every_unknown_in_one_frame(library, monkeypatch, recorder):
    add_person(library)
    clock = [100.0]
    monkeypatch.setattr(records.time, "monotonic", lambda: clock[0])
    frame = np.zeros((120, 200, 3), dtype=np.uint8)
    known = {"matched": True, "person_id": 1, "person_name": "测试人员", "similarity": .9}
    unknown = {"matched": False, "bbox": [0, 0, 30, 40], "person_id": None, "person_name": "未知人员", "similarity": .2}
    assert recorder.record(1, [known, known, unknown, {**unknown, "bbox": [50, 0, 80, 40]}], 30, frame=frame) == 3
    library.statements.clear()
    for _ in range(5):
        assert recorder.record(1, [known, unknown], 30, frame=frame) == 0
    assert library.statements == []
    assert recorder.record(2, [known], 30, frame=frame) == 1
    clock[0] = 130
    assert recorder.record(1, [known, unknown], 30, frame=frame) == 2
    recorder.stop()
    with library.factory() as session:
        assert session.query(FaceRecognitionRecord).count() == 6
        first_frame = session.query(FaceRecognitionRecord).order_by(FaceRecognitionRecord.id).limit(3).all()
        assert len({record.image_path for record in first_frame}) == 1
        assert len({record.recognized_at for record in first_frame}) == 1
        assert sum(record.person_id is None for record in first_frame) == 2
        np.testing.assert_array_equal(cv2.imread(first_frame[0].image_path), frame)
    assert len(list(Path(settings.storage.data_path).rglob("*.png"))) == 3
    recorder.clear_camera(1)
    assert 1 not in recorder._unknown_recorded_at
    assert all(key[0] != 1 for key in recorder._recorded_at)


def test_record_failure_is_bounded_and_can_retry(library, monkeypatch, recorder):
    scope = Mock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(records, "session_scope", scope)
    clock = [100.0]
    monkeypatch.setattr(records.time, "monotonic", lambda: clock[0])
    detection = {"matched": False, "person_id": None, "person_name": "未知人员", "similarity": .1}
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    assert recorder.record(1, [detection], 30, frame=frame) == 1
    recorder.start()
    recorder._queue.join()
    for _ in range(5):
        assert recorder.record(1, [detection], 30, frame=frame) == 0
    scope.assert_called_once()
    assert recorder._recorded_at == {}
    assert recorder._unknown_recorded_at == {}
    assert list(Path(settings.storage.data_path).rglob("*.png")) == []
    monkeypatch.setattr(records, "session_scope", db.session_scope)
    clock[0] += records.RECORD_RETRY_SECONDS
    assert recorder.record(1, [detection], 30, frame=frame) == 1
    recorder.stop()
    with library.factory() as session:
        assert session.query(FaceRecognitionRecord).count() == 1


def test_record_only_enqueues_frozen_frame_and_metadata(library, monkeypatch, recorder):
    caller = threading.get_ident()
    writer_threads = []
    original_write = cv2.imwrite

    def write(path, frame):
        writer_threads.append(threading.get_ident())
        return original_write(path, frame)

    imwrite = Mock(side_effect=write)
    scope = Mock(wraps=db.session_scope)
    monkeypatch.setattr(records.cv2, "imwrite", imwrite)
    monkeypatch.setattr(records, "session_scope", scope)
    frame = np.full((12, 16, 3), 42, np.uint8)
    detection = {"matched": False, "person_id": None, "person_name": "未知人员", "similarity": .1}
    assert recorder.record(1, [detection, detection], 30, frame=frame) == 2
    imwrite.assert_not_called()
    scope.assert_not_called()
    assert library.statements == []
    frame[:] = 255
    detection["person_name"] = "已修改"
    recorder.stop()
    imwrite.assert_called_once()
    scope.assert_called_once()
    assert writer_threads[0] != caller
    with library.factory() as session:
        rows = session.query(FaceRecognitionRecord).all()
        assert len(rows) == 2 and len({row.image_path for row in rows}) == 1
        assert all(row.person_name == "未知人员" for row in rows)
        assert np.all(cv2.imread(rows[0].image_path) == 42)


def test_slow_writer_and_full_queue_never_block_consumer_and_stop_drains(library, monkeypatch, recorder):
    recorder._queue = queue.Queue(maxsize=1)
    entered, release = threading.Event(), threading.Event()
    original_write = cv2.imwrite
    warnings = []

    def slow_write(path, frame):
        entered.set()
        assert release.wait(3)
        return original_write(path, frame)

    monkeypatch.setattr(records.cv2, "imwrite", slow_write)
    monkeypatch.setattr(records.logger, "warning", warnings.append)
    detection = {"matched": False, "person_id": None, "person_name": "未知人员", "similarity": .1}
    frame = np.zeros((10, 10, 3), np.uint8)
    stopper = threading.Thread(target=recorder.stop)
    recorder.start()
    worker = recorder._thread
    recorder.start()
    assert recorder._thread is worker
    try:
        assert recorder.record(1, [detection], 30, frame=frame) == 1
        assert entered.wait(3)
        assert recorder.record(2, [detection], 30, frame=frame) == 1
        assert recorder.record(3, [detection], 30, frame=frame) == 0
        assert 3 not in recorder._unknown_recorded_at
        assert any("队列已满" in message for message in warnings)
        assert not release.is_set()
        stopper.start()
        stopper.join(.05)
        assert stopper.is_alive()
        assert recorder.record(4, [detection], 30, frame=frame) == 0
    finally:
        release.set()
        if stopper.ident is not None:
            stopper.join(3)
    assert not stopper.is_alive() and not worker.is_alive()
    assert recorder._thread is None and recorder._queue.unfinished_tasks == 0
    with library.factory() as session:
        assert session.query(FaceRecognitionRecord).count() == 2


def test_failed_commit_rolls_back_and_removes_snapshot(library, monkeypatch, recorder):
    session = library.factory()
    rollback = Mock(wraps=session.rollback)
    monkeypatch.setattr(session, "rollback", rollback)

    def fail_commit():
        session.flush()
        raise RuntimeError("commit failed")

    monkeypatch.setattr(session, "commit", fail_commit)
    monkeypatch.setattr(db, "get_session", lambda: session)
    detection = {"matched": False, "person_id": None, "person_name": "未知人员", "similarity": .1}
    assert recorder.record(1, [detection, detection], 30, frame=np.zeros((10, 10, 3), np.uint8)) == 2
    recorder.stop()
    rollback.assert_called_once()
    assert not list(Path(settings.storage.data_path).rglob("*.png"))
    assert recorder._queue.unfinished_tasks == 0
    with library.factory() as check:
        assert check.query(FaceRecognitionRecord).count() == 0


def test_consumer_owns_record_worker_lifecycle(library, monkeypatch):
    from AiVision.features._shared.consumer import BaseFunctionConsumer

    consumer = FaceRecognitionConsumer(SPEC, {}, queue.Queue(), {}, lambda _: True)
    calls = []
    consumer.recorder = Mock()
    consumer.recorder.start.side_effect = lambda: calls.append("writer start")
    consumer.recorder.stop.side_effect = lambda: calls.append("writer stop")
    monkeypatch.setattr(BaseFunctionConsumer, "start", lambda _self: calls.append("consumer start"))
    monkeypatch.setattr(BaseFunctionConsumer, "stop", lambda _self: calls.append("consumer stop"))
    consumer.start()
    consumer.stop()
    assert calls == ["writer start", "consumer start", "consumer stop", "writer stop"]
    monkeypatch.setattr(BaseFunctionConsumer, "start", Mock(side_effect=RuntimeError("config unavailable")))
    with pytest.raises(RuntimeError):
        consumer.start()
    assert calls[-2:] == ["writer start", "writer stop"]


@pytest.mark.parametrize("matched, allowed, reason", [(False, False, "unknown"), (True, False, "unauthorized"), (True, True, "normal")])
def test_consumer_dispatches_insightface_and_alarms_only_for_disallowed_faces(library, removed_face_environment, monkeypatch, matched, allowed, reason):
    from AiVision.features._shared import consumer as consumer_module

    dispatcher = Mock()
    monkeypatch.setattr(consumer_module, "alarm_dispatcher", dispatcher)
    consumer = FaceRecognitionConsumer(SPEC, {}, queue.Queue(), {}, lambda _: True)
    consumer.config_cache[7] = {
        "shm_name": "camera_7", "name": "测试摄像头7", "department": "haoda_company", "cap_interval": .5, "similarity_threshold": .7, "detection_threshold": .35,
        "wechat_enable": True, "wechat_user": "test-user", "horn_enable": True,
        "horn_id": 1, "horn_event_id": 7, "alarm_interval": 5,
    }
    consumer.frame_cache[7] = np.zeros((120, 200, 3), dtype=np.uint8)
    consumer._masks[7] = (None, 10, 100, 20, 150)
    if matched:
        with library.factory.begin() as session:
            session.add_all([
                FacePerson(id=person_id, hik_source="one", hik_person_id=f"person-{person_id}",
                           is_allowed=allowed, last_synced_at=datetime.now())
                for person_id in range(1, 4)
            ])
    detections = [dict(bbox=[0, 0, 30, 40], matched=matched, person_id=person_id if matched else None,
                       person_name=f"测试人员{person_id}" if matched else "未知人员",
                       job_no=f"JOB-{person_id}" if matched else None,
                       person_code=f"CODE-{person_id}" if matched else None, org_index_code="ORG-A" if matched else None,
                       similarity=.9 if matched else .2, type="face_identity") for person_id in range(1, 4)]
    consumer.dispatch_inference_sync = Mock(return_value={"status": "ok", "detections": detections})
    result = consumer._process(consumer.frame_cache[7], 7)
    assert result[0] is (not allowed)
    assert all(detection["is_allowed"] is allowed for detection in result[1]["detections"])
    assert consumer.dispatch_inference_sync.call_args.args[1] == "insightface"
    assert consumer.dispatch_inference_sync.call_args.kwargs["task_meta"] == {"conf": .35, "similarity_threshold": .7}
    assert "timeout" not in consumer.dispatch_inference_sync.call_args.kwargs
    annotated = consumer.post_process(7, result)
    consumer._handle_alarm(7, result, annotated)
    if allowed:
        dispatcher.maybe_dispatch.assert_not_called()
    else:
        dispatcher.maybe_dispatch.assert_called_once()
        request = dispatcher.maybe_dispatch.call_args.args[0]
        assert request.violation_type == 7
        assert request.alarm_config["wechat"]["enable"] and request.alarm_config["horn"]["enable"]
        assert request.subject_type == ("face_person" if matched else "unknown_face")
        assert request.subject_id == ("1" if matched else "")
        assert request.subject_name == detections[0]["person_name"]
        assert request.reason == reason
        assert request.metadata["offending_detections"] == detections
        assert request.camera_name == request.metadata["camera_name"] == "测试摄像头7"
        assert request.metadata["matched"] is matched and request.metadata["is_allowed"] is False
        assert request.metadata["similarity"] == detections[0]["similarity"]
        if matched:
            for key in ("person_id", "person_name", "job_no", "person_code", "org_index_code"):
                assert request.metadata[key] == detections[0][key]
        else:
            assert "person_id" not in request.metadata
    consumer.stop()
    assert annotated.shape == (120, 200, 3)
    assert np.any(annotated != consumer.frame_cache[7])
    with library.factory() as session:
        saved = session.query(FaceRecognitionRecord).all()
        assert len(saved) == 3
        assert len({row.image_path for row in saved}) == 1
        np.testing.assert_array_equal(cv2.imread(saved[0].image_path), annotated)
    snapshot = consumer.get_monitor_status("camera_7")
    assert snapshot["count"] == 3 and snapshot["alarm"] is (not allowed)
    assert snapshot["reason"] == reason
    assert snapshot["detections"][0]["bbox"] == [20, 10, 50, 50]
    assert snapshot["frame_width"] == 200
    assert consumer._should_process_now(7, consumer.config_cache[7])
    consumer._last_process_at[7] = time.time()
    assert not consumer._should_process_now(7, consumer.config_cache[7])
    consumer.post_process(7, (False, {"status": "timeout", "detections": []}))
    assert consumer.get_monitor_status("camera_7")["detections"] == []


def test_consumer_refreshes_only_allowed_ids_and_handles_mixed_and_empty_frames(monkeypatch):
    from AiVision.features.face_recognition import consumer as consumer_module
    from AiVision.features.face_recognition.library.constants import AUTHORIZATION_REFRESH_SECONDS

    now = [100.0]
    monkeypatch.setattr(consumer_module.time, "monotonic", lambda: now[0])
    consumer = FaceRecognitionConsumer(SPEC, {}, queue.Queue(), {}, lambda _: True)
    consumer.config_cache[7] = {}
    consumer.config_cache[8] = {}
    consumer.library = Mock(get_allowed_person_ids=Mock(return_value={1}))
    consumer.dispatch_inference_sync = Mock(return_value={"status": "ok", "detections": [
        {"matched": True, "person_id": 1}, {"matched": True, "person_id": 2}, {"matched": False, "person_id": None},
    ]})
    assert consumer._process(None, 7)[0] is True
    result = consumer._process(None, 8)
    assert [face["is_allowed"] for face in result[1]["detections"]] == [True, False, False]
    consumer.library.get_allowed_person_ids.assert_called_once()
    consumer.library.get_allowed_person_ids.return_value = {2}
    now[0] += AUTHORIZATION_REFRESH_SECONDS
    result = consumer._process(None, 7)
    assert [face["is_allowed"] for face in result[1]["detections"]] == [False, True, False]
    assert consumer.library.get_allowed_person_ids.call_count == 2
    consumer.dispatch_inference_sync.return_value = {"status": "ok", "detections": []}
    assert consumer._process(None, 7)[0] is False
    consumer.dispatch_inference_sync.return_value = {"status": "timeout", "detections": []}
    assert consumer._process(None, 7)[0] is False


def test_person_api_requires_view_access_and_admin_for_permission_changes(library):
    from auth.auth import get_current_user
    from AiVision.api.routes.face_recognition import router

    add_person(library)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"role": "viewer", "departments": ["electronics_electrician"]}
    with TestClient(app) as client:
        response = client.get("/api/face-recognition/persons?source=one&is_active=true&is_allowed=false&keyword=JOB&page_size=1")
        assert response.status_code == 200 and response.json()["total"] == 1
        original = response.json()["items"][0]
        assert original["is_allowed"] is False
        assert not {"embedding", "embedding_dim"} & original.keys()
        assert client.patch("/api/face-recognition/persons/1", json={"is_allowed": True}).status_code == 403
        app.dependency_overrides[get_current_user] = lambda: {"role": "viewer", "departments": ["research_institute"]}
        assert client.get("/api/face-recognition/persons").status_code == 200
        app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
        for payload in ({}, {"is_allowed": "true"}, {"is_allowed": True, "is_active": False}, {"is_allowed": True, "person_name": "修改"}):
            assert client.patch("/api/face-recognition/persons/1", json=payload).status_code == 422
        saved = client.patch("/api/face-recognition/persons/1", json={"is_allowed": True})
        assert saved.status_code == 200 and saved.json()["is_allowed"] is True
        assert saved.json()["person_name"] == original["person_name"]
        assert saved.json()["last_synced_at"] == original["last_synced_at"]
        assert client.get("/api/face-recognition/persons?is_allowed=true").json()["items"] == [saved.json()]
        assert client.patch("/api/face-recognition/persons/999", json={"is_allowed": True}).status_code == 404
        for query in ("page=0", "page_size=101", "source=invalid"):
            assert client.get(f"/api/face-recognition/persons?{query}").status_code == 422


def test_identity_feature_uses_platform_alarm_schema():
    from AiVision.alarms.types import VIOLATION_TYPE_META
    from AiVision.alarms.notifications.wechat import _EVENT_DISPLAY
    from AiVision.features._shared.alarm_schema import AlarmConfigSchema

    assert "departments" not in SPEC.__dataclass_fields__
    assert SPEC.required_models == ("insightface",)
    config = FaceRecognitionConfigSchema.model_validate({"alarm": {
        "wechat": {"enable": True, "parm": {"user": "test-user|second-user"}},
        "horn": {"enable": True, "parm": {"horn_id": 1, "horn_event_id": 7}},
    }})
    assert isinstance(config.alarm, AlarmConfigSchema)
    assert config.alarm.wechat.enable and config.alarm.wechat.parm.user == "test-user|second-user"
    assert config.alarm.horn.enable and config.alarm.horn.parm.horn_id == 1
    assert config.alarm.horn.parm.horn_event_id == 7
    assert SPEC.violation_type == 7
    assert VIOLATION_TYPE_META[SPEC.violation_type] == {"event_type": "recognize_face", "label": "人脸身份识别"}
    assert _EVENT_DISPLAY[SPEC.name] == "人脸身份识别"


def test_monitor_status_exposes_identities_and_clears_expired_results(monkeypatch):
    from AiVision.runtime.orchestrator import Orchestrator

    orchestrator = object.__new__(Orchestrator)
    orchestrator.camera_runtime_manager = Mock(list_running=Mock(return_value=["camera_7"]))
    snapshot = {"updated_at_s": time.time(), "count": 1, "detections": [{"person_name": "测试"}],
                "frame_width": 200, "frame_height": 120, "reason": "normal"}
    orchestrator.consumers = {"recognize_face": Mock(get_monitor_status=Mock(return_value=snapshot))}
    assert orchestrator.get_feature_monitor_status("camera_7", "recognize_face")["detections"] == snapshot["detections"]
    orchestrator.camera_runtime_manager.list_running.return_value = []
    assert orchestrator.get_feature_monitor_status("camera_7", "recognize_face")["detections"] == []
    orchestrator.camera_runtime_manager.list_running.return_value = ["camera_7"]
    snapshot["updated_at_s"] -= 10
    assert orchestrator.get_feature_monitor_status("camera_7", "recognize_face")["detections"] == []


def test_record_api_has_department_scope_pagination_and_auth(library):
    from auth.auth import get_current_user
    from AiVision.api.routes.face_recognition import router

    directory = Path(settings.storage.data_path) / "recognize_face"
    directory.mkdir()
    image_path = directory / "test.png"
    assert cv2.imwrite(str(image_path), np.zeros((20, 30, 3), dtype=np.uint8))
    with library.factory.begin() as session:
        for camera_id, department in [(1, "electronics_electrician"), (2, "research_institute")]:
            session.add(AiCameraConfig(id=camera_id, name=f"测试摄像头{camera_id}", shm_name=f"camera_{camera_id}",
                                       url="test-camera", department=department))
            session.add(FaceRecognitionRecord(camera_id=camera_id, person_id=None, person_name="未知人员",
                                              similarity=.1, image_path=str(image_path)))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"role": "viewer", "departments": ["electronics_electrician"]}
    with TestClient(app) as client:
        response = client.get("/api/face-recognition/records?department=electronics_electrician&page_size=1")
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["camera_id"] == 1
        item = response.json()["items"][0]
        assert item["image_path"] == str(image_path)
        image = client.get(item["image_url"])
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content == image_path.read_bytes()
        assert client.get("/api/face-recognition/records/2/image").status_code == 404
        assert client.get("/api/face-recognition/records/999/image").status_code == 404
        assert client.get("/api/face-recognition/records?department=electronics_electrician&camera_id=2").json()["total"] == 0
        assert client.get("/api/face-recognition/records?department=electronics_electrician&page=2").json()["items"] == []
        assert client.get("/api/face-recognition/records?department=electronics_electrician&page_size=101").status_code == 422
        app.dependency_overrides[get_current_user] = lambda: {"role": "viewer", "departments": ["research_institute"]}
        assert client.get("/api/face-recognition/records?department=electronics_electrician").status_code == 403
        response = client.get("/api/face-recognition/records?department=research_institute")
        assert response.status_code == 200
        assert [row["camera_id"] for row in response.json()["items"]] == [2]
        assert client.get(item["image_url"]).status_code == 404


@pytest.mark.parametrize("threshold", [0.0, .37, 1.0])
def test_recognition_config_api_preserves_threshold_and_feature_switch(library, monkeypatch, threshold):
    from auth.auth import get_current_user, require_admin
    from AiVision.api.routes.alarms import _event_dict
    from AiVision.api.routes.features import create_features_router
    from AiVision.features._shared import config_manager
    from AiVision.features._shared import consumer as consumer_module
    from AiVision.core import cache as cache_module
    from AiVision.features import registry
    from AiVision.alarms.dispatcher import AlarmDispatcher

    monkeypatch.setattr(config_manager, "get_session", library.factory)
    monkeypatch.setattr(cache_module, "get_session", library.factory)
    monkeypatch.setattr(registry, "all_specs", lambda: {SPEC.name: SPEC})
    cache = cache_module.ConfigCache()
    monkeypatch.setattr(config_manager, "config_cache", cache)
    monkeypatch.setattr(consumer_module, "config_cache", cache)
    consumer = FaceRecognitionConsumer(SPEC, {}, queue.Queue(), {}, lambda _: True)
    events = Mock(publish=Mock(side_effect=lambda event: consumer.update_config(event.camera_id)))
    monkeypatch.setattr(config_manager, "config_event_bus", events)
    with library.factory.begin() as session:
        session.add(AiCameraConfig(id=1, name="测试", shm_name="test_camera", url="test-camera",
                                   department="electronics_electrician"))
        session.add(AiHornConfig(id=1, name="测试喇叭", url="http://horn.test", username="test", password="test-only", enable=True))
    app = FastAPI()
    app.include_router(create_features_router(config_manager.FeatureConfigManager()))
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    path = "/api/features/recognize_face/configs/test_camera"
    with TestClient(app) as client:
        config = client.get(path).json()["config"]
        config["value"].update(detection_threshold=threshold, roi_pos=[[0, 0], [1, 0], [1, 1]])
        config["alarm"]["wechat"] = {"enable": True, "parm": {"user": "test-user|second-user"}}
        config["alarm"]["horn"] = {"enable": True, "parm": {"horn_id": 1, "horn_event_id": 7}}
        for enabled in [True, False, False, True]:
            config["enable"] = enabled
            response = client.put(path, json=config)
            assert response.status_code == 200, response.text
            saved = client.get(path).json()["config"]
            assert saved["enable"] is enabled
            assert saved["value"]["detection_threshold"] == threshold
            assert saved == config == response.json()["config"]
        assert [call.args[0].change_type for call in events.publish.call_args_list] == [
            "recognize_face_config_updated", "recognize_face_enabled",
            "recognize_face_config_updated", "recognize_face_disabled",
            "recognize_face_config_updated",
            "recognize_face_config_updated", "recognize_face_enabled",
        ]
        for invalid in [-.01, 1.01]:
            assert client.put(path, json={"value": {"detection_threshold": invalid}}).status_code == 400
        assert client.get(path).json()["config"]["value"]["detection_threshold"] == threshold

        config["value"]["similarity_threshold"] = .91
        response = client.put(path, json=config)
        assert response.status_code == 200, response.text
        assert client.get(path).json()["config"] == config
        value = dict(config["value"])
        config["alarm"]["wechat"]["parm"]["user"] = "updated-user"
        config["alarm"]["horn"]["parm"]["horn_event_id"] = 12
        response = client.put(path, json=config)
        assert response.status_code == 200, response.text
        assert client.get(path).json()["config"] == config
        assert response.json()["config"]["value"] == value
        runtime_config = consumer.config_cache[1]
        assert runtime_config["wechat_enable"] is True and runtime_config["wechat_user"] == "updated-user"
        assert runtime_config["horn_enable"] is True and runtime_config["horn_id"] == 1
        assert runtime_config["horn_event_id"] == 12
        assert runtime_config["roi_pos"] == value["roi_pos"]

        # 注入正式未授权判定，确认统一链路同时传递人员主体和本帧全部违规信息。
        dispatcher = AlarmDispatcher()
        dispatcher.horn_runtime_manager = Mock()
        dispatcher.wechat = Mock()
        dispatcher.violation_writer = Mock(save_now=Mock(return_value={"id": 10}))
        monkeypatch.setattr(consumer_module, "alarm_dispatcher", dispatcher)
        unknown = {"matched": False, "is_allowed": False, "person_id": None, "person_name": "未知人员", "similarity": .2}
        unauthorized = {"matched": True, "is_allowed": False, "person_id": 17, "person_name": "测试人员17",
                        "job_no": "JOB-17", "person_code": "CODE-17", "org_index_code": "ORG-A", "similarity": .9}
        allowed = {**unauthorized, "person_id": 18, "is_allowed": True}
        consumer._handle_alarm(1, (True, {"detections": [unknown, allowed, unauthorized]}), np.zeros((4, 4, 3), np.uint8))
        dispatcher.horn_runtime_manager.enqueue_play.assert_called_once_with(1, 12)
        request, user, record = dispatcher._wechat_queue.get_nowait()
        assert (request.violation_type, request.feature_name, user, record["id"]) == (7, "recognize_face", "updated-user", 10)
        assert (request.subject_type, request.subject_id, request.subject_name, request.reason) == ("face_person", "17", "测试人员17", "unauthorized")
        written = dispatcher.violation_writer.save_now.call_args.kwargs
        assert written["subject_id"] == "17" and written["reason"] == "unauthorized"
        assert written["event_metadata"]["offending_detections"] == [unknown, unauthorized]
        event = _event_dict(SimpleNamespace(id=10, image_path="snapshot.png", **written))
        assert (event["camera_no"], event["camera_name"], event["subject_name"]) == ("test_camera", "测试", "测试人员17")
        consumer._handle_alarm(1, (True, {"detections": [unknown]}), np.zeros((4, 4, 3), np.uint8))
        dispatcher.violation_writer.save_now.assert_called_once()
        dispatcher.reset_cooldown(1, "recognize_face")
        consumer._handle_alarm(1, (True, {"detections": [unknown]}), np.zeros((4, 4, 3), np.uint8))
        written = dispatcher.violation_writer.save_now.call_args.kwargs
        assert written["subject_type"] == "unknown_face" and written["subject_id"] == ""
        assert written["subject_name"] == "未知人员" and written["reason"] == "unknown"
        assert written["event_metadata"] == {"similarity": .2, "matched": False, "is_allowed": False,
                                             "offending_detections": [unknown], "camera_name": "测试"}
        event = _event_dict(SimpleNamespace(id=11, image_path="snapshot.png", **written))
        assert (event["camera_no"], event["camera_name"], event["subject_name"]) == ("test_camera", "测试", "未知人员")
        consumer.config_cache[2] = {**runtime_config, "shm_name": "test_camera_2", "name": "测试摄像头2"}
        consumer._handle_alarm(2, (True, {"detections": [unauthorized]}), np.zeros((4, 4, 3), np.uint8))
        assert dispatcher.violation_writer.save_now.call_count == 3
        assert dispatcher.violation_writer.save_now.call_args.kwargs["camera_no"] == "test_camera_2"

        published = events.publish.call_count
        for horn_id, event_id in [(None, 12), (9999, 12), (1, None), (1, 0), (1, -1), (1, True), (1, "12"), (1, 2147483648)]:
            invalid = {**config, "alarm": {**config["alarm"], "horn": {
                "enable": True, "parm": {"horn_id": horn_id, "horn_event_id": event_id},
            }}}
            response = client.put(path, json=invalid)
            assert response.status_code == 400, response.text
            assert client.get(path).json()["config"] == config
            assert events.publish.call_count == published
        with library.factory.begin() as session:
            session.get(AiHornConfig, 1).enable = False
        assert client.put(path, json=config).status_code == 400
        assert events.publish.call_count == published
        assert client.get(path).json()["config"] == config


def test_recognition_uses_consumer_result_frame_and_existing_camera_jpeg_api(library, monkeypatch):
    from AiVision.api.routes.cameras import build_camera_frame_response
    from AiVision.features._shared import consumer as consumer_module
    from AiVision.runtime.orchestrator import Orchestrator

    frame = np.zeros((120, 200, 3), dtype=np.uint8)
    consumer = FaceRecognitionConsumer(SPEC, {}, queue.Queue(), {"camera_7": frame}, lambda _: True)
    consumer.config_cache[7] = {**SPEC.config_schema().value.model_dump(), "shm_name": "camera_7", "record_enabled": False}
    consumer.dispatch_inference_sync = Mock(return_value={"status": "ok", "detections": [
        {"bbox": [20, 20, 50, 60], "matched": False, "person_id": None,
         "person_name": "未知人员", "similarity": .1},
    ]})
    consumer.recorder.record = Mock()
    monkeypatch.setattr(consumer_module.time, "sleep", lambda _: setattr(consumer, "running", False))
    consumer.running = True
    consumer._run()
    annotated = consumer.result_dict["camera_7"]
    assert consumer.result_updated_at["camera_7"] > 0
    assert np.any(annotated != frame)
    consumer.recorder.record.assert_not_called()
    orchestrator = object.__new__(Orchestrator)
    orchestrator.consumers = {"recognize_face": consumer}
    assert orchestrator.get_camera_frame_info("camera_7", "recognize_face")[0] is annotated
    response = build_camera_frame_response(key="camera_7", feature="recognize_face", quality=85,
        max_width=None, max_height=None, orchestrator=orchestrator)
    assert response.media_type == "image/jpeg"
    decoded = cv2.imdecode(np.frombuffer(response.body, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == frame.shape and np.any(decoded != frame)


def test_screenshot_failure_never_creates_text_only_records(library, monkeypatch, recorder):
    monkeypatch.setattr(records.cv2, "imwrite", Mock(return_value=False))
    detection = {"matched": False, "person_id": None, "person_name": "未知人员", "similarity": .1}
    assert recorder.record(1, [detection], 30, frame=np.zeros((10, 10, 3), np.uint8)) == 1
    recorder.stop()
    assert library.statements == []
    assert recorder._unknown_recorded_at == {}


def _recognition_media(library, name, timestamp, *, people=1, write=True):
    path = Path(settings.storage.data_path) / "recognize_face" / name
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"snapshot")
        os.utime(path, (timestamp.timestamp(), timestamp.timestamp()))
    with library.factory.begin() as session:
        session.add_all([FaceRecognitionRecord(camera_id=1, person_name="未知人员", similarity=.1,
                        image_path=str(path), recognized_at=timestamp) for _ in range(people)])
    return path


def _recognition_cleaner(*, retention_days=7, max_bytes=0):
    return MediaCleaner(settings.storage.data_path, retention_days=retention_days, max_bytes=max_bytes,
                        references=(records.RecognitionMediaReferences(),))


def test_recognition_media_retention_removes_shared_missing_and_orphan_images(library):
    now = datetime.now()
    old = now - timedelta(days=8)
    expired = _recognition_media(library, "expired/frame.png", old, people=2)
    recent = _recognition_media(library, "recent.png", now - timedelta(days=1))
    _recognition_media(library, "missing.png", old, write=False)
    orphan = expired.parent / "orphan.png"
    orphan.write_bytes(b"orphan")
    os.utime(orphan, (old.timestamp(), old.timestamp()))
    fresh_orphan = recent.parent / "fresh-orphan.png"
    fresh_orphan.write_bytes(b"fresh")
    stats = _recognition_cleaner().cleanup(now)
    assert not expired.exists() and not orphan.exists() and not expired.parent.exists()
    assert recent.exists() and fresh_orphan.exists()
    assert (stats.removed_records, stats.removed_files) == (3, 2)
    with library.factory() as session:
        rows = session.query(FaceRecognitionRecord).all()
        assert len(rows) == 1 and rows[0].image_path == str(recent)


@pytest.mark.parametrize("kind", ["outside", "file_symlink", "directory_symlink", "root_symlink", "other_business"])
def test_recognition_media_rejects_unsafe_paths_and_keeps_records(library, kind):
    root = Path(settings.storage.data_path)
    outside = root.parent / f"{root.name}-outside"
    outside.mkdir()
    image = outside / "evidence.png"
    image.write_bytes(b"untouched")
    directory = root / "recognize_face"
    if kind == "root_symlink":
        directory.symlink_to(outside, target_is_directory=True)
        path = directory / image.name
    else:
        directory.mkdir()
        if kind == "file_symlink":
            path = directory / "link.png"
            path.symlink_to(image)
        elif kind == "directory_symlink":
            link = directory / "linked"
            link.symlink_to(outside, target_is_directory=True)
            path = link / image.name
        elif kind == "other_business":
            path = root / "6" / image.name
            path.parent.mkdir()
            path.write_bytes(b"alarm media")
        else:
            path = image
    with library.factory.begin() as session:
        session.add(FaceRecognitionRecord(camera_id=1, person_name="未知人员", similarity=.1,
                    image_path=str(path), recognized_at=datetime.now() - timedelta(days=8)))
    stats = _recognition_cleaner(max_bytes=1).cleanup()
    assert path.exists() and image.read_bytes() == b"untouched"
    assert stats.skipped_unsafe_paths >= 1
    with library.factory() as session:
        assert session.query(FaceRecognitionRecord).count() == 1


def test_recognition_media_quota_orders_images_and_protects_recent_frames(library):
    now = datetime.now()
    old = _recognition_media(library, "old.png", now - timedelta(days=2), people=3)
    recent = _recognition_media(library, "recent.png", now - timedelta(seconds=30), people=2)
    orphan = old.parent / "orphan.png"
    orphan.write_bytes(b"orphan")
    stamp = (now - timedelta(days=3)).timestamp()
    os.utime(orphan, (stamp, stamp))
    fresh_orphan = old.parent / "fresh.png"
    fresh_orphan.write_bytes(b"fresh")
    cleaner = _recognition_cleaner(max_bytes=1)
    stats = cleaner.cleanup(now)
    assert not old.exists() and not orphan.exists()
    assert recent.exists() and fresh_orphan.exists()
    assert stats.removed_records == 3 and stats.removed_files == 2
    with library.factory() as session:
        rows = session.query(FaceRecognitionRecord).all()
        assert len(rows) == 2 and all(Path(row.image_path).exists() for row in rows)


def test_recognition_shared_image_uses_newest_reference_for_retention_and_grace(library):
    now = datetime.now()
    image = _recognition_media(library, "shared.png", now - timedelta(days=8))
    _recognition_media(library, "shared.png", now - timedelta(seconds=30), write=False)
    stats = _recognition_cleaner(max_bytes=1).cleanup(now)
    assert stats.removed_records == 0 and image.exists()
    with library.factory() as session:
        assert session.query(FaceRecognitionRecord).count() == 2


@pytest.mark.parametrize("oldest", ["face", "alarm"])
def test_alarm_and_recognition_media_share_one_capacity_and_database_ownership(library, oldest):
    from AiVision.alarms.records.cleanup import ViolationMediaCleaner
    from AiVision.alarms.records.orm import AiAlarmEvent

    AiAlarmEvent.__table__.create(library.factory.kw["bind"])
    now = datetime.now()
    face_image = _recognition_media(library, "older.png", now - timedelta(days=2 if oldest == "face" else 1), people=2)
    alarm_image = Path(settings.storage.data_path) / "6" / "alarm.png"
    alarm_image.parent.mkdir()
    alarm_image.write_bytes(b"snapshot")
    with library.factory.begin() as session:
        session.add(AiAlarmEvent(id=1, image_path=str(alarm_image), create_time=now - timedelta(days=1 if oldest == "face" else 2),
                    violation_type=6, feature_name="detect_logistics_single_person", department="general_electric",
                    camera_no="camera_1", subject_type="camera", subject_id="1", subject_name="测试摄像头"))
    cleaner = ViolationMediaCleaner(settings.storage.data_path, retention_days=7, max_bytes=10,
                                    session_scope_factory=db.session_scope)
    cleaner.set_additional_references((records.RecognitionMediaReferences(),))
    stats = cleaner.cleanup(now)
    assert face_image.exists() == (oldest == "alarm")
    assert alarm_image.exists() == (oldest == "face")
    assert stats.removed_files == 1 and stats.removed_records == (2 if oldest == "face" else 1)
    with library.factory() as session:
        assert session.query(FaceRecognitionRecord).count() == (0 if oldest == "face" else 2)
        assert session.query(AiAlarmEvent).count() == (1 if oldest == "face" else 0)


def test_media_cleanup_lock_and_file_failure_preserve_references(library, monkeypatch):
    now = datetime.now()
    image = _recognition_media(library, "old.png", now - timedelta(days=8))
    cleaner = _recognition_cleaner()
    with cleaner._lock:
        assert cleaner.cleanup(now).removed_records == 0
    original_unlink = Path.unlink

    def fail_image(path, *args, **kwargs):
        if path == image:
            raise PermissionError("file busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_image)
    stats = cleaner.cleanup(now)
    assert stats.failed_files == 1 and image.exists()
    with library.factory() as session:
        assert session.query(FaceRecognitionRecord).count() == 1


def test_recognition_cleanup_failed_transaction_retries_missing_file_reference(library):
    now = datetime.now()
    image = _recognition_media(library, "old.png", now - timedelta(days=8), people=2)
    fail = [True]

    @contextmanager
    def scope():
        previous = len(library.statements)
        with db.session_scope() as session:
            yield session
            if fail[0] and any(statement.startswith("DELETE") for statement in library.statements[previous:]):
                fail[0] = False
                raise RuntimeError("commit failed")

    cleaner = MediaCleaner(settings.storage.data_path, retention_days=7, max_bytes=0,
                           references=(records.RecognitionMediaReferences(scope),))
    stats = cleaner.cleanup(now)
    assert not image.exists() and stats.removed_records == 0
    with library.factory() as session:
        assert session.query(FaceRecognitionRecord).count() == 2
    stats = cleaner.cleanup(now)
    assert stats.removed_records == 2
    with library.factory() as session:
        assert session.query(FaceRecognitionRecord).count() == 0


@pytest.fixture
def model_directory(tmp_path):
    directory = tmp_path / "buffalo_l"
    directory.mkdir()
    for filename in MODEL_FILES:
        (directory / filename).write_bytes(b"mock ONNX")
    return directory


def test_insightface_directory_validation_preserves_yolo_rules(model_directory, tmp_path, monkeypatch):
    assert model_paths.validate_model_path(str(model_directory), model_type="insightface") == str(model_directory)
    with pytest.raises(ValueError):
        model_paths.validate_model_path(str(model_directory), model_type="yolo")
    config = tmp_path / "model_paths.yaml"
    config.write_text("models:\n  yolo_human:\n    path: /models/person.pt\n")
    monkeypatch.setattr(settings.model_paths, "config_path", str(config))
    try:
        model_paths.save_model_path("insightface", str(model_directory))
        assert model_paths.load_model_paths()["yolo_human"] == "/models/person.pt"
        assert model_paths.load_model_paths()["insightface"] == str(model_directory)
    finally:
        model_paths.clear_model_paths_cache()
    (model_directory / "det_10g.onnx").write_bytes(b"")
    with pytest.raises(ValueError):
        model_paths.validate_model_path(str(model_directory), model_type="insightface")


@pytest.fixture
def removed_face_environment(monkeypatch):
    values = {
        "INSIGHTFACE_EXECUTION_PROVIDER": "CPUExecutionProvider",
        "INSIGHTFACE_DETECTION_SIZE": "invalid",
        "INSIGHTFACE_DETECTION_THRESHOLD": "invalid",
        "FACE_INDEX_REFRESH_SECONDS": "invalid",
        "FACE_INFERENCE_TIMEOUT": "invalid",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_face_runtime_has_no_environment_settings(removed_face_environment):
    import AiVision.core.settings as settings_module

    assert not hasattr(settings_module, "FaceRecognitionSettings")
    assert not hasattr(settings_module.Settings(), "face_recognition")
    assert INDEX_REFRESH_SECONDS == 60.0
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    assert all(name not in example for name in removed_face_environment)


@pytest.mark.parametrize("visible_devices", ["3", "4,1"])
def test_recognizer_loads_local_onnx_without_download_and_detects_all_faces(
    model_directory, monkeypatch, visible_devices, removed_face_environment,
):
    detector = Mock(taskname="detection")
    detector.session.get_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    boxes = np.array([[1, 2, 30, 40, .9], [40, 2, 70, 40, .8]])
    landmarks = np.zeros((2, 5, 2))

    def detect(*args, **kwargs):
        selected = boxes[:, 4] >= detector.det_thresh
        return boxes[selected], landmarks[selected]

    detector.detect.side_effect = detect
    recognizer = Mock(taskname="recognition")
    recognizer.session.get_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    get_model = Mock(side_effect=[detector, recognizer])
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    ))
    monkeypatch.setitem(sys.modules, "insightface.model_zoo", SimpleNamespace(get_model=get_model))
    monkeypatch.setitem(sys.modules, "insightface.app.common", SimpleNamespace(Face=SimpleNamespace))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", visible_devices)
    backend = face_recognizer.InsightFaceRecognizer(str(model_directory))
    for call in get_model.call_args_list:
        assert call.kwargs["download"] is False
        assert call.kwargs["providers"] == ["CUDAExecutionProvider"]
        assert call.kwargs["provider_options"] == [{"device_id": "0"}]
        assert str(model_directory) in call.args[0]
    # 显式检测尺寸防止上游默认的多尺寸检测改变当前项目的推理配置。
    detector.prepare.assert_called_once_with(
        ctx_id=0, input_size=(640, 640),
    )
    recognizer.prepare.assert_called_once_with(ctx_id=0)
    detector.session.disable_fallback.assert_called_once()
    recognizer.session.disable_fallback.assert_called_once()
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    for threshold, count in ((.2, 2), (.85, 1), (.3, 2), (.95, 0)):
        assert len(backend.get_faces(image, detection_threshold=threshold)) == count
        assert detector.det_thresh == threshold
    # 注册照片调用默认参数时恢复默认阈值，不继承最近一次摄像头阈值。
    assert len(backend.get_faces(image)) == 2
    assert detector.det_thresh == 0.5
    assert detector.detect.call_args.kwargs["max_num"] == 0
    assert recognizer.get.call_count == 7
    assert os.environ["CUDA_VISIBLE_DEVICES"] == visible_devices
    detector.detect.side_effect = RuntimeError("CUDA inference failed")
    with pytest.raises(RuntimeError, match="CUDA inference failed"):
        backend.get_faces(image)
    detector.session.set_providers.assert_not_called()
    recognizer.session.set_providers.assert_not_called()


@pytest.mark.parametrize("failure", ["unavailable", "detection", "recognition"])
def test_recognizer_rejects_cpu_when_cuda_is_unavailable_or_fails(model_directory, monkeypatch, failure):
    models = [Mock(taskname="detection"), Mock(taskname="recognition")]
    for model in models:
        model.session.get_providers.return_value = [
            "CPUExecutionProvider" if failure == model.taskname else "CUDAExecutionProvider",
        ]
    get_model = Mock(side_effect=models)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"] if failure == "unavailable" else ["CUDAExecutionProvider"],
    ))
    monkeypatch.setitem(sys.modules, "insightface.model_zoo", SimpleNamespace(get_model=get_model))
    with pytest.raises(RuntimeError, match="CUDAExecutionProvider"):
        face_recognizer.InsightFaceRecognizer(str(model_directory))
    if failure == "unavailable":
        get_model.assert_not_called()
    for model in models:
        if model.taskname != "detection" or failure != "recognition":
            model.prepare.assert_not_called()
        model.session.set_providers.assert_not_called()


def test_missing_models_fail_before_loading_or_downloading(tmp_path, monkeypatch):
    get_model = Mock()
    monkeypatch.setitem(sys.modules, "insightface.model_zoo", SimpleNamespace(get_model=get_model))
    with pytest.raises(ValueError):
        face_recognizer.InsightFaceRecognizer(str(tmp_path))
    get_model.assert_not_called()


def test_detection_and_recognition_reuse_code_with_independent_model_instances(model_directory, monkeypatch):
    from AiVision.inference.workers.face_detector import FaceDetectorWorker

    models = [Mock(taskname=task) for task in ("detection", "detection", "recognition")]
    for model in models:
        model.session.get_providers.return_value = ["CUDAExecutionProvider"]
        model.detect.return_value = (np.empty((0, 5)), None)
    get_model = Mock(side_effect=models)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        get_available_providers=lambda: ["CUDAExecutionProvider"],
    ))
    monkeypatch.setitem(sys.modules, "insightface.model_zoo", SimpleNamespace(get_model=get_model))
    monkeypatch.setitem(sys.modules, "insightface.app.common", SimpleNamespace(Face=SimpleNamespace))
    detector = FaceDetectorWorker({}, {}, "insightface_detection", str(model_directory / "det_10g.onnx")).load_model()
    recognizer = face_recognizer.InsightFaceRecognizer(str(model_directory))
    assert [Path(call.args[0]).name for call in get_model.call_args_list] == [
        "det_10g.onnx", "det_10g.onnx", "w600k_r50.onnx",
    ]
    assert detector.model is not recognizer.detector.model
    image = np.zeros((120, 240, 3), np.uint8)
    detector.detect(image, confidence=.1, nms_threshold=.9)
    recognizer.get_faces(image, detection_threshold=.8)
    assert (models[0].det_thresh, models[0].nms_thresh) == (.1, .9)
    assert (models[1].det_thresh, models[1].nms_thresh) == (.8, .4)
