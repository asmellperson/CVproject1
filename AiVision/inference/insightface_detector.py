"""本地 InsightFace 检测与模型加载；不依赖人员库或身份识别业务。"""
from __future__ import annotations

import math

import numpy as np

DETECTION_MODEL_FILE = "det_10g.onnx"
DETECTION_SIZE = 640
EXECUTION_PROVIDER = "CUDAExecutionProvider"


def load_insightface_model(model_path: str, *, task: str):
    # 复用 AiVision 的 PyTorch CUDA/cuDNN 动态库与 CUDA_VISIBLE_DEVICES。
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
        from .model_paths import validate_model_path

        path = validate_model_path(model_path, model_type="insightface_detection")
        self.model = load_insightface_model(path, task="detection")
        # 固定单一尺寸；缩放、补边和坐标还原由 InsightFace 完成。
        self.model.prepare(ctx_id=0, input_size=(DETECTION_SIZE, DETECTION_SIZE))

    def detect(self, frame: np.ndarray, *, confidence: float, nms_threshold: float):
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
