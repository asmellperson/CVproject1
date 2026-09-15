"""推理包独立导入、模型配置定位及真实 Worker spawn 入口；不运行真实模型。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def isolated_environment(tmp_path):
    env = os.environ.copy()
    for name in ("CONFIG_TEST_MYSQL_URL", "LOGISTICS_TEST_MYSQL_URL", "HUMAN_TEST_MYSQL_URL"):
        env.pop(name, None)
    env.update(
        PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1",
        MYSQL_DB_URL="127.0.0.1", MYSQL_DB_PORT="1", MYSQL_DB_USER="inference_package_test",
        MYSQL_DB_PASSWORD="test-only-unused", MYSQL_DB_NAME="inference_package_test",
        AUTO_CREATE_DB="false", DATA_PATH=str(tmp_path / "media"),
        AUTH_USERS_DB=str(tmp_path / "auth.sqlite"),
        UNIFIED_BACKEND_DATA_DIR=str(tmp_path / "backend"),
        MODEL_PATHS_CONFIG="config/model_paths.yaml",
    )
    return env


@pytest.mark.parametrize("entry", [
    "AiVision.inference.model_registry", "AiVision.inference.runtime_manager",
    "AiVision.inference.workers.face_recognizer", "AiVision.features",
    "AiVision.platform.orchestrator", "AiVision.features.recognize_face.library.embedding",
])
def test_fresh_import_orders_register_canonical_workers_and_features(entry, tmp_path):
    program = textwrap.dedent("""
        import importlib
        import importlib.util
        from pathlib import Path
        import pickle
        import sys
        import sqlalchemy

        def forbid_database(*args, **kwargs):
            raise AssertionError("imports must not connect to a database")

        sqlalchemy.create_engine = forbid_database
        importlib.import_module(sys.argv[1])
        import AiVision.inference as inference
        from AiVision.inference import model_paths
        from AiVision.inference.base_worker import BaseModelWorker
        from AiVision.inference.model_registry import MODEL_SPECS
        from AiVision.inference.workers.yolo_detector import YoloDetectorWorker
        from AiVision.inference.workers.face_detector import FaceDetectorWorker
        from AiVision.inference.workers.face_recognizer import FaceRecognizerWorker
        from AiVision.features import all_specs

        root = Path(sys.argv[2]) / "AiVision"
        assert Path(inference.__file__).parent == root / "inference"
        assert model_paths._PROJECT_ROOT == root
        assert model_paths._resolve_config_path("config/model_paths.yaml") == root / "config/model_paths.yaml"
        assert {name: spec.worker_class for name, spec in MODEL_SPECS.items()} == {
            "yolo_human": YoloDetectorWorker, "yolo_phone": YoloDetectorWorker,
            "insightface_detection": FaceDetectorWorker, "insightface": FaceRecognizerWorker,
        }
        for cls in {spec.worker_class for spec in MODEL_SPECS.values()}:
            assert issubclass(cls, BaseModelWorker)
            assert cls.__module__.startswith("AiVision.inference.workers.")
            assert pickle.loads(pickle.dumps(cls)) is cls
        assert set(all_specs()) == {
            "blocks", "detect_door", "detect_face", "detect_human",
            "detect_logistics_single_person", "detect_phone", "recognize_face",
        }
        old_package = "AiVision.platform.inference"
        assert importlib.util.find_spec(old_package) is None
        assert not any(name == old_package or name.startswith(old_package + ".") for name in sys.modules)
        print("registered")
    """)
    result = subprocess.run([sys.executable, "-c", program, entry, str(REPO_ROOT)],
                            cwd=tmp_path, env=isolated_environment(tmp_path),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "registered"
    assert "加载 features." not in result.stderr
    assert not (tmp_path / "auth.sqlite").exists()


@pytest.mark.parametrize("path_kind", ["relative", "absolute"])
def test_model_config_read_and_save_keep_original_base_from_another_cwd(path_kind, tmp_path):
    config = tmp_path / "models.yaml"
    first, second = tmp_path / "first.pt", tmp_path / "second.pt"
    for weight in (first, second):
        weight.write_bytes(b"test-only placeholder; never loaded by a model")
    config.write_text(f"# preserve\nmodels:\n  yolo_human:\n    path: {first}\n")
    env = isolated_environment(tmp_path)
    env["MODEL_PATHS_CONFIG"] = (
        os.path.relpath(config, REPO_ROOT / "AiVision") if path_kind == "relative" else str(config)
    )
    program = textwrap.dedent("""
        from pathlib import Path
        import sys
        from AiVision.inference import model_paths

        config, first, second = map(Path, sys.argv[1:])
        assert model_paths._resolve_config_path(model_paths.settings.model_paths.config_path) == config
        assert model_paths.load_model_paths() == {"yolo_human": str(first)}
        assert model_paths.save_model_path("yolo_human", str(second)) == str(second)
        assert model_paths.load_model_paths() == {"yolo_human": str(second)}
    """)
    result = subprocess.run([sys.executable, "-c", program, str(config), str(first), str(second)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert config.read_text() == f'# preserve\nmodels:\n  yolo_human:\n    path: "{second}"\n'
    assert config.with_suffix(".yaml.lock").is_file()
    assert not list(tmp_path.glob(".models.yaml.*.tmp"))


def test_spawn_uses_real_worker_entry_for_shared_model_queues_and_shutdown(tmp_path):
    """仅替换外部 ultralytics；真实 Worker 的加载、进程入口、队列和结果转换均执行。"""
    (tmp_path / "ultralytics.py").write_text(textwrap.dedent("""
        from pathlib import Path
        from types import SimpleNamespace
        import numpy as np

        class Tensor:
            def __init__(self, values):
                self.values = np.asarray(values)
            def cpu(self):
                return self
            def numpy(self):
                return self.values

        class YOLO:
            def __init__(self, path):
                assert Path(path).read_bytes() == b"isolated-test-model"
            def predict(self, frame, *, conf, iou, verbose):
                assert frame.shape == (8, 8, 3)
                if frame[0, 0, 0] == 2:
                    raise RuntimeError("synthetic inference failure")
                assert (conf, iou) == ((0.3, 0.5) if frame[0, 0, 0] == 0 else (0.7, 0.2))
                assert verbose is False
                boxes = Boxes(
                    xyxy=Tensor([[0, 0, 4, 4], [1, 1, 5, 5]]),
                    conf=Tensor([0.75, 0.5]), cls=Tensor([0, 1]),
                )
                return [SimpleNamespace(boxes=boxes)]

        class Boxes(SimpleNamespace):
            def __len__(self):
                return 2
    """))
    weight = tmp_path / "shared.pt"
    weight.write_bytes(b"isolated-test-model")
    script = tmp_path / "spawn_inference.py"
    script.write_text(textwrap.dedent("""
        import json
        import multiprocessing as mp
        import os
        import sys
        import numpy as np

        from AiVision.inference.base_worker import BaseModelWorker
        from AiVision.inference.model_registry import MODEL_SPECS

        def main():
            mp.set_start_method("spawn", force=True)
            inputs = {name: mp.Queue(maxsize=4) for name in ("yolo_human", "yolo_phone")}
            outputs = {name: mp.Queue(maxsize=4) for name in ("detect_human", "detect_phone")}
            worker = MODEL_SPECS["yolo_human"].worker_class(
                inputs, outputs, model_name="yolo_human", model_path=sys.argv[1],
            )
            try:
                worker.start()
                assert worker._proc.pid != os.getpid()
                assert mp.get_start_method() == "spawn"
                assert worker._ready_event.wait(10), worker.failure_message()
                assert worker.is_running()
                # 同一 Worker 服务两个逻辑模型；异常之后还须处理下一次合法请求。
                for index, model, pixel in ((0, "yolo_human", 0), (1, "yolo_phone", 1),
                                            (2, "yolo_human", 2), (3, "yolo_human", 0)):
                    feature = "detect_human" if model == "yolo_human" else "detect_phone"
                    task = {"camera_id": index + 10, "roi_id": index, "function_name": feature,
                            "request_id": f"spawn:{index}", "frame": np.full((8, 8, 3), pixel, np.uint8)}
                    if model == "yolo_phone":
                        task.update(conf=0.7, iou=0.2)
                    inputs[model].put(task, timeout=2)
                    result = outputs[feature].get(timeout=10)
                    assert set(result) == {"camera_id", "roi_id", "function_name", "request_id", "model_name",
                                           "status", "error_code", "error_message", "inference_ms", "detections"}
                    for key in ("camera_id", "roi_id", "function_name", "request_id"):
                        assert result[key] == task[key]
                    assert result["model_name"] == model
                    assert result["inference_ms"] >= 0
                    if pixel == 2:
                        assert result["status"] == "error" and result["detections"] == []
                        assert result["error_code"] == "model_inference_error"
                        assert result["error_message"] == "synthetic inference failure"
                    else:
                        assert result["status"] == "ok"
                        assert result["error_code"] is None and result["error_message"] is None
                        expected = ({"bbox": [0., 0., 4., 4.], "confidence": 0.75, "class_id": 0, "type": "person"}
                                    if model == "yolo_human" else
                                    {"bbox": [1., 1., 5., 5.], "confidence": 0.5, "class_id": 1, "type": "phone"})
                        assert result["detections"] == [expected]
                    assert worker.is_running()
            finally:
                try:
                    worker.stop()
                finally:
                    for channel in (*inputs.values(), *outputs.values()):
                        channel.close()
                        channel.join_thread()
            assert worker._proc.exitcode == 0
            assert not worker.is_alive() and not worker.is_ready()
            assert not mp.active_children()
            print(json.dumps({"entry": BaseModelWorker._run.__module__, "worker": type(worker).__module__,
                              "completed": 4, "stopped": True}))

        if __name__ == "__main__":
            main()
    """))
    result = subprocess.run([sys.executable, str(script), str(weight)], cwd=tmp_path,
                            env=isolated_environment(tmp_path), capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "entry": "AiVision.inference.base_worker", "worker": "AiVision.inference.workers.yolo_detector",
        "completed": 4, "stopped": True,
    }
    assert "leaked" not in result.stderr
