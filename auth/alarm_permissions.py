"""报警事件能力属于平台，数据访问范围由事业部决定。"""
from typing import Any, Iterable

from AiVision.departments.department_registry import DEPARTMENT_SPECS
from AiVision.alarms.types import VIOLATION_TYPE_META

# 事件类型沿用正式目录，避免新功能已入库却被普通账号的重复白名单过滤。
DETECTION_EVENT_TYPES = frozenset(meta["event_type"] for meta in VIOLATION_TYPE_META.values())


def allowed_alarm_event_types(user: dict[str, Any], departments: Iterable[str]) -> set[str] | None:
    role = str(user.get("role") or "").strip().lower()
    if role == "admin":
        return None
    if role not in {"viewer", "department_admin"}:
        return set()
    departments = set(departments)
    return set(DETECTION_EVENT_TYPES) if departments.intersection(DEPARTMENT_SPECS) else set()
