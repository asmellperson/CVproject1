"""供人脸逗留功能使用的纯检测 Worker。

输入是 Consumer 准备的 BGR ROI，输出坐标仍相对该输入图；主进程负责还原到全帧。
本实现只提取人脸框和分数，不加载身份特征索引或判断人员授权。
"""
from __future__ import annotations

from AiVision.inference.base_worker import BaseModelWorker
from AiVision.inference.insightface_detector import InsightFaceDetector


class FaceDetectorWorker(BaseModelWorker):
    """复用 InsightFaceDetector 的单帧人脸检测 Worker。"""
    def load_model(self) -> InsightFaceDetector:
        """在 Worker 子进程中验证并加载纯检测 Session。"""
        return InsightFaceDetector(self.model_path)

    def infer(self, model: InsightFaceDetector, frame, task_meta: dict) -> list[dict]:
        """使用任务 conf/iou 检测 ROI，把框转换为 type=face 的标准列表；关键点不向业务返回。"""
        boxes, _landmarks = model.detect(
            frame, confidence=task_meta["conf"], nms_threshold=task_meta["iou"],
        )
        return [
            {"bbox": [float(value) for value in box[:4]], "confidence": float(box[4]),
             "class_id": 0, "type": "face"}
            for box in boxes
        ]
