"""features/detect_face/consumer.py — 人脸逗留检测"""
from AiVision.features._base.dwell_consumer import DwellDetectionConsumer

class FaceConsumer(DwellDetectionConsumer):
    """使用 InsightFace 纯检测结果，跟踪和告警由公共逗留流程处理。"""
    REQUIRED_DETECTION_TYPE = "face"

    def _detection_options(self, cfg: dict) -> tuple:
        return cfg["FACE_SCORE_THR"], 0, (None, None), {}
