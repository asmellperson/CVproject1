"""只加载本地 buffalo_l ONNX 文件；注册照片与实时摄像头共用推理实现。"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from AiVision.core.logger import logger
from AiVision.platform.face_library.constants import (
    DEFAULT_SIMILARITY_THRESHOLD, DETECTION_MODEL_FILE, RECOGNITION_MODEL_FILE,
)
from AiVision.platform.face_library.index import FaceIndex
from AiVision.platform.inference.base_worker import BaseModelWorker


class InsightFaceRecognizer:
    def __init__(self, model_path: str):
        from AiVision.core.settings import settings
        from AiVision.platform.inference.model_paths import validate_model_path

        directory = Path(validate_model_path(model_path, model_type="insightface"))
        config = settings.face_recognition
        if config.provider == "CUDAExecutionProvider":
            # 复用项目 PyTorch 环境中的 CUDA/cuDNN 动态库。
            import torch  # noqa: F401
        import onnxruntime
        from insightface.model_zoo import get_model

        if config.provider not in onnxruntime.get_available_providers():
            raise RuntimeError(f"未安装可用的 {config.provider}，请检查 ONNX Runtime 和运行环境")
        options = [{"device_id": str(config.device_id)}] if config.provider == "CUDAExecutionProvider" else [{}]
        # 传入完整文件名并显式禁止下载，不调用会自动下载模型包的 FaceAnalysis 构造器。
        self.detector = get_model(
            str(directory / DETECTION_MODEL_FILE), download=False,
            providers=[config.provider], provider_options=options,
        )
        self.recognizer = get_model(
            str(directory / RECOGNITION_MODEL_FILE), download=False,
            providers=[config.provider], provider_options=options,
        )
        for model, task in ((self.detector, "detection"), (self.recognizer, "recognition")):
            if model is None or model.taskname != task:
                raise RuntimeError(f"buffalo_l 的 {task} 模型无效")
            if config.provider not in model.session.get_providers():
                raise RuntimeError(f"{config.provider} 初始化失败，请检查 GPU、CUDA 和 cuDNN")
        context = config.device_id if config.provider == "CUDAExecutionProvider" else -1
        self.detector.prepare(
            ctx_id=context, input_size=(config.detection_size, config.detection_size),
            det_thresh=config.detection_threshold,
        )
        self.recognizer.prepare(ctx_id=context)

    def get_faces(self, frame: np.ndarray) -> list:
        from insightface.app.common import Face

        if frame is None or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
            raise ValueError("人脸推理需要有效的 BGR 图像")
        boxes, landmarks = self.detector.detect(frame, max_num=0, metric="default")
        if len(boxes) and landmarks is None:
            raise ValueError("人脸检测未返回对齐所需的关键点")
        faces = []
        for index, box in enumerate(boxes):
            face = Face(bbox=box[:4], kps=landmarks[index], det_score=float(box[4]))
            self.recognizer.get(frame, face)
            faces.append(face)
        return faces


class FaceRecognizerWorker(BaseModelWorker):
    def load_model(self) -> InsightFaceRecognizer:
        model = InsightFaceRecognizer(self.model_path)
        self.index = FaceIndex()
        count = self.index.refresh()
        self._index_refreshed_at = time.monotonic()
        self._index_available = True
        logger.info(f"[FaceRecognizer] 模型已加载，索引有效人员数 {count}")
        return model

    def infer(self, model: InsightFaceRecognizer, frame, task_meta: dict) -> list[dict]:
        from AiVision.core.settings import settings

        now = time.monotonic()
        if now - self._index_refreshed_at >= settings.face_recognition.index_refresh_seconds:
            self._index_refreshed_at = now
            self._index_available = False
            count = self.index.refresh()
            self._index_available = True
            logger.info(f"[FaceRecognizer] 已刷新索引，有效人员数 {count}")
        if not self._index_available:
            raise RuntimeError("人员特征索引刷新失败，等待下一次刷新")
        threshold = float(task_meta.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD))
        detections = []
        # 摄像头允许任意多张脸，各自提取特征并比对，不应用注册照片的单脸限制。
        for face in model.get_faces(frame):
            result = self.index.match(face.normed_embedding, threshold)
            detections.append({
                "bbox": [float(value) for value in face.bbox],
                "confidence": float(face.det_score), "class_id": 0, "type": "face_identity", **result,
            })
        return detections
