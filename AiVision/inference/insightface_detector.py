"""本地 InsightFace ONNX 加载与纯人脸检测公共实现。

显式使用可用的 CUDA Execution Provider 并关闭自动回退，避免 GPU 初始化失败被隐藏。
检测 Session 在调用间复用，每次覆盖分数与 NMS 阈值；不读取人员身份或授权数据。
"""
from __future__ import annotations

import math

import numpy as np

DETECTION_MODEL_FILE = "det_10g.onnx"
DETECTION_SIZE = 640
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
        """验证检测 ONNX 文件并创建固定输入尺寸的 Session，图像缩放和坐标还原交给 InsightFace。"""
        from .model_paths import validate_model_path

        path = validate_model_path(model_path, model_type="insightface_detection")
        self.model = load_insightface_model(path, task="detection")
        # 固定单一尺寸；缩放、补边和坐标还原由 InsightFace 完成。
        self.model.prepare(ctx_id=0, input_size=(DETECTION_SIZE, DETECTION_SIZE))

    def detect(self, frame: np.ndarray, *, confidence: float, nms_threshold: float):
        """验证 BGR 三通道图像和有限的 0～1 阈值，逐任务设置分数/NMS 后返回检测框及关键点。

        此方法修改共享 Session 参数，应由同一 Worker 串行调用；参数非法时抛出 ValueError。
        """
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
            raise ValueError("人脸推理需要有效的 BGR 图像")
        for name, value in (("conf", confidence), ("iou", nms_threshold)):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} 必须是 0～1 的有限数值")
        # InsightFace 1.0.1 SCRFD.detect/forward/nms 实际读取这两个属性。
        # 每个任务同时赋值，合法零值不替换，摄像头之间不继承参数。
        self.model.det_thresh = confidence
        self.model.nms_thresh = nms_threshold
        return self.model.detect(frame, max_num=0, metric="default")
