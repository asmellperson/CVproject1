"""统一报警处置沿用的事业部报警类型权限；归属权限由报警源另行校验。"""
from typing import Any, Iterable


DEPARTMENT_EVENT_TYPES: dict[str, set[str]] = {
    "general_electric": {
        "security_vlm_non_compliant",
        "security_vlm_error",
        "guard_absent",
        "guard_phone_use",
        "guard_prone_sleep",
        "detect_human",
        "detect_logistics_single_person",
    },
    "research_institute": {
        "blocks",
        "detect_face",
        "detect_phone",
    },
    "electronics_electrician": {
        "security_vlm_non_compliant",
        "security_vlm_error",
        "guard_absent",
        "guard_phone_use",
        "guard_prone_sleep",
        "detect_logistics_single_person",
    },
    "electrical_components": {
        "security_vlm_non_compliant",
        "security_vlm_error",
        "detect_logistics_single_person",
    },
    "precious_metal_recycling": {
        "security_vlm_non_compliant",
        "security_vlm_error",
        "detect_logistics_single_person",
    },
    "haoda_company": {
        "detect_human",
    },
}

def allowed_alarm_event_types(user: dict[str, Any], departments: Iterable[str]) -> set[str] | None:
    role = str(user.get("role") or "").strip().lower()
    if role == "admin":
        return None
    if role != "viewer":
        return set()
    departments = set(departments)
    if "all" in departments:
        return None
    return {event_type for department in departments
            for event_type in DEPARTMENT_EVENT_TYPES.get(department, set())}
