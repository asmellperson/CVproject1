"""公共姿态、分类 Worker 的离线模型合同测试。"""
import math
import pickle
import socket
import sys
from multiprocessing.reduction import ForkingPickler
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from AiVision.inference.workers.uniform_classifier import UniformClassifierWorker
from AiVision.inference.workers.yolo_pose import YoloPoseWorker


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("模型测试不得访问网络")
    monkeypatch.setattr(socket.socket, "connect", fail)


class Tensor:
    def __init__(self, values):
        self.values = np.asarray(values)

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class Boxes(SimpleNamespace):
    def __len__(self):
        return len(self.cls.values)


@pytest.fixture
def pose():
    worker = YoloPoseWorker({}, {}, "yolo_guard_pose", "/unused.engine")
    points = [[[100 + person * 20 + index, 200 + index, 0.75] for index in range(17)]
              for person in range(2)]
    result = SimpleNamespace(
        boxes=Boxes(xyxy=Tensor([[100, 200, 300, 400], [120, 200, 320, 400]]),
                    conf=Tensor([0.93, 0.85]), cls=Tensor([0, 0])),
        keypoints=SimpleNamespace(data=Tensor(points)),
    )
    calls = []

    def predict(frame, **kwargs):
        calls.append(kwargs)
        return [result]

    return worker, SimpleNamespace(predict=predict), result, calls, points


def test_pose_preserves_pixels_and_returns_serializable_inference_contract(pose):
    worker, model, _, calls, points = pose
    task = {"model_name": "yolo_guard_pose", "camera_id": 12, "function_name": "synthetic",
            "roi_id": 3, "request_id": "pose:12:3", "frame": np.zeros((480, 640, 3), np.uint8)}
    result = worker._execute_task(model, task)
    for field in ("model_name", "camera_id", "function_name", "roi_id", "request_id"):
        assert result[field] == task[field]
    assert result["status"] == "ok"
    detections = result["detections"]
    assert len(detections) == 2
    assert detections[0] == {"bbox": [100., 200., 300., 400.], "confidence": 0.93,
                             "class_id": 0, "type": "pose", "keypoints": points[0]}
    for detection in detections:
        assert len(detection["keypoints"]) == 17
        assert all(type(value) is float for point in detection["keypoints"] for value in point)
        assert all(type(value) is float for value in detection["bbox"])
        assert type(detection["class_id"]) is int
    assert pickle.loads(ForkingPickler.dumps(result)) == result
    assert calls == [{"conf": 0.3, "iou": 0.5, "verbose": False}]
    worker.infer(model, task["frame"], {**task, "conf": 0.7, "iou": 0.2, "imgsz": 960})
    assert calls[-1] == {"conf": 0.7, "iou": 0.2, "imgsz": 960, "verbose": False}


@pytest.mark.parametrize("malformed", ["count", "joint_count", "no_confidence", "no_keypoints", "bbox"])
def test_pose_malformed_output_is_a_model_error_instead_of_misaligned_detections(pose, malformed):
    worker, model, result, _, _ = pose
    if malformed == "count":
        result.keypoints.data = Tensor(np.zeros((1, 17, 3)))
    elif malformed == "joint_count":
        result.keypoints.data = Tensor(np.zeros((2, 16, 3)))
    elif malformed == "no_confidence":
        result.keypoints.data = Tensor(np.zeros((2, 17, 2)))
    elif malformed == "no_keypoints":
        result.keypoints = None
    else:
        result.boxes.xyxy = Tensor(np.zeros((1, 4)))
    task = {"model_name": "yolo_guard_pose", "frame": None, "request_id": "bad-pose",
            "function_name": "synthetic", "camera_id": 1, "roi_id": 0}
    with pytest.raises(ValueError, match="姿态模型"):
        worker.infer(model, None, task)
    response = worker._execute_task(model, task)
    assert response["request_id"] == "bad-pose"
    assert response["status"] == "error"
    assert response["error_code"] == "model_inference_error"
    assert response["detections"] == []


def test_pose_empty_result_is_success(pose):
    worker, model, result, _, _ = pose
    result.boxes = Boxes(xyxy=Tensor(np.empty((0, 4))), conf=Tensor([]), cls=Tensor([]))
    result.keypoints.data = Tensor(np.empty((0, 17, 3)))
    assert worker.infer(model, None, {"model_name": "yolo_guard_pose"}) == []


def test_pose_loads_only_valid_local_model_with_explicit_task(tmp_path, monkeypatch):
    path = tmp_path / "model.engine"
    path.write_bytes(b"local pose model")
    calls = []
    ultralytics = ModuleType("ultralytics")
    ultralytics.YOLO = lambda *args, **kwargs: calls.append((args, kwargs)) or "model"
    monkeypatch.setitem(sys.modules, "ultralytics", ultralytics)
    worker = YoloPoseWorker({}, {}, "yolo_guard_pose", str(path))
    assert worker.load_model() == "model"
    assert calls == [((str(path),), {"task": "pose"})]
    worker.model_path = str(tmp_path / "missing.pt")
    with pytest.raises(ValueError):
        worker.load_model()
    assert len(calls) == 1


@pytest.fixture
def classifier(tmp_path, monkeypatch):
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    path = tmp_path / "uniform.pt"
    state = torch.nn.Linear(3, 2).state_dict()
    checkpoint = {"model_state_dict": state, "class_to_idx": {"non_uniform": 0, "uniform": 1}}
    calls, pixels = [], []
    timm = ModuleType("timm")
    data = ModuleType("timm.data")

    def create_model(name, **kwargs):
        calls.append((name, kwargs))
        return torch.nn.Linear(3, kwargs["num_classes"])

    def resolve_data_config(config, *, model):
        assert config == {} and model.training is False
        return {"input_size": (3, 224, 224)}

    def create_transform(**kwargs):
        assert kwargs == {"input_size": (3, 224, 224), "is_training": False}

        def transform(image):
            pixels.append(image.getpixel((0, 0)))
            return torch.tensor(pixels[-1], dtype=torch.float32) / 255
        return transform

    timm.create_model = create_model
    data.resolve_data_config = resolve_data_config
    data.create_transform = create_transform
    monkeypatch.setitem(sys.modules, "timm", timm)
    monkeypatch.setitem(sys.modules, "timm.data", data)
    worker = UniformClassifierWorker({}, {}, "guard_uniform", str(path))
    return SimpleNamespace(torch=torch, path=path, checkpoint=checkpoint,
                           calls=calls, pixels=pixels, worker=worker)


@pytest.mark.parametrize("prefix", ["", "module."])
@pytest.mark.parametrize("uniform_index,probability", [(1, 0.913), (0, 0.25)])
def test_uniform_loads_strict_local_checkpoint_and_returns_positive_probability(classifier, prefix, uniform_index, probability):
    fixture = classifier
    probabilities = [1 - probability, probability] if uniform_index == 1 else [probability, 1 - probability]
    fixture.checkpoint["class_to_idx"] = {"uniform": uniform_index, "non_uniform": 1 - uniform_index}
    fixture.checkpoint["model_state_dict"] = {
        prefix + "weight": fixture.torch.zeros(2, 3),
        prefix + "bias": fixture.torch.tensor([math.log(value) for value in probabilities]),
    }
    fixture.torch.save(fixture.checkpoint, fixture.path)
    model = fixture.worker.load_model()
    assert fixture.calls == [("convnextv2_tiny.fcmae_ft_in22k_in1k", {"pretrained": False, "num_classes": 2})]
    frame = np.full((10, 20, 3), [10, 20, 30], np.uint8)
    result = fixture.worker.infer(model, frame, {"model_name": "guard_uniform"})
    assert result == [{"type": "uniform", "confidence": pytest.approx(probability)}]
    assert type(result[0]["confidence"]) is float
    assert fixture.pixels == [(30, 20, 10)]
    assert model.training is False
    assert next(model.parameters()).device.type == "cpu"
    assert pickle.loads(ForkingPickler.dumps(result)) == result


@pytest.mark.parametrize("missing", ["model_state_dict", "class_to_idx", "uniform"])
def test_uniform_missing_checkpoint_fields_fail_before_model_creation(classifier, missing):
    fixture = classifier
    if missing == "uniform":
        fixture.checkpoint["class_to_idx"] = {"other": 0, "non_uniform": 1}
    else:
        fixture.checkpoint.pop(missing)
    fixture.torch.save(fixture.checkpoint, fixture.path)
    with pytest.raises(ValueError, match=missing):
        fixture.worker.load_model()
    assert fixture.calls == []


@pytest.mark.parametrize("invalid", ["missing_weight", "unexpected_weight", "wrong_shape"])
def test_uniform_incompatible_weights_fail_strictly(classifier, invalid):
    fixture = classifier
    state = fixture.checkpoint["model_state_dict"]
    if invalid == "missing_weight":
        del state["weight"]
    elif invalid == "unexpected_weight":
        state["unrelated"] = fixture.torch.zeros(1)
    else:
        state["weight"] = fixture.torch.zeros(3, 3)
    fixture.torch.save(fixture.checkpoint, fixture.path)
    with pytest.raises(RuntimeError):
        fixture.worker.load_model()


@pytest.mark.parametrize("classes", [
    {"uniform": True, "other": 0}, {"uniform": 0, "other": 0}, {"uniform": 2, "other": 0},
])
def test_uniform_invalid_class_indices_are_rejected(classifier, classes):
    fixture = classifier
    fixture.checkpoint["class_to_idx"] = classes
    fixture.torch.save(fixture.checkpoint, fixture.path)
    with pytest.raises(ValueError, match="class_to_idx"):
        fixture.worker.load_model()
    assert fixture.calls == []
