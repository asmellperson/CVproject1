"""大屏只读围栏接口；配置和白名单写入由平台管理员负责。"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import AwareDatetime

from AiVision.api.deps import get_camera_config_manager, get_current_orchestrator, get_department_service, get_optional_orchestrator
from AiVision.api.routes.cameras import build_camera_frame_response
from AiVision.departments.department_registry import DEPARTMENT_SPECS
from AiVision.features.security_fence import service
from AiVision.features.security_fence.schema import FEATURE, FenceAlarm, FenceHistory, FenceStatus
from . import common


def no_store(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/security-fence", tags=["external-security-fence"], dependencies=[Depends(no_store)])


def department_access(department: str, catalog=Depends(get_department_service)):
    return common.require_feature_department(department, FEATURE, catalog)


def scoped_camera(shm_name: str, department: str = Depends(department_access), manager=Depends(get_camera_config_manager)):
    return common.scoped_camera(manager, shm_name, department)


@router.get("/departments", response_model=list[common.DepartmentResponse])
def departments(catalog=Depends(get_department_service)):
    access = catalog.feature_access()
    return [{"name": name, "display_name": spec.display_name} for name, spec in DEPARTMENT_SPECS.items()
            if FEATURE in access.get(name, [])]


@router.get("/cameras", response_model=list[common.CameraResponse])
def cameras(department: str = Depends(department_access), enabled_only: bool = True, manager=Depends(get_camera_config_manager)):
    result = []
    for camera in manager.list_cameras(department=department):
        enabled = bool(camera["functions"].get(FEATURE))
        if camera["department"] != department or (enabled_only and not (camera["enabled"] and enabled)):
            continue
        order = camera["feature_sort_orders"].get(FEATURE, camera["sort_order"])
        result.append(common.CameraResponse.model_validate({**camera, "functions": {FEATURE: enabled}, "feature_sort_orders": {FEATURE: order}}))
    return sorted(result, key=lambda camera: (camera.feature_sort_orders[FEATURE], camera.camera_id))


@router.get("/cameras/{shm_name}/status", response_model=FenceStatus)
def status(camera=Depends(scoped_camera), orchestrator=Depends(get_optional_orchestrator)):
    return service.camera_status(camera, orchestrator)


@router.get("/status", response_model=list[FenceStatus])
def statuses(department: str = Depends(department_access), manager=Depends(get_camera_config_manager), orchestrator=Depends(get_optional_orchestrator)):
    return [service.camera_status(camera, orchestrator) for camera in manager.list_cameras(department=department)
            if camera["department"] == department and camera["functions"].get(FEATURE)]


@router.get("/cameras/{shm_name}/frame.jpg", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
def frame(camera=Depends(scoped_camera), annotated: bool = True, quality: int = Query(85, ge=1, le=100),
          max_width: int | None = Query(None, ge=1, le=4096), max_height: int | None = Query(None, ge=1, le=4096),
          orchestrator=Depends(get_current_orchestrator)):
    response = build_camera_frame_response(key=camera["shm_name"], feature=FEATURE if annotated else None,
                                           quality=quality, max_width=max_width, max_height=max_height, orchestrator=orchestrator)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/history", response_model=FenceHistory)
def history(department: str = Depends(department_access), camera_key: str | None = None,
            start: AwareDatetime | None = None, end: AwareDatetime | None = None,
            limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    try:
        return service.history(department, camera_key=camera_key, start=start, end=end, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/alarms/{alarm_id}", response_model=FenceAlarm)
def alarm_detail(alarm_id: int, department: str = Depends(department_access)):
    result = service.alarm_detail(department, alarm_id)
    if result is None:
        raise HTTPException(404, "alarm not found")
    return result


@router.get("/alarms/{alarm_id}/image")
def alarm_image(alarm_id: int, department: str = Depends(department_access)):
    path = service.alarm_image(department, alarm_id)
    if path is None:
        raise HTTPException(404, "alarm image not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})
