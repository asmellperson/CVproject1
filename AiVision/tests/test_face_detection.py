"""纯检测链路使用模拟模型、推理队列和告警出口，不访问人员库或生产服务。"""
import queue
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from AiVision.features.face_dwell.spec import SPEC
from AiVision.inference import model_paths
from AiVision.inference.insightface_detector import InsightFaceDetector
from AiVision.inference.workers.face_detector import FaceDetectorWorker


@pytest.fixture
def detector_backend(tmp_path, monkeypatch):
    path = tmp_path / "det_10g.onnx"
    path.write_bytes(b"mock detector")
    model = Mock(taskname="detection")
    model.session.get_providers.return_value = ["CUDAExecutionProvider"]
    model.detect.return_value = (np.empty((0, 5)), None)
    get_model = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        get_available_providers=lambda: ["CUDAExecutionProvider"],
    ))
    monkeypatch.setitem(sys.modules, "insightface.model_zoo", SimpleNamespace(get_model=get_model))
    return SimpleNamespace(path=path, model=model, load=get_model)


def task(frame=None, **values):
    return {"model_name": "insightface_detection", "camera_id": 1, "roi_id": 0,
            "function_name": "detect_face", "request_id": "face-request",
            "frame": np.zeros((120, 240, 3), np.uint8) if frame is None else frame,
            "conf": .6, "iou": .3, **values}


def make_worker(path):
    return FaceDetectorWorker({}, {}, "insightface_detection", str(path))


def test_pure_worker_import_and_execution_do_not_import_identity_business():
    source = '''
import importlib.abc, sys
from unittest.mock import Mock
class NoIdentity(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('AiVision.features.face_recognition.library',
                                'AiVision.features.face_recognition', 'ultralytics')):
            raise AssertionError('unexpected import: ' + fullname)
sys.meta_path.insert(0, NoIdentity())
from AiVision.inference.workers.face_detector import FaceDetectorWorker
model = Mock()
model.detect.return_value = ([], None)
worker = FaceDetectorWorker({}, {}, 'insightface_detection', '/unused.onnx')
assert worker.infer(model, None, {'conf': .6, 'iou': .3}) == []
'''
    result = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("visible", ["3", "4,1"])
def test_detector_loads_only_one_local_session_and_respects_gpu(detector_backend, monkeypatch, visible):
    backend = detector_backend
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", visible)
    worker = make_worker(backend.path)
    model = worker.load_model()
    for values in [dict(conf=.1, iou=.9), dict(conf=.9, iou=.1), dict(conf=0, iou=0)]:
        assert worker._execute_task(model, task(**values))["status"] == "ok"
        assert backend.model.det_thresh == values["conf"]
        assert backend.model.nms_thresh == values["iou"]
    backend.load.assert_called_once_with(
        str(backend.path), download=False, providers=["CUDAExecutionProvider"],
        provider_options=[{"device_id": "0"}],
    )
    backend.model.prepare.assert_called_once_with(ctx_id=0, input_size=(640, 640))
    backend.model.session.disable_fallback.assert_called_once()
    backend.model.session.set_providers.assert_not_called()
    assert __import__("os").environ["CUDA_VISIBLE_DEVICES"] == visible


def test_detection_path_requires_only_a_readable_onnx(detector_backend, tmp_path):
    path = detector_backend.path
    assert model_paths.validate_model_path(str(path), model_type="insightface_detection") == str(path)
    assert len(list(tmp_path.iterdir())) == 1
    for invalid in (tmp_path, tmp_path / "missing.onnx", tmp_path / "model.pt"):
        with pytest.raises(ValueError):
            model_paths.validate_model_path(str(invalid), model_type="insightface_detection")
    path.write_bytes(b"")
    with pytest.raises(ValueError):
        make_worker(path).load_model()
    detector_backend.load.assert_not_called()


@pytest.mark.parametrize("failure", ["unavailable", "provider_failed", "wrong_model", "load_failed"])
def test_detection_load_failures_are_explicit(detector_backend, monkeypatch, failure):
    backend = detector_backend
    if failure == "unavailable":
        monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
            get_available_providers=lambda: ["CPUExecutionProvider"],
        ))
    elif failure == "provider_failed":
        backend.model.session.get_providers.return_value = ["CPUExecutionProvider"]
    elif failure == "wrong_model":
        backend.model.taskname = "recognition"
    else:
        backend.load.side_effect = RuntimeError("invalid ONNX")
    with pytest.raises(RuntimeError):
        make_worker(backend.path).load_model()
    backend.model.detect.assert_not_called()
    backend.model.session.set_providers.assert_not_called()
    if failure == "unavailable":
        backend.load.assert_not_called()


def test_detector_worker_reports_loading_failure_to_runtime(detector_backend):
    detector_backend.load.side_effect = RuntimeError("detector load failed")
    worker = make_worker(detector_backend.path)
    worker._run()
    assert worker.is_failed() and not worker.is_ready()
    assert worker.failure_message() == "detector load failed"


@pytest.mark.parametrize("count", [0, 1, 3])
def test_standard_detection_protocol_for_all_faces(detector_backend, count):
    backend = detector_backend
    boxes = np.array([[10 + 40*i, 2, 30 + 40*i, 40, .9] for i in range(count)]).reshape(-1, 5)
    backend.model.detect.return_value = (boxes, None)
    worker = make_worker(backend.path)
    frame = np.full((120, 240, 3), [10, 20, 30], np.uint8)
    result = worker._execute_task(worker.load_model(), task(frame))
    assert result["status"] == "ok"
    assert result["request_id"] == "face-request" and result["camera_id"] == 1
    assert len(result["detections"]) == count
    for item, box in zip(result["detections"], boxes):
        assert item == {"bbox": box[:4].tolist(), "confidence": .9, "class_id": 0, "type": "face"}
    assert backend.model.detect.call_args.args[0] is frame
    assert backend.model.detect.call_args.kwargs == {"max_num": 0, "metric": "default"}


@pytest.mark.parametrize("field", ["conf", "iou"])
@pytest.mark.parametrize("invalid", [-.1, 1.1, float("nan"), float("inf"), None, True, "0.5"])
def test_invalid_task_thresholds_fail_instead_of_becoming_empty_detection(detector_backend, field, invalid):
    worker = make_worker(detector_backend.path)
    result = worker._execute_task(worker.load_model(), task(**{field: invalid}))
    assert result["status"] == "error"
    assert result["error_message"] and result["detections"] == []
    detector_backend.model.detect.assert_not_called()


def test_inference_error_preserves_failure_protocol(detector_backend):
    worker = make_worker(detector_backend.path)
    detector_backend.model.detect.side_effect = RuntimeError("CUDA execution failed")
    result = worker._execute_task(worker.load_model(), task())
    assert result["status"] == "error"
    assert result["error_message"] == "CUDA execution failed"
    assert result["inference_ms"] >= 0 and result["model_name"] == "insightface_detection"


@pytest.mark.parametrize("frame", [np.empty((0, 10, 3)), np.zeros((10, 10)), np.zeros((10, 10, 4)), "invalid"])
def test_invalid_images_fail_without_invoking_detector(detector_backend, frame):
    worker = make_worker(detector_backend.path)
    result = worker._execute_task(worker.load_model(), task(frame))
    assert result["status"] == "error" and "BGR" in result["error_message"]
    detector_backend.model.detect.assert_not_called()


def test_worker_loads_once_and_routes_each_queued_camera_request(detector_backend):
    worker = make_worker(detector_backend.path)
    inputs, outputs = queue.Queue(), queue.Queue()
    worker.infer_queues = {"insightface_detection": inputs}
    worker._queue_names = ("insightface_detection",)
    received = []

    def publish(result, timeout):
        outputs.put(result)
        if outputs.qsize() == 3:
            worker._stop_event.set()

    def detect(frame, **_kwargs):
        received.append((detector_backend.model.det_thresh, detector_backend.model.nms_thresh))
        return np.empty((0, 5)), None

    detector_backend.model.detect.side_effect = detect
    worker.result_queues = {"detect_face": SimpleNamespace(put=publish)}
    for i, (conf, iou) in enumerate([(.1, .9), (.8, .2), (0, 1)]):
        inputs.put(task(camera_id=i+1, request_id=f"request-{i}", conf=conf, iou=iou))
    worker._run()
    assert worker.is_ready() and not worker.is_failed()
    detector_backend.load.assert_called_once()
    assert received == [(.1, .9), (.8, .2), (0, 1)]
    assert [(r["camera_id"], r["request_id"], r["status"]) for r in list(outputs.queue)] == [
        (i+1, f"request-{i}", "ok") for i in range(3)
    ]


def test_face_roi_detector_and_tracker_have_independent_parameters(detector_backend, monkeypatch):
    from AiVision.features._shared import dwell_consumer

    worker = make_worker(detector_backend.path)
    model = worker.load_model()
    consumer = SPEC.consumer_cls(spec=SPEC, infer_dict={}, result_queue=None,
                                 latest_frames={}, is_camera_active=lambda _: True)
    frame = np.full((120, 240, 3), 10, np.uint8)
    consumer.config_cache[1] = SPEC.config_schema(value={
        "roi_pos": [[.25, .25], [.75, .25], [.75, .75], [.25, .75]],
        "FACE_SCORE_THR": .2, "DETECTION_IOU_THR": .1, "TRACK_IOU_THR": .9,
    }).value.model_dump()
    consumer.frame_cache[1] = frame
    detector_backend.model.detect.return_value = (np.array([[10, 10, 30, 40, .9]]), None)
    rectangle = Mock()
    monkeypatch.setattr(dwell_consumer.cv2, "rectangle", rectangle)

    def dispatch(camera_id, name, roi, *, task_meta):
        assert name == "insightface_detection" and roi.shape == (60, 120, 3)
        return worker._execute_task(model, task(roi, **task_meta))

    consumer.dispatch_inference_sync = dispatch
    for confidence, detection_iou, track_iou in [(.2, .1, .9), (0, 1, 0)]:
        consumer.config_cache[1].update(FACE_SCORE_THR=confidence, DETECTION_IOU_THR=detection_iou,
                                        TRACK_IOU_THR=track_iou)
        result = consumer._process(consumer._get_roi(1, frame), 1)
        consumer.post_process(1, result)
        assert detector_backend.model.det_thresh == confidence
        assert detector_backend.model.nms_thresh == detection_iou
        assert consumer._trackers[1].iou_thr == track_iou
        assert rectangle.call_args.args[1:3] == ((70, 40), (90, 70))


@pytest.mark.parametrize("period", [.1, .5, 1.0])
def test_dwell_time_loss_updates_and_alarm_cooldown_at_different_rates(monkeypatch, period):
    from AiVision.alarms.dispatcher import AlarmDispatcher
    from AiVision.features._shared import consumer as base_consumer
    from AiVision.features._shared import dwell_consumer

    now = [100.0]
    monkeypatch.setattr(dwell_consumer.time, "time", lambda: now[0])
    monkeypatch.setattr(dwell_consumer, "monotonic", lambda: now[0])
    dispatcher = AlarmDispatcher()
    monkeypatch.setattr(dispatcher, "_execute", Mock())
    monkeypatch.setattr(base_consumer, "alarm_dispatcher", dispatcher)
    consumer = SPEC.consumer_cls(spec=SPEC, infer_dict={}, result_queue=None,
                                 latest_frames={}, is_camera_active=lambda _: True)
    consumer.config_cache[1] = {
        **SPEC.config_schema(value={"MAX_TIME": 2.0, "MAX_LOST": 2, "alarm_interval": 3.0}).value.model_dump(),
        "shm_name": "mock-face", "name": "mock-face", "department": SPEC.departments[0], "sql_enable": True,
    }
    frame = np.zeros((120, 240, 3), np.uint8)
    boxes = [{"bbox": [10, 10, 30, 40], "type": "face", "confidence": .9, "class_id": 0}]
    consumer.dispatch_inference_sync = Mock(return_value={"status": "ok", "detections": boxes})
    for i in range(round(6 / period) + 1):
        now[0] = 100 + i * period
        result = consumer._process(frame, 1)
        consumer._handle_alarm(1, result, frame)
        assert result[0] == (i * period >= 2)
    assert dispatcher._execute.call_count == 2
    track_id = next(iter(consumer._trackers[1].tracks))
    assert consumer._trackers[1].tracks[track_id].first_seen == 0
    consumer.dispatch_inference_sync.return_value = {"status": "ok", "detections": []}
    for lost in [1, 2]:
        now[0] += period
        assert consumer._process(frame, 1)[0] is False
        assert consumer._trackers[1].tracks[track_id].lost == lost
    consumer.dispatch_inference_sync.return_value = {"status": "ok", "detections": boxes}
    assert consumer._process(frame, 1)[0] is True
    assert list(consumer._trackers[1].tracks) == [track_id]
    consumer.dispatch_inference_sync.return_value = {"status": "ok", "detections": []}
    for _ in range(3):
        consumer._process(frame, 1)
    assert not consumer._trackers[1].tracks
    consumer.dispatch_inference_sync.return_value = {"status": "ok", "detections": boxes}
    assert consumer._process(frame, 1)[0] is False
    assert next(iter(consumer._trackers[1].tracks)) != track_id


@pytest.mark.parametrize("shape", [(120, 240), (240, 120), (123, 257)])
def test_scrfd_actual_resize_bgr_threshold_and_nms_with_mock_onnx(shape):
    """安装 InsightFace 的环境执行其真实预后处理；ONNX 输出始终模拟。"""
    scrfd = pytest.importorskip("insightface.model_zoo.scrfd")
    session = Mock()
    session.get_inputs.return_value = [SimpleNamespace(name="input", shape=[1, 3, "h", "w"])]
    session.get_outputs.return_value = [SimpleNamespace(name=str(i), shape=[None, 1]) for i in range(9)]
    raw = [([48, 48, 112, 112], .95, (80, 80)), ([50, 50, 110, 110], .8, (88, 80)),
           ([200, 50, 260, 110], .7, (232, 80))]

    def run(names, inputs):
        blob = inputs["input"]
        assert blob.shape == (1, 3, 640, 640)
        np.testing.assert_allclose(blob[0, :, 0, 0], (np.array([30, 20, 10]) - 127.5) / 128)
        scores, boxes, landmarks = [], [], []
        for stride in [8, 16, 32]:
            count = (640 // stride) ** 2 * 2
            scores.append(np.zeros((count, 1), np.float32))
            boxes.append(np.zeros((count, 4), np.float32))
            landmarks.append(np.zeros((count, 10), np.float32))
        for box, score, (x, y) in raw:
            index = ((y // 8) * 80 + x // 8) * 2
            scores[0][index] = score
            boxes[0][index] = np.array([x-box[0], y-box[1], box[2]-x, box[3]-y]) / 8
        return scores + boxes + landmarks

    session.run.side_effect = run
    model = scrfd.SCRFD(session=session)
    model.prepare(ctx_id=0, input_size=(640, 640))
    detector = InsightFaceDetector.__new__(InsightFaceDetector)
    detector.model = model
    frame = np.full((*shape, 3), [10, 20, 30], np.uint8)
    scale = (640 if shape[0] > shape[1] else int(640 * shape[0] / shape[1])) / shape[0]
    for confidence, nms, expected in [(.1, .3, [0, 2]), (.1, 1, [0, 1, 2]), (.9, 1, [0]), (1, 0, [])]:
        detected, _ = detector.detect(frame, confidence=confidence, nms_threshold=nms)
        assert len(detected) == len(expected)
        if expected:
            np.testing.assert_allclose(detected[:, :4], np.array([raw[i][0] for i in expected]) / scale, rtol=1e-6)
