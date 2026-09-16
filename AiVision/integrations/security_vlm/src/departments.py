"""安检工作区复用平台正式事业部目录。"""
from AiVision.departments.department_registry import DEPARTMENT_SPECS, require_department

DEPARTMENTS = tuple(DEPARTMENT_SPECS)

__all__ = ["DEPARTMENTS", "require_department"]
