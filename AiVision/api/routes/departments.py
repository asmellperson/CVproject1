"""api/routes/departments.py
部门管理 API。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from auth.auth import get_current_user
from AiVision.api.deps import get_department_service
from AiVision.departments.service import DepartmentService

router = APIRouter(prefix="/api/departments", tags=["departments"])


@router.get("")
def list_departments(
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """查询所有部门。"""
    depts = dept_service.list_departments()
    return [{"name": d.name, "display_name": d.display_name} for d in depts]


@router.get("/{name}/features")
def get_department_features(
    name: str,
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """获取部门下的功能列表。"""
    return dept_service.get_features_by_department(name)
