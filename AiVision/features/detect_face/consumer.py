"""features/detect_face/consumer.py — 人脸逗留检测"""
from features._base.dwell_consumer import DwellDetectionConsumer


class FaceConsumer(DwellDetectionConsumer):
    """人脸逗留 — 用 yolo_face 模型,所有 detection 都视为人脸"""
    REQUIRED_DETECTION_TYPE = None  # face 模型本身只检测人脸,不需要再过滤
