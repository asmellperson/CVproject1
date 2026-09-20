"""平台总览接口。"""
from fastapi import APIRouter, Depends

from auth.auth import get_current_user
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
    departments = list(DEPARTMENT_SPECS) if user["role"] == "admin" else _camera_departments_for_user(user)
    items = [camera_response_for_user(camera, user) for department in departments
             for camera in cameras.list_cameras(department)]
    return build_overview(departments, items, logistics, guards, orchestrator)
