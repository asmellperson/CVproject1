"""外部报警统一只读入口，请求按数字类型和部门选择数据。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import AwareDatetime

from AiVision.alarms import external as service
from AiVision.alarms.records.schema import ExternalAlarmListResponse, ExternalAlarmResponse
from AiVision.api.deps import get_department_service
from AiVision.departments.department_registry import DEPARTMENT_SPECS, require_department
from . import common

router = APIRouter(prefix="/alarms", tags=["external-alarms"])


def department_access(department: str, catalog=Depends(get_department_service)) -> service.ExternalAlarmScope:
    try:
        require_department(department)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    features = catalog.feature_access().get(department, [])
    available = {number: feature for number, feature in service.feature_types().items() if feature in features}
    if not available:
        raise HTTPException(403, "此事业部未分配对应报警功能")
    return service.ExternalAlarmScope(department, available)


@router.get("/departments", response_model=list[common.DepartmentResponse])
def departments(catalog=Depends(get_department_service)):
    access = catalog.feature_access()
    return [
        common.DepartmentResponse(name=name, display_name=spec.display_name)
        for name, spec in DEPARTMENT_SPECS.items()
        if set(service.SUPPORTED_FEATURES).intersection(access.get(name, []))
    ]


@router.get("", response_model=ExternalAlarmListResponse)
def history(
    scope: service.ExternalAlarmScope = Depends(department_access),
    violation_type: list[int] | None = Query(None), camera_key: str | None = None,
    start: AwareDatetime | None = None, end: AwareDatetime | None = None,
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
):
    try:
        return service.history(scope, violation_types=violation_type, camera_key=camera_key,
                               start=start, end=end, limit=limit, offset=offset)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{alarm_id}", response_model=ExternalAlarmResponse)
def alarm_detail(alarm_id: int, scope: service.ExternalAlarmScope = Depends(department_access)):
    result = service.alarm_detail(scope, alarm_id)
    if result is None:
        raise HTTPException(404, "alarm not found")
    return result


@router.get("/{alarm_id}/image", response_class=FileResponse, responses={200: {"content": {"image/png": {}}}})
def alarm_image(alarm_id: int, scope: service.ExternalAlarmScope = Depends(department_access)):
    path = service.alarm_image(scope, alarm_id)
    if path is None:
        raise HTTPException(404, "alarm image not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})
