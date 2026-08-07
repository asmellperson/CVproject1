"""物流通道共享常量与功能白名单。"""
from __future__ import annotations

from datetime import time


LOGISTICS_FEATURES = frozenset({
    "detect_logistics_single_person",
    "detect_logistics_single_person_electronics_electrician",
    "detect_logistics_single_person_electrical_components",
    "detect_logistics_single_person_precious_metal_recycling",
})

LOGISTICS_FEATURE_DEPARTMENTS = {
    "detect_logistics_single_person": "general_electric",
    "detect_logistics_single_person_electronics_electrician": "electronics_electrician",
    "detect_logistics_single_person_electrical_components": "electrical_components",
    "detect_logistics_single_person_precious_metal_recycling": "precious_metal_recycling",
}

MAX_CAMERAS_PER_CHANNEL = 9
DEFAULT_DETECTION_START = time(8, 0)
DEFAULT_DETECTION_END = time(20, 0)
DEFAULT_STATUS_STALE_SECONDS = 5.0


def require_logistics_feature(feature_name: str) -> str:
    """校验并规范化物流单人检测功能名称。"""
    normalized = feature_name.strip() if isinstance(feature_name, str) else ""
    if normalized not in LOGISTICS_FEATURES:
        raise ValueError(f"不支持的物流检测功能: {feature_name!r}")
    return normalized
