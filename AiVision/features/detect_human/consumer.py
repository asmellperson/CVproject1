"""features/detect_human/consumer.py — 人体逗留检测"""
from features._base.dwell_consumer import DwellDetectionConsumer


class HumanConsumer(DwellDetectionConsumer):
    """人体逗留 — 用 yolo_human 模型(person_phone.pt 过滤 class 0)"""
    REQUIRED_DETECTION_TYPE = None
