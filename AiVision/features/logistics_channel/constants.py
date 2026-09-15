"""物流通道共享常量与功能白名单。"""
from __future__ import annotations

from datetime import time

# 哪些feature被认为是物流通道检测功能（frozenset（...）不可修改的set集合）
LOGISTICS_FEATURE_NAME = "detect_logistics_single_person"
LOGISTICS_FEATURES = frozenset({LOGISTICS_FEATURE_NAME})

MAX_CAMERAS_PER_CHANNEL = 9
DEFAULT_DETECTION_START = time(8, 0)
DEFAULT_DETECTION_END = time(20, 0)
DEFAULT_PERSON_CONFIDENCE_THRESHOLD = 0.3
DEFAULT_EMPTY_GRACE_SECONDS = 2.0
DEFAULT_MULTI_GRACE_SECONDS = 1.0
DEFAULT_MODEL_IOU = 0.3
DEFAULT_MIN_BOX_AREA = 0
DEFAULT_ASPECT_RATIO_RANGE = (0.0, 10.0)
DEFAULT_CAP_INTERVAL = 0.2
PERSON_DEDUP_IOU_THRESHOLD = 0.5

def require_logistics_feature(feature_name: str) -> str:
    """校验并规范化物流单人检测功能名称。"""
    normalized = feature_name.strip() if isinstance(feature_name, str) else ""
    if normalized not in LOGISTICS_FEATURES:
        raise ValueError(f"不支持的物流检测功能: {feature_name!r}")
    return normalized
