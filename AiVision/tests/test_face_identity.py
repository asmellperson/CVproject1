"""以虚构人员、内存照片、SQLite 和 Mock 验证整条身份识别链路。"""
from datetime import datetime
import os
from pathlib import Path
import queue
import sys
import time
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
from AiVision.core.settings import settings
from AiVision.features.recognize_face import SPEC, records
from AiVision.features.recognize_face.consumer import FaceRecognitionConsumer
from AiVision.features.recognize_face.orm import FaceRecognitionRecord
from AiVision.features.recognize_face.schema import FaceRecognitionConfigSchema
from AiVision.platform.camera.orm import AiCameraConfig
from AiVision.platform.face_library import PersonSyncError, service
from AiVision.platform.face_library.constants import EMBEDDING_DIM, INDEX_REFRESH_SECONDS, MODEL_FILES, MODEL_NAME
from AiVision.platform.face_library.embedding import generate_embeddings
from AiVision.platform.face_library.index import FaceIndex, decode_embedding, encode_embedding, photo_signature
from AiVision.platform.face_library.orm import FaceEmbedding, FacePerson
from AiVision.platform.inference import model_paths
from AiVision.platform.inference.workers import face_recognizer


def vector(position=0):
    value = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    value[position] = 1.0
    return value


def face(position=0, bbox=(10, 20, 50, 70)):
    return SimpleNamespace(normed_embedding=vector(position), bbox=np.array(bbox), det_score=0.99)


@pytest.fixture
def library(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [FacePerson.__table__, FaceEmbedding.__table__, FaceRecognitionRecord.__table__, AiCameraConfig.__table__]
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


def add_person(library, person_id=1, source="one", active=True, pic_uri="/pic?token=fake", server="image-server"):
    with library.factory.begin() as session:
        session.add(FacePerson(
            id=person_id, hik_source=source, hik_person_id="person-a", person_name=f"测试人员{person_id}",
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
        assert index.match(vector(0), 0.5)["person_id"] == 1
        assert index.match(vector(1), 0.5)["person_name"] == "测试人员2"
        unknown = index.match(vector(2), 0.5)
        assert unknown == {"matched": False, "person_id": None, "person_name": "未知人员", "similarity": 0.0}
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


def test_recorder_cooldown_deduplicates_camera_person_and_unknown(library, monkeypatch):
    add_person(library)
    recorder = records.RecognitionRecorder()
    clock = [100.0]
    monkeypatch.setattr(records.time, "monotonic", lambda: clock[0])
    known = {"person_id": 1, "person_name": "测试人员", "similarity": .9}
    unknown = {"person_id": None, "person_name": "未知人员", "similarity": .2}
    assert recorder.record(1, [known, known, unknown, unknown], 30) == 2
    library.statements.clear()
    for _ in range(5):
        assert recorder.record(1, [known, unknown], 30) == 0
    assert library.statements == []
    assert recorder.record(2, [known], 30) == 1
    clock[0] = 130
    assert recorder.record(1, [known, unknown], 30) == 2
    with library.factory() as session:
        assert session.query(FaceRecognitionRecord).count() == 5


def test_record_failure_is_bounded_and_can_retry(library, monkeypatch):
    recorder = records.RecognitionRecorder()
    scope = Mock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(records, "session_scope", scope)
    for _ in range(5):
        assert recorder.record(1, [{"person_id": None, "person_name": "未知人员", "similarity": .1}], 30) == 0
    scope.assert_called_once()
    assert recorder._recorded_at == {}


def test_consumer_dispatches_insightface_offsets_all_faces_and_never_alarms(library, removed_face_environment):
    consumer = FaceRecognitionConsumer(SPEC, {}, queue.Queue(), {}, lambda _: True)
    consumer.config_cache[7] = {
        "shm_name": "camera_7", "cap_interval": .5, "similarity_threshold": .7, "detection_threshold": .35,
    }
    consumer.frame_cache[7] = np.zeros((120, 200, 3), dtype=np.uint8)
    consumer._masks[7] = (None, 10, 100, 20, 150)
    detections = [dict(bbox=[0, 0, 30, 40], matched=False, person_id=None, person_name="未知人员",
                       similarity=.2, type="face_identity") for _ in range(3)]
    consumer.dispatch_inference_sync = Mock(return_value={"status": "ok", "detections": detections})
    result = consumer._process(consumer.frame_cache[7], 7)
    assert result[0] is False
    assert consumer.dispatch_inference_sync.call_args.args[1] == "insightface"
    assert consumer.dispatch_inference_sync.call_args.kwargs["task_meta"] == {"conf": .35, "similarity_threshold": .7}
    assert "timeout" not in consumer.dispatch_inference_sync.call_args.kwargs
    assert consumer.post_process(7, result).shape == (120, 200, 3)
    snapshot = consumer.get_monitor_status("camera_7")
    assert snapshot["count"] == 3 and snapshot["alarm"] is False
    assert snapshot["detections"][0]["bbox"] == [20, 10, 50, 50]
    assert snapshot["frame_width"] == 200
    assert consumer._should_process_now(7, consumer.config_cache[7])
    consumer._last_process_at[7] = time.time()
    assert not consumer._should_process_now(7, consumer.config_cache[7])
    consumer.post_process(7, (False, {"status": "timeout", "detections": []}))
    assert consumer.get_monitor_status("camera_7")["detections"] == []


def test_electronics_feature_config_and_alarm_rejection():
    assert SPEC.departments == ("electronics_electrician",)
    assert SPEC.required_models == ("insightface",)
    assert SPEC.resolve_camera_department(None) == "electronics_electrician"
    with pytest.raises(ValueError):
        SPEC.resolve_camera_department("research_institute")
    with pytest.raises(ValueError):
        FaceRecognitionConfigSchema.model_validate({"alarm": {"sql": {"enable": True}}})


def test_monitor_status_exposes_identities_and_clears_expired_results(monkeypatch):
    from AiVision.platform.orchestrator import Orchestrator

    orchestrator = object.__new__(Orchestrator)
    orchestrator.camera_runtime_manager = Mock(list_running=Mock(return_value=["camera_7"]))
    snapshot = {"updated_at_s": time.time(), "count": 1, "detections": [{"person_name": "测试"}],
                "frame_width": 200, "frame_height": 120}
    orchestrator.consumers = {"recognize_face": Mock(get_monitor_status=Mock(return_value=snapshot))}
    assert orchestrator.get_feature_monitor_status("camera_7", "recognize_face")["detections"] == snapshot["detections"]
    snapshot["updated_at_s"] -= 10
    assert orchestrator.get_feature_monitor_status("camera_7", "recognize_face")["detections"] == []


def test_record_api_has_department_scope_pagination_and_auth(library):
    from auth.auth import get_current_user
    from AiVision.api.face_recognition import router

    with library.factory.begin() as session:
        for camera_id, department in [(1, "electronics_electrician"), (2, "research_institute")]:
            session.add(AiCameraConfig(id=camera_id, name=f"测试摄像头{camera_id}", shm_name=f"camera_{camera_id}",
                                       url="test-camera", department=department))
            session.add(FaceRecognitionRecord(camera_id=camera_id, person_id=None, person_name="未知人员", similarity=.1))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"role": "viewer", "departments": ["electronics_electrician"]}
    with TestClient(app) as client:
        response = client.get("/api/face-recognition/records?page_size=1")
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["camera_id"] == 1
        assert client.get("/api/face-recognition/records?camera_id=2").json()["total"] == 0
        assert client.get("/api/face-recognition/records?page=2").json()["items"] == []
        assert client.get("/api/face-recognition/records?page_size=101").status_code == 422
        app.dependency_overrides[get_current_user] = lambda: {"role": "viewer", "departments": ["research_institute"]}
        assert client.get("/api/face-recognition/records").status_code == 403


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
    config.write_text("models:\n  yolo_face:\n    path: /models/face.pt\n")
    monkeypatch.setattr(settings.model_paths, "config_path", str(config))
    try:
        model_paths.save_model_path("insightface", str(model_directory))
        assert model_paths.load_model_paths()["yolo_face"] == "/models/face.pt"
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
        ctx_id=0, input_size=(640, 640), det_thresh=0.5,
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
        model.prepare.assert_not_called()
        model.session.set_providers.assert_not_called()


def test_missing_models_fail_before_loading_or_downloading(tmp_path, monkeypatch):
    get_model = Mock()
    monkeypatch.setitem(sys.modules, "insightface.model_zoo", SimpleNamespace(get_model=get_model))
    with pytest.raises(ValueError):
        face_recognizer.InsightFaceRecognizer(str(tmp_path))
    get_model.assert_not_called()
