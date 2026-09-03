"""告警类型的规范定义与历史编号兼容。"""
from __future__ import annotations

from typing import TypedDict


class AlarmTypeMeta(TypedDict):
    event_type: str
    label: str


class LegacyAlarmContext(TypedDict):
    violation_type: int
    feature_name: str
    department: str


VIOLATION_TYPE_META: dict[int, AlarmTypeMeta] = {
    1: {"event_type": "blocks", "label": "区域入侵"},
    2: {"event_type": "detect_door", "label": "大门开关"},
    3: {"event_type": "detect_phone", "label": "手机检测"},
    4: {"event_type": "detect_face", "label": "人脸检测"},
    5: {"event_type": "detect_human", "label": "人员违规逗留检测"},
    6: {"event_type": "detect_logistics_single_person", "label": "物流通道单人检测"},
}

DEFAULT_ALARM_TYPE_META: AlarmTypeMeta = {
    "event_type": "unknown",
    "label": "未知报警",
}

# 7/8/9 与 10 曾把部门或公司编码进告警类型。保留这里仅用于读取历史记录；
# 新写入统一使用 6（物流通道单人）或 5（人员违规逗留）。
LEGACY_ALARM_CONTEXT: dict[int, LegacyAlarmContext] = {
    7: {
        "violation_type": 6,
        "feature_name": "detect_logistics_single_person_electronics_electrician",
        "department": "electronics_electrician",
    },
    8: {
        "violation_type": 6,
        "feature_name": "detect_logistics_single_person_electrical_components",
        "department": "electrical_components",
    },
    9: {
        "violation_type": 6,
        "feature_name": "detect_logistics_single_person_precious_metal_recycling",
        "department": "precious_metal_recycling",
    },
    10: {
        "violation_type": 5,
        "feature_name": "detect_human_haoda",
        "department": "haoda_company",
    },
}

CANONICAL_FEATURE_BY_TYPE = {
    1: "blocks",
    2: "detect_door",
    3: "detect_phone",
    4: "detect_face",
    5: "detect_human",
    6: "detect_logistics_single_person",
}

DEFAULT_DEPARTMENT_BY_TYPE = {
    1: "research_institute",
    2: "general_electric",
    3: "research_institute",
    4: "research_institute",
    5: "general_electric",
    6: "general_electric",
}

FEATURE_DEPARTMENTS = {
    "blocks": "research_institute",
    "detect_door": "general_electric",
    "detect_phone": "research_institute",
    "detect_face": "research_institute",
    "detect_human": "general_electric",
    "detect_human_haoda": "haoda_company",
    "detect_logistics_single_person": "general_electric",
    "detect_logistics_single_person_electronics_electrician": "electronics_electrician",
    "detect_logistics_single_person_electrical_components": "electrical_components",
    "detect_logistics_single_person_precious_metal_recycling": "precious_metal_recycling",
}


def normalize_violation_type(value: int | None) -> int:
    """把历史部门型编号转换为只表达告警性质的规范编号。"""
    raw_type = int(value or 0)
    legacy = LEGACY_ALARM_CONTEXT.get(raw_type)
    return legacy["violation_type"] if legacy else raw_type


def feature_name_for_violation_type(value: int | None) -> str:
    """为缺少独立 feature_name 的历史记录恢复原检测功能。"""
    raw_type = int(value or 0)
    legacy = LEGACY_ALARM_CONTEXT.get(raw_type)
    if legacy:
        return legacy["feature_name"]
    return CANONICAL_FEATURE_BY_TYPE.get(raw_type, "")


def department_for_violation_type(value: int | None) -> str:
    """为缺少独立 department 的历史记录恢复原归属。"""
    raw_type = int(value or 0)
    legacy = LEGACY_ALARM_CONTEXT.get(raw_type)
    if legacy:
        return legacy["department"]
    return DEFAULT_DEPARTMENT_BY_TYPE.get(raw_type, "")


def department_for_feature(feature_name: str | None) -> str:
    """根据独立功能名补齐归属，不把归属重新编码进 violation_type。"""
    return FEATURE_DEPARTMENTS.get(str(feature_name or ""), "")


def violation_types_for_feature(feature_name: str) -> tuple[int, ...]:
    """返回查询某功能历史记录时需要兼容的所有编号。"""
    legacy_types = tuple(
        legacy_type
        for legacy_type, context in LEGACY_ALARM_CONTEXT.items()
        if context["feature_name"] == feature_name
    )
    canonical_types = tuple(
        violation_type
        for violation_type, canonical_feature in CANONICAL_FEATURE_BY_TYPE.items()
        if canonical_feature == feature_name
    )
    return canonical_types + legacy_types
