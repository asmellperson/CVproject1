"""本地 InsightFace ONNX 加载与纯人脸检测公共实现。

显式使用可用的 CUDA Execution Provider 并关闭自动回退，避免 GPU 初始化失败被隐藏。
检测 Session 在调用间复用，检测与身份识别使用同一套图像预处理。
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from AiVision.features._shared.defaults import FACE_DETECTION_IOU_THR, FACE_SCORE_THR

DETECTION_MODEL_FILE = "det_10g.onnx"
DETECTION_SIZE = 960
EXECUTION_PROVIDER = "CUDAExecutionProvider"


def load_insightface_model(model_path: str, *, task: str):
    # 复用 AiVision 的 PyTorch CUDA/cuDNN 动态库与 CUDA_VISIBLE_DEVICES。
    """加载指定任务的本地 ONNX 模型，并要求 CUDA Session 真正可用。

    Args:
        model_path: 已准备好的本地模型文件路径，不自动下载。
        task: 期望的 InsightFace 任务类型，如 detection 或 recognition。

    Returns:
        模型对象: 已验证任务类型和 CUDA Provider，尚由调用方执行 prepare()。

    Raises:
        RuntimeError: CUDA Provider 不可用、模型类型不符或 GPU Session 初始化失败。
    """
    import torch  # noqa: F401
    import onnxruntime
    from insightface.model_zoo import get_model

    if EXECUTION_PROVIDER not in onnxruntime.get_available_providers():
        raise RuntimeError(f"未安装可用的 {EXECUTION_PROVIDER}，请检查 ONNX Runtime 和运行环境")
    # 设备 0 是进程可见的逻辑设备，不修改部署环境的物理 GPU 分配。
    model = get_model(
        model_path, download=False, providers=[EXECUTION_PROVIDER],
        provider_options=[{"device_id": "0"}],
    )
    if model is None or model.taskname != task:
        raise RuntimeError(f"InsightFace {task} 模型无效: {model_path}")
    if EXECUTION_PROVIDER not in model.session.get_providers():
        raise RuntimeError(f"{EXECUTION_PROVIDER} 初始化失败，请检查 GPU、CUDA 和 cuDNN")
    model.session.disable_fallback()
    return model


class InsightFaceDetector:
    """复用一个检测 Session，串行处理不同摄像头的 BGR ROI。"""

    def __init__(self, model_path: str):
        """验证检测 ONNX 文件并创建可复用的 Session。"""
        from .model_paths import validate_model_path

        path = validate_model_path(model_path, model_type="insightface_detection")
        self.model = load_insightface_model(path, task="detection")
        shape = self.model.session.get_inputs()[0].shape
        expected = (1, 3, DETECTION_SIZE, DETECTION_SIZE)
        if len(shape) != len(expected) or any(
            isinstance(actual, int) and actual != size for actual, size in zip(shape, expected)
        ):
            raise ValueError(f"人脸检测 ONNX 必须支持 1×3×{DETECTION_SIZE}×{DETECTION_SIZE} 输入")

    def detect(
        self, frame: np.ndarray, *, confidence: float = FACE_SCORE_THR,
        nms_threshold: float = FACE_DETECTION_IOU_THR,
    ):
        """返回 ROI 坐标系中的人脸框、置信度和五点关键点。

        此方法修改共享 Session 参数，应由同一 Worker 串行调用；参数非法时抛出 ValueError。
        """
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
            raise ValueError("人脸推理需要有效的 BGR 图像")
        for name, value in (("conf", confidence), ("iou", nms_threshold)):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} 必须是 0～1 的有限数值")
        height, width = frame.shape[:2]
        longest_side = max(height, width)
        resized_width = max(1, width * DETECTION_SIZE // longest_side)
        resized_height = max(1, height * DETECTION_SIZE // longest_side)
        # forward 统一转 RGB 并归一化。float32 补边保留 127.5 的小数，使归一化结果为零。
        canvas = np.full((DETECTION_SIZE, DETECTION_SIZE, 3), 127.5, dtype=np.float32)
        canvas[:resized_height, :resized_width] = cv2.resize(frame, (resized_width, resized_height))
        scores_by_stride, boxes_by_stride, landmarks_by_stride = self.model.forward(canvas, confidence)

        scores = np.vstack(scores_by_stride)
        order = scores.ravel().argsort()[::-1]
        # 整数缩放尺寸可能使横纵比例略有不同，按各自的实际比例恢复。
        scale = np.array([resized_width / width, resized_height / height], dtype=np.float32)
        boxes = np.vstack(boxes_by_stride) / np.tile(scale, 2)
        detections = np.hstack((boxes, scores)).astype(np.float32, copy=False)[order]
        # 每次设置阈值，摄像头之间不继承参数。
        self.model.nms_thresh = nms_threshold
        keep = self.model.nms(detections)
        landmarks = np.vstack(landmarks_by_stride)[order][keep] / scale if landmarks_by_stride else None
        return detections[keep], landmarks
