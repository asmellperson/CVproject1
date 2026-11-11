"""事业部目录与检测功能访问分配 API。

普通读取按登录权限提供功能范围，完整分配矩阵的维护仅向管理员开放；
权限分配不直接改变摄像头检测配置或运行状态。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from auth.auth import get_current_user, require_admin
from auth.feature_permissions import accessible_departments
from AiVision.api.deps import get_department_service
from AiVision.departments.service import DepartmentService, FeatureAssignmentConflict
from AiVision.departments.schema import FeatureAssignmentsResponse, FeatureAssignmentsUpdate
from AiVision.api.routes.cameras import camera_read_department

router = APIRouter(prefix="/api/departments", tags=["departments"])


@router.get("")
def list_departments(
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """查询所有部门。"""
    depts = dept_service.list_departments()
    allowed = accessible_departments(user)
    return [{"name": d.name, "display_name": d.display_name} for d in depts if d.name in allowed]


@router.get("/feature-access")
def get_feature_access(response: Response, user: dict = Depends(get_current_user)) -> dict[str, list[str]]:
    """已登录页面定期读取权限，不重复记录访问审计。"""
    response.headers["Cache-Control"] = "no-store"
    return user["feature_access"]


@router.get("/feature-settings", response_model=FeatureAssignmentsResponse)
def get_feature_settings(
    response: Response,
    _admin: dict = Depends(require_admin),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """管理员读取完整分配矩阵。"""
    response.headers["Cache-Control"] = "no-store"
    return dept_service.feature_settings()


@router.put("/feature-settings", response_model=FeatureAssignmentsResponse)
def save_feature_settings(
    payload: FeatureAssignmentsUpdate,
    _admin: dict = Depends(require_admin),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """保存只变更访问权限，不修改摄像头配置或检测运行状态。"""
    try:
        return dept_service.save_feature_settings(payload.assignments)
    except FeatureAssignmentConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{name}/features")
def get_department_features(
    name: str,
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """获取部门下的功能列表。"""
    camera_read_department(user, name)
    try:
        return dept_service.get_features_by_department(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
