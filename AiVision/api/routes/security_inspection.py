"""安检历史、运行状态和全局模型参数；摄像头和检测参数复用公共 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from auth.auth import get_current_user, require_admin
from auth.feature_permissions import require_feature_access
from AiVision.api.deps import get_inspection_consumer, get_inspection_service
from AiVision.departments.department_registry import require_department
from AiVision.features.security_inspection.schema import HistoryResponse, SettingsResponse, StatusResponse, VlmSettings
from AiVision.features.security_inspection.service import InspectionService

router = APIRouter(prefix="/api/security-inspection", tags=["security-inspection"])


def department_access(department: str, user: dict = Depends(get_current_user)) -> str:
    """校验正式事业部及对应安检功能授权。"""
    try:
        require_department(department)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    require_feature_access(user, "security_inspection", department)
    return department


@router.get("/history", response_model=HistoryResponse)
def history(
    department: str = Depends(department_access),
    camera_id: int | None = Query(None, gt=0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service=Depends(get_inspection_service),
):
    """在已授权事业部内查询可选摄像头的分页会话历史。"""
    return service.history(department, camera_id=camera_id, limit=limit, offset=offset)


def build_inspection_image_response(service: InspectionService, department: str, session_id: str) -> Response:
    """平台与外部入口复用证据读取响应，禁止客户端缓存已过期的图片。"""
    result = service.image(department, session_id)
    if result is None:
        raise HTTPException(404, "安检证据不存在或已过期")
    data, media_type = result
    return Response(data, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.get("/history/{session_id}/image.jpg", response_class=Response,
            responses={200: {"content": {"image/jpeg": {}}}})
def history_image(
    session_id: str,
    department: str = Depends(department_access),
    service=Depends(get_inspection_service),
):
    """通过人员会话及安检功能权限读取当前事业部的证据。"""
    return build_inspection_image_response(service, department, session_id)


@router.get("/status", response_model=StatusResponse)
def status(department: str = Depends(department_access), consumer=Depends(get_inspection_consumer)):
    """展示部门排队与活动任务，消费者未运行时明确返回不可用原因。"""
    return InspectionService.runtime_status(department, consumer)


@router.get("/settings", response_model=VlmSettings, dependencies=[Depends(require_admin)])
def get_settings(service=Depends(get_inspection_service)):
    """读取当前保存的全局内部模型参数。"""
    return service.get_settings()


@router.put("/settings", response_model=SettingsResponse, dependencies=[Depends(require_admin)])
def save_settings(payload: VlmSettings, service=Depends(get_inspection_service), consumer=Depends(get_inspection_consumer)):
    """先保存模型设置，再重配现有运行时；无消费者时执行独立健康探测。"""
    service.save_settings(payload)
    if consumer is not None:
        consumer.vlm_runtime.configure(payload)
        health = consumer.vlm_runtime.health_status()
    else:
        health = service.check_model(payload)
    return {"settings": payload, "vlm": health}
