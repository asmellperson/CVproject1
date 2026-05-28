"""platform/department/
部门管理模块。
"""
from platform.department.orm import AiDepartment, AiFeatureDepartment
from platform.department.service import department_service

__all__ = [
    "AiDepartment",
    "AiFeatureDepartment",
    "department_service",
]
