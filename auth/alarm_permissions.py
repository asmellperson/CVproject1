"""报警事件能力属于平台，数据访问范围由事业部决定。"""
from typing import Any, Iterable

from AiVision.departments.department_registry import DEPARTMENT_SPECS

DETECTION_EVENT_TYPES = frozenset({
    "security_inspection", "visual_language_detection",
    "guard_absent", "guard_phone_use", "guard_prone_sleep", "guard_vehicle_inspection_missing",
    "blocks", "detect_door", "detect_face", "recognize_face", "detect_human",
    "detect_logistics_single_person", "detect_phone", "agv_person_check",
})


def allowed_alarm_event_types(user: dict[str, Any], departments: Iterable[str]) -> set[str] | None:
    role = str(user.get("role") or "").strip().lower()
    if role == "admin":
        return None
    if role != "viewer":
        return set()
    departments = set(departments)
    return set(DETECTION_EVENT_TYPES) if departments.intersection(DEPARTMENT_SPECS) else set()
