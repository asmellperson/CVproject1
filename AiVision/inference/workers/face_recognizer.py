"""本地人脸特征提取与实时人员匹配 Worker。

InsightFaceRecognizer 由注册照片生成任务和实时 Worker 共用，加载 buffalo_l 检测与识别文件。
Worker 周期刷新 FaceIndex，逐脸匹配；人员是否被授权仍由 Consumer 读取本地授权集合判断。
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from AiVision.core.logger import logger
from AiVision.features.face_recognition.library.constants import (
    DEFAULT_DETECTION_THRESHOLD, DEFAULT_SIMILARITY_THRESHOLD, DEFAULT_NMS_THRESHOLD,
    INDEX_REFRESH_SECONDS, RECOGNITION_MODEL_FILE,
)
from AiVision.features.face_recognition.library.index import FaceIndex
from AiVision.inference.base_worker import BaseModelWorker
from AiVision.inference.insightface_detector import (
    DETECTION_MODEL_FILE, InsightFaceDetector, load_insightface_model,
)


class InsightFaceRecognizer:
    """持有检测与识别 Session，负责对齐和特征提取，不直接管理人员数据库。"""
    def __init__(self, model_path: str):
        """验证模型目录中的必要文件，分别加载检测和识别 Session 并完成设备准备。"""
        from AiVision.inference.model_paths import validate_model_path

        directory = Path(validate_model_path(model_path, model_type="insightface"))
        self.detector = InsightFaceDetector(str(directory / DETECTION_MODEL_FILE))
        self.recognizer = load_insightface_model(
            str(directory / RECOGNITION_MODEL_FILE), task="recognition",
        )
        self.recognizer.prepare(ctx_id=0)

    def get_faces(self, frame: np.ndarray, *, detection_threshold: float = DEFAULT_DETECTION_THRESHOLD) -> list:
        """为 BGR 图像中的每张人脸提取特征并返回 Face 列表；无脸返回空列表，缺少对齐关键点报错。"""
        from insightface.app.common import Face

        boxes, landmarks = self.detector.detect(
            frame, confidence=detection_threshold, nms_threshold=DEFAULT_NMS_THRESHOLD,
        )
        if len(boxes) and landmarks is None:
            raise ValueError("人脸检测未返回对齐所需的关键点")
        faces = []
        for index, box in enumerate(boxes):
            face = Face(bbox=box[:4], kps=landmarks[index], det_score=float(box[4]))
            self.recognizer.get(frame, face)
            faces.append(face)
        return faces


class FaceRecognizerWorker(BaseModelWorker):
    """把人脸特征与定期刷新的人脸底库匹配，返回身份及相似度的 Worker。"""
    def load_model(self) -> InsightFaceRecognizer:
        """加载模型并首次刷新人员索引，记录刷新时刻；失败会阻止 Worker 就绪。"""
        model = InsightFaceRecognizer(self.model_path)
        self.index = FaceIndex()
        count = self.index.refresh()
        self._index_refreshed_at = time.monotonic()
        self._index_available = True
        logger.info(f"[FaceRecognizer] 模型已加载，索引有效人员数 {count}")
        return model

    def infer(self, model: InsightFaceRecognizer, frame, task_meta: dict) -> list[dict]:
        """按任务阈值逐脸匹配，索引刷新失败时拒绝使用旧索引完成本次推理。

        返回 ROI 坐标中的人脸框、分数和匹配字段；摄像头允许多脸，不应用注册照片的单脸限制。
        """
        now = time.monotonic()
        if now - self._index_refreshed_at >= INDEX_REFRESH_SECONDS:
            self._index_refreshed_at = now
            self._index_available = False
            count = self.index.refresh()
            self._index_available = True
            logger.info(f"[FaceRecognizer] 已刷新索引，有效人员数 {count}")
        if not self._index_available:
            raise RuntimeError("人员特征索引刷新失败，等待下一次刷新")
        threshold = float(task_meta.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD))
        detection_threshold = float(task_meta.get("conf", DEFAULT_DETECTION_THRESHOLD))
        detections = []
        # 摄像头允许任意多张脸，各自提取特征并比对，不应用注册照片的单脸限制。
        for face in model.get_faces(frame, detection_threshold=detection_threshold):
            result = self.index.match(face.normed_embedding, threshold)
            detections.append({
                "bbox": [float(value) for value in face.bbox],
                "confidence": float(face.det_score), "class_id": 0, "type": "face_identity", **result,
            })
        return detections
