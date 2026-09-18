"""安检历史、运行状态和全局模型参数；摄像头和检测参数复用公共 API。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth.auth import get_current_user, require_admin
from AiVision.departments.department_registry import require_department
from AiVision.features.security_inspection.schema import InspectionVerdict, VlmSettings
from AiVision.features.security_inspection.service import InspectionService

router = APIRouter(prefix="/api/security-inspection", tags=["security-inspection"])


def get_service():
    return InspectionService()


def get_consumer():
    from AiVision.runtime.orchestrator import get_orchestrator

    try:
        orchestrator = get_orchestrator()
    except RuntimeError:
        return None
    return orchestrator.consumers.get("security_inspection")


def department_access(department: str, user: dict = Depends(get_current_user)) -> str:
    try:
        require_department(department)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if user.get("role") != "admin" and (user.get("role") != "viewer" or department not in user.get("departments", [])):
        raise HTTPException(403, "department permission required")
    return department


class InspectionStats(BaseModel):
    total: int
    compliant: int
    non_compliant: int
    error: int
    cancelled: int
    rate: float


class SessionResponse(BaseModel):
    session_id: str
    camera_id: int | None
    camera_name: str
    roi_name: str
    started_at: str
    ended_at: str
    duration_sec: float
    status: Literal["compliant", "non_compliant", "error", "cancelled"]
    verdict: InspectionVerdict | None
    error: str | None
    latency_sec: float | None


class HistoryResponse(BaseModel):
    stats: InspectionStats
    items: list[SessionResponse]


class StatusResponse(BaseModel):
    running: bool
    queue: int
    active: int
    error: str | None


@router.get("/history", response_model=HistoryResponse)
def history(
    department: str = Depends(department_access),
    camera_id: int | None = Query(None, gt=0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service=Depends(get_service),
):
    return service.history(department, camera_id=camera_id, limit=limit, offset=offset)


@router.get("/status", response_model=StatusResponse)
def status(department: str = Depends(department_access), consumer=Depends(get_consumer)):
    if consumer is None or not consumer.running:
        return {"running": False, "queue": 0, "active": 0, "error": "安检处理器未运行，请检查人体模型状态"}
    return consumer.vlm_runtime.status(department)


@router.get("/settings", response_model=VlmSettings, dependencies=[Depends(require_admin)])
def get_settings(service=Depends(get_service)):
    return service.get_settings()


@router.put("/settings", response_model=VlmSettings, dependencies=[Depends(require_admin)])
def save_settings(payload: VlmSettings, service=Depends(get_service), consumer=Depends(get_consumer)):
    service.save_settings(payload)
    if consumer is not None:
        consumer.vlm_runtime.configure(payload)
    return payload
