"""人员逗留报警的免登录只读入口，按事业部功能分配和记录归属隔离。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import AwareDatetime

from AiVision.api.deps import get_department_service
from AiVision.departments.department_registry import DEPARTMENT_SPECS
from AiVision.features.person_dwell import service
from AiVision.features.person_dwell.schema import FEATURE, HumanDwellAlarm, HumanDwellHistory
from . import common

router = APIRouter(prefix="/human-dwell", tags=["external-human-dwell"])


def department_access(department: str, catalog=Depends(get_department_service)) -> str:
    return common.require_feature_department(department, FEATURE, catalog)


@router.get("/departments", response_model=list[common.DepartmentResponse])
def departments(catalog=Depends(get_department_service)):
    access = catalog.feature_access()
    return [
        common.DepartmentResponse(name=name, display_name=spec.display_name)
        for name, spec in DEPARTMENT_SPECS.items() if FEATURE in access.get(name, [])
    ]


@router.get("/history", response_model=HumanDwellHistory)
def history(
    department: str = Depends(department_access), camera_key: str | None = None,
    start: AwareDatetime | None = None, end: AwareDatetime | None = None,
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
):
    try:
        return service.history(department, camera_key=camera_key, start=start, end=end, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/alarms/{alarm_id}", response_model=HumanDwellAlarm)
def alarm_detail(alarm_id: int, department: str = Depends(department_access)):
    result = service.alarm_detail(department, alarm_id)
    if result is None:
        raise HTTPException(404, "alarm not found")
    return result


@router.get("/alarms/{alarm_id}/image", response_class=FileResponse, responses={200: {"content": {"image/png": {}}}})
def alarm_image(alarm_id: int, department: str = Depends(department_access)):
    path = service.alarm_image(department, alarm_id)
    if path is None:
        raise HTTPException(404, "alarm image not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})
