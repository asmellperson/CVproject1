"""YOLO 入队图像大小、模型输入一致性和原始 ROI 坐标恢复的回归验证。"""

import numpy as np
import pytest

from AiVision.inference.input_frames import prepare_inference_task, restore_detection_coordinates


@pytest.fixture(autouse=True)
def deployment_environment(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("model_name", ["yolo_human", "yolo_phone", "yolo_guard_person_phone", "yolo_vehicle"])
def test_large_detection_inputs_send_one_ninth_of_original_bytes(model_name):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    task = {"model_name": model_name, "frame": frame, "request_id": "test", "conf": 0.35, "iou": 0.6}
    prepared = prepare_inference_task(task)
    assert prepared["frame"].shape == (360, 640, 3)
    assert prepared["frame"].nbytes == frame.nbytes // 9
    assert prepared["source_frame_shape"] == (1080, 1920)
    assert task["frame"] is frame
    assert "source_frame_shape" not in task
    assert (prepared["request_id"], prepared["conf"], prepared["iou"]) == ("test", 0.35, 0.6)


@pytest.mark.parametrize("size, expected", [(320, (180, 320)), (960, (540, 960)), (1920, (1080, 1920))])
def test_camera_specific_image_size_is_respected(size, expected):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    task = {"model_name": "yolo_human", "frame": frame, "imgsz": size}
    prepared = prepare_inference_task(task)
    assert prepared["frame"].shape[:2] == expected
    assert prepared["imgsz"] == size


@pytest.mark.parametrize("model_name", ["insightface", "insightface_detection", "guard_uniform", "yolo_guard_pose"])
def test_other_model_inputs_keep_their_original_resolution(model_name):
    task = {"model_name": model_name, "frame": np.zeros((1080, 1920, 3), dtype=np.uint8)}
    assert prepare_inference_task(task) is task


def test_small_image_is_not_upscaled_for_transmission():
    task = {"model_name": "yolo_human", "frame": np.zeros((120, 320, 3), dtype=np.uint8)}
    assert prepare_inference_task(task) is task


def test_detection_coordinates_return_to_original_roi_without_mutating_model_output():
    task = prepare_inference_task({
        "model_name": "yolo_human", "frame": np.zeros((1080, 1920, 3), dtype=np.uint8),
    })
    detections = [{"bbox": [64., 36., 320., 180.], "confidence": 0.9, "class_id": 0, "type": "person"}]
    restored = restore_detection_coordinates(detections, task)
    assert restored[0]["bbox"] == [192., 108., 960., 540.]
    assert restored[0]["confidence"] == 0.9
    assert restored[0]["type"] == "person"
    assert detections[0]["bbox"] == [64., 36., 320., 180.]
    assert restore_detection_coordinates([], task) == []


@pytest.mark.parametrize("shape", [(1080, 1920), (1081, 1921), (432, 768), (1536, 864), (257, 513)])
def test_transmitted_image_produces_identical_yolo_letterbox_pixels(shape):
    from ultralytics.data.augment import LetterBox

    frame = np.random.default_rng(42).integers(0, 256, (*shape, 3), dtype=np.uint8)
    task = prepare_inference_task({"model_name": "yolo_human", "frame": frame})
    letterbox = LetterBox(new_shape=(640, 640), auto=True, stride=32)
    # 提前缩小只改变传输位置；YOLO 实际收到的补边像素须与直接输入原图一致。
    assert np.array_equal(letterbox(image=frame), letterbox(image=task["frame"]))


def test_worker_restores_coordinates_before_publishing_result():
    from AiVision.inference.base_worker import BaseModelWorker

    class Worker(BaseModelWorker):
        def load_model(self):
            return None

        def infer(self, model, frame, task):
            assert frame.shape == (360, 640, 3)
            return [{"bbox": [64., 36., 320., 180.], "type": "person", "confidence": 0.9}]

    worker = Worker.__new__(Worker)
    worker.model_name = "yolo_human"
    task = prepare_inference_task({"model_name": "yolo_human", "frame": np.zeros((1080, 1920, 3), dtype=np.uint8)})
    result = worker._execute_task(None, task)
    assert result["status"] == "ok"
    assert result["detections"][0]["bbox"] == [192., 108., 960., 540.]
