"""物流通道共享常量与功能白名单。"""
from __future__ import annotations

from datetime import time

# 哪些feature被认为是物流通道检测功能（frozenset（...）不可修改的set集合）
LOGISTICS_FEATURES = frozenset({
    "detect_logistics_single_person",                         # 通用电气
    "detect_logistics_single_person_electronics_electrician", # 电子电工
    "detect_logistics_single_person_electrical_components",   # 电器元件
    "detect_logistics_single_person_precious_metal_recycling", # 贵金属回收
})

MAX_CAMERAS_PER_CHANNEL = 9
DEFAULT_DETECTION_START = time(8, 0)
DEFAULT_DETECTION_END = time(20, 0)
DEFAULT_PERSON_CONFIDENCE_THRESHOLD = 0.3
DEFAULT_STATUS_STALE_SECONDS = 5.0

def require_logistics_feature(feature_name: str) -> str:
    """校验并规范化物流单人检测功能名称。"""
    normalized = feature_name.strip() if isinstance(feature_name, str) else ""
    if normalized not in LOGISTICS_FEATURES:
        raise ValueError(f"不支持的物流检测功能: {feature_name!r}")
    return normalized


def get_logistics_department(feature_name: str) -> str:
    """物流功能只归属一个部门，直接读取 FeatureSpec 声明。"""
    # 功能发现过程中会导入本模块，调用时再取已注册的 SPEC，避免循环导入。
    from AiVision.features import get_spec

    spec = get_spec(require_logistics_feature(feature_name))
    if spec is None or len(spec.departments) != 1:
        raise ValueError(f"物流功能必须声明唯一归属部门: {feature_name}")
    return spec.departments[0]
