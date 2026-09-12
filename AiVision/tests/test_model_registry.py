from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import queue

import numpy as np
import pytest
import yaml

from AiVision.platform.inference.model_registry import MODEL_SPECS, get_model_spec
from AiVision.platform.inference import model_paths
from AiVision.platform.inference.workers.yolo_detector import YoloDetectorWorker


@pytest.fixture
def local_paths(tmp_path, monkeypatch):
    config = tmp_path / "model_paths.yaml"
    weight = tmp_path / "model.pt"
    weight.write_bytes(b"test weights")
    monkeypatch.setattr(model_paths.settings.model_paths, "config_path", str(config))
    model_paths.clear_model_paths_cache()
    yield config, weight
    model_paths.clear_model_paths_cache()


def test_fixed_registry_has_explicit_inference_settings():
    assert set(MODEL_SPECS) == {"yolo_human", "yolo_phone", "yolo_face", "insightface"}
    assert get_model_spec("yolo_human").class_filter == (0,)
    assert get_model_spec("yolo_phone").class_filter == (1,)
    assert get_model_spec("yolo_face").conf == 0.6
    assert all(spec.worker_class is YoloDetectorWorker for spec in MODEL_SPECS.values() if spec.type == "yolo")
    from AiVision.platform.inference.workers.face_recognizer import FaceRecognizerWorker
    assert get_model_spec("insightface").worker_class is FaceRecognizerWorker
    assert get_model_spec("insightface").type == "insightface"
    assert get_model_spec("insightface").conf == 0.5
    with pytest.raises(TypeError):
        MODEL_SPECS["new"] = get_model_spec("yolo_human")
    with pytest.raises(FrozenInstanceError):
        get_model_spec("yolo_human").name = "new"
    with pytest.raises(KeyError):
        get_model_spec("new")


def test_model_orm_is_no_longer_registered():
    from AiVision.core.db import Base
    assert "ai_model" not in Base.metadata.tables


def test_save_preserves_comments_other_entries_permissions_and_clears_cache(local_paths):
    config, weight = local_paths
    original = (
        "# 手写说明\nmodels:\n"
        "  yolo_human:\n    path: /old/model.pt # 保留行尾说明\n"
        "  yolo_phone:\n    path: /other.pt\n"
        "  unused:\n    path: /site/custom.pt\n"
        "# 保留最后说明\n"
    )
    config.write_text(original)
    config.chmod(0o640)
    assert model_paths.load_model_paths()["yolo_human"] == "/old/model.pt"
    model_paths.save_model_path("yolo_human", str(weight))
    updated = config.read_text()
    assert updated == original.replace("/old/model.pt", f'"{weight}"')
    assert model_paths.load_model_paths()["yolo_human"] == str(weight)
    assert config.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("source", [
    "",
    "# 手写说明\n",
    "models:\n  yolo_phone:\n    path: /phone.pt\n",
    "models:\n  yolo_phone:\n    path: /phone.pt\nother: keep\n",
    "models:\n  yolo_phone:\n    path: /phone.pt",
    "models: {} # 保留注释\n",
    "models:\n  yolo_human: {}\n",
    "models:\n    yolo_phone:\n        path: /phone.pt\n",
])
def test_save_adds_missing_path_without_losing_existing_data(local_paths, source):
    config, weight = local_paths
    config.write_text(source)
    model_paths.save_model_path("yolo_human", str(weight))
    data = yaml.safe_load(config.read_text())
    assert data["models"]["yolo_human"]["path"] == str(weight)
    if "other:" in source:
        assert data["other"] == "keep"
    if "yolo_phone" in source:
        assert data["models"]["yolo_phone"]["path"] == "/phone.pt"


@pytest.mark.parametrize("value", ["", "relative.pt", "https://example.com/model.pt", "/not-existing-model.pt", "/bad\x00path"])
def test_invalid_paths_do_not_write(local_paths, value):
    config, _ = local_paths
    with pytest.raises(ValueError):
        model_paths.save_model_path("yolo_human", value)
    assert not config.exists()


def test_empty_file_directory_and_unknown_model_are_rejected(local_paths, tmp_path):
    config, weight = local_paths
    empty = tmp_path / "empty.pt"
    empty.touch()
    for path in (empty, tmp_path):
        with pytest.raises(ValueError):
            model_paths.save_model_path("yolo_human", str(path))
    with pytest.raises(KeyError):
        model_paths.save_model_path("custom", str(weight))
    assert not config.exists()


@pytest.mark.parametrize("source", [
    "models: [broken",
    "models:\n  yolo_human:\n    path: /a\n    path: /b\n",
    "models:\n  yolo_human: &model\n    path: /a\n  yolo_phone: *model\n",
    "model_paths:\n  yolo_human: /a\n",
    "models:\n  yolo_human: /a\n",
])
def test_malformed_or_legacy_yaml_is_not_silently_overwritten(local_paths, source):
    config, weight = local_paths
    config.write_text(source)
    with pytest.raises(ValueError):
        model_paths.save_model_path("yolo_human", str(weight))
    assert config.read_text() == source


def test_failed_atomic_replace_preserves_config_and_removes_temp(local_paths, monkeypatch):
    config, weight = local_paths
    original = "models:\n  yolo_human:\n    path: /old.pt\n"
    config.write_text(original)
    assert model_paths.load_model_paths()["yolo_human"] == "/old.pt"

    def fail_replace(*args):
        raise OSError("disk error")

    monkeypatch.setattr(model_paths.os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk error"):
        model_paths.save_model_path("yolo_human", str(weight))
    assert config.read_text() == original
    assert model_paths.load_model_paths()["yolo_human"] == "/old.pt"
    assert not list(config.parent.glob("*.tmp"))
    assert not list(config.parent.glob(".*.tmp"))


def test_path_quotes_and_unicode_round_trip(local_paths):
    config, weight = local_paths
    special = weight.with_name('模型 "one".pt')
    weight.rename(special)
    model_paths.save_model_path("yolo_human", str(special))
    assert model_paths.load_model_paths()["yolo_human"] == str(special)


def test_multiline_yaml_scalar_can_be_updated_without_changing_other_entries(local_paths):
    config, weight = local_paths
    config.write_text("models:\n  yolo_human:\n    path: >-\n      /old.pt\n  yolo_phone:\n    path: /phone.pt\n")
    model_paths.save_model_path("yolo_human", str(weight))
    assert model_paths.load_model_paths() == {"yolo_human": str(weight), "yolo_phone": "/phone.pt"}


def test_missing_local_path_never_uses_database_or_network(local_paths):
    assert model_paths.load_model_paths() == {}


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


@pytest.mark.parametrize("name,expected_classes,label,conf", [
    ("yolo_human", [0], "person", 0.3),
    ("yolo_phone", [1], "phone", 0.3),
    ("yolo_face", [0, 1], "face", 0.6),
])
def test_shared_yolo_uses_each_logical_models_fixed_parameters(name, expected_classes, label, conf):
    worker = YoloDetectorWorker(
        infer_queues={name: queue.Queue()}, result_queues={},
        model_name=name, model_path="/unused.pt",
    )
    calls = []
    boxes = Boxes(
        xyxy=Tensor([[0, 0, 10, 10], [2, 2, 8, 8]]),
        conf=Tensor([0.8, 0.9]), cls=Tensor([0, 1]),
    )

    def predict(frame, **kwargs):
        calls.append(kwargs)
        return [SimpleNamespace(boxes=boxes)]

    model = SimpleNamespace(predict=predict)
    result = worker.infer(model, None, {"model_name": name})
    assert [item["class_id"] for item in result] == expected_classes
    assert all(item["type"] == label for item in result)
    assert calls[-1] == {"conf": conf, "iou": 0.5, "verbose": False}
    worker.infer(model, None, {"model_name": name, "conf": 0.7, "iou": 0.4})
    assert calls[-1]["conf"] == 0.7
    assert calls[-1]["iou"] == 0.4


def test_shared_worker_reads_queues_fairly_and_preserves_request_identity():
    inputs = {name: queue.Queue() for name in ("yolo_human", "yolo_phone")}
    worker = YoloDetectorWorker(
        infer_queues=inputs, result_queues={}, model_name="yolo_human", model_path="/unused.pt",
    )
    inputs["yolo_human"].put({"request_id": "human", "model_name": "wrong"})
    inputs["yolo_human"].put({"request_id": "human2"})
    inputs["yolo_phone"].put({"request_id": "phone"})
    assert worker._next_task() == {"request_id": "human", "model_name": "yolo_human"}
    assert worker._next_task() == {"request_id": "phone", "model_name": "yolo_phone"}
    assert worker._next_task() == {"request_id": "human2", "model_name": "yolo_human"}
    assert worker._next_task() is None
    for removed in ("initial_configs", "update_camera_info", "update_status"):
        assert not hasattr(worker, removed)


def test_worker_stop_joins_after_terminate_and_kill():
    worker = YoloDetectorWorker(
        infer_queues={}, result_queues={}, model_name="yolo_human", model_path="/unused.pt",
    )
    calls = []
    process = SimpleNamespace(
        alive=True,
        is_alive=lambda: process.alive,
        join=lambda **kwargs: calls.append("join"),
        terminate=lambda: calls.append("terminate"),
        kill=lambda: (calls.append("kill"), setattr(process, "alive", False)),
    )
    worker._proc = process
    worker.stop()
    assert calls == ["join", "terminate", "join", "kill", "join"]
    assert not worker.is_alive()
