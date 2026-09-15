"""人脸纯检测 Worker：只返回 ROI 内的检测框，不访问人员库。"""
from __future__ import annotations

from AiVision.inference.base_worker import BaseModelWorker
from AiVision.inference.insightface_detector import InsightFaceDetector


class FaceDetectorWorker(BaseModelWorker):
    def load_model(self) -> InsightFaceDetector:
        return InsightFaceDetector(self.model_path)

    def infer(self, model: InsightFaceDetector, frame, task_meta: dict) -> list[dict]:
        boxes, _landmarks = model.detect(
            frame, confidence=task_meta["conf"], nms_threshold=task_meta["iou"],
        )
        return [
            {"bbox": [float(value) for value in box[:4]], "confidence": float(box[4]),
             "class_id": 0, "type": "face"}
            for box in boxes
        ]
