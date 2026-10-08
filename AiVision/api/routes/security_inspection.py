"""安检历史、运行状态和全局模型参数；摄像头和检测参数复用公共 API。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth.auth import get_current_user, require_admin
from auth.feature_permissions import require_feature_access
from AiVision.departments.department_registry import require_department
from AiVision.features.security_inspection.schema import InspectionVerdict, VlmHealth, VlmSettings
from AiVision.features.security_inspection.service import InspectionService

router = APIRouter(prefix="/api/security-inspection", tags=["security-inspection"])


def get_service():
    """提供安检设置和历史持久化服务。"""
    return InspectionService()


def get_consumer():
    """尝试取得安检消费者，平台尚未启动时返回 None。"""
    from AiVision.runtime.orchestrator import get_orchestrator

    try:
        orchestrator = get_orchestrator()
    except RuntimeError:
        return None
    return orchestrator.consumers.get("security_inspection")


def department_access(department: str, user: dict = Depends(get_current_user)) -> str:
    """校验正式事业部及对应安检功能授权。"""
    try:
        require_department(department)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    require_feature_access(user, "security_inspection", department)
    return department


class InspectionStats(BaseModel):
    """成功判定、错误与取消的统计，合格率独立于执行失败。"""
    total: int
    compliant: int
    non_compliant: int
    error: int
    cancelled: int
    rate: float


class SessionResponse(BaseModel):
    """安检会话的时间、状态、判定和错误详情。"""
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
    """组合查询范围统计与当前页会话记录。"""
    stats: InspectionStats
    items: list[SessionResponse]


class StatusResponse(BaseModel):
    """指定事业部的任务运行数量与公共模型健康状态。"""
    running: bool
    queue: int
    active: int
    error: str | None
    vlm: VlmHealth


class SettingsResponse(BaseModel):
    """保存后的模型设置及其当前健康检查结果。"""
    settings: VlmSettings
    vlm: VlmHealth


@router.get("/history", response_model=HistoryResponse)
def history(
    department: str = Depends(department_access),
    camera_id: int | None = Query(None, gt=0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service=Depends(get_service),
):
    """在已授权事业部内查询可选摄像头的分页会话历史。"""
    return service.history(department, camera_id=camera_id, limit=limit, offset=offset)


@router.get("/status", response_model=StatusResponse)
def status(department: str = Depends(department_access), consumer=Depends(get_consumer)):
    """展示部门排队与活动任务，消费者未运行时明确返回不可用原因。"""
    if consumer is None:
        return StatusResponse(
            running=False,
            queue=0,
            active=0,
            error="安检处理器未运行，请检查人体模型状态",
            vlm=VlmHealth(),
        )
    result = consumer.vlm_runtime.status(department)
    if not consumer.running:
        result.update(running=False, error="安检处理器未运行，请检查人体模型状态")
    return result


@router.get("/settings", response_model=VlmSettings, dependencies=[Depends(require_admin)])
def get_settings(service=Depends(get_service)):
    """读取当前保存的全局内部模型参数。"""
    return service.get_settings()


@router.put("/settings", response_model=SettingsResponse, dependencies=[Depends(require_admin)])
def save_settings(payload: VlmSettings, service=Depends(get_service), consumer=Depends(get_consumer)):
    """先保存模型设置，再重配现有运行时；无消费者时执行独立健康探测。"""
    service.save_settings(payload)
    if consumer is not None:
        consumer.vlm_runtime.configure(payload)
        health = consumer.vlm_runtime.health_status()
    else:
        health = service.check_model(payload)
    return {"settings": payload, "vlm": health}
