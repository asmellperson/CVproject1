"""features/face_dwell/consumer.py — 人脸逗留检测"""
from AiVision.features._shared.dwell_consumer import DwellDetectionConsumer

class FaceConsumer(DwellDetectionConsumer):
    """使用 InsightFace 纯检测结果，跟踪和告警由公共逗留流程处理。"""
    REQUIRED_DETECTION_TYPE = "face"

    def _detection_options(self, cfg: dict) -> tuple:
        """使用人脸置信度筛选目标，其余框形状与跟踪参数沿用公共逗留实现。"""
        return cfg["FACE_SCORE_THR"], 0, (None, None), {}
