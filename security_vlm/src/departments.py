"""安检事业部白名单及统一校验。"""

from __future__ import annotations


SECURITY_DEPARTMENTS = (
    "general_electric",
    "electronics_electrician",
    "electrical_components",
    "precious_metal_recycling",
)


def require_department(value: str) -> str:
    """返回合法事业部标识；空值或未知标识会被拒绝。"""
    department = str(value or "").strip()
    if department not in SECURITY_DEPARTMENTS:
        raise ValueError(f"未知安检事业部: {department or '<empty>'}")
    return department
