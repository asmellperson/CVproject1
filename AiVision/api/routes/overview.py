"""平台总览接口。"""
from fastapi import APIRouter, Depends

from auth.auth import get_current_user
from auth.feature_permissions import feature_departments
from AiVision.features.registry import all_specs
from AiVision.api.deps import (
    get_camera_config_manager, get_guard_behavior_service,
    get_logistics_channel_service, get_optional_orchestrator,
)
from AiVision.api.routes.cameras import _camera_departments_for_user, camera_response_for_user
from AiVision.departments.department_registry import DEPARTMENT_SPECS
from AiVision.runtime.overview import OverviewStatus, build_overview

router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("", response_model=OverviewStatus)
def overview(
    user: dict = Depends(get_current_user),
    cameras=Depends(get_camera_config_manager),
    logistics=Depends(get_logistics_channel_service),
    guards=Depends(get_guard_behavior_service),
    orchestrator=Depends(get_optional_orchestrator),
):
    """按账号事业部及功能分配过滤资源，再统一汇总摄像头、业务对象和服务状态。"""
    departments = list(DEPARTMENT_SPECS) if user["role"] == "admin" else _camera_departments_for_user(user)
    # 一次读取授权范围，避免每个事业部重复扫描全部功能配置表。
    department_order = {department: index for index, department in enumerate(departments)}
    items = [camera_response_for_user(camera, user) for camera in sorted(
        cameras.list_cameras(departments=departments),
        key=lambda camera: department_order[camera["department"]],
    )]
    feature_access = {
        department: [feature for feature in all_specs() if department in feature_departments(user, feature)]
        for department in departments
    }
    return build_overview(departments, items, logistics, guards, orchestrator, feature_access)
