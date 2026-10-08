"""指令驱动智慧安防的结果、事件及视频提问；配置复用公共 feature API。"""

from concurrent.futures import TimeoutError as FutureTimeout

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.auth import get_current_user
from auth.feature_permissions import require_feature_access
from AiVision.api.deps import get_camera_config_manager, get_optional_orchestrator
from AiVision.api.routes.cameras import camera_read_department, get_camera_for_user
from AiVision.core.settings import settings
from AiVision.features.visual_language_detection.runtime import VideoUnavailable
from AiVision.features.visual_language_detection.schema import (
    FEATURE_NAME, VideoAnswer, VideoQuestion, VisualLanguageHistory, VisualLanguageStatus,
)
from AiVision.features.visual_language_detection.service import VisualLanguageService

router = APIRouter(prefix="/api/visual-language-detection", tags=["visual-language-detection"])


def scoped_camera(key: str, department: str = Query(...), user: dict = Depends(get_current_user),
                  manager=Depends(get_camera_config_manager)):
    """要求明确事业部，核对功能访问权及摄像头归属后提供资源。"""
    scope = camera_read_department(user, department)
    require_feature_access(user, FEATURE_NAME, scope)
    camera = get_camera_for_user(manager, key, user)
    if camera["department"] != scope:
        raise HTTPException(404, "camera not found in department")
    return camera


def get_consumer(orchestrator=Depends(get_optional_orchestrator)):
    """返回可选视频理解消费者，平台未就绪时保持配置查询可用。"""
    return orchestrator.consumers.get(FEATURE_NAME) if orchestrator is not None else None


def get_service():
    """提供视频理解事件持久化服务。"""
    return VisualLanguageService()


@router.get("/cameras/{key}/status", response_model=VisualLanguageStatus)
def status(camera=Depends(scoped_camera), consumer=Depends(get_consumer)):
    """返回摄像头理解状态，并区分功能未启动、未启用和视频离线。"""
    if consumer is None or not consumer.running:
        return VisualLanguageStatus(error="指令驱动智慧安防尚未运行")
    result = consumer.visual_runtime.status(camera["camera_id"])
    if not camera["enabled"] or not camera["functions"][FEATURE_NAME]:
        result.error = "摄像头未启用指令驱动智慧安防"
    elif not consumer.is_camera_active(camera["shm_name"]):
        result.error = "摄像头离线，等待恢复画面"
    return result


@router.get("/cameras/{key}/events", response_model=VisualLanguageHistory)
def events(camera=Depends(scoped_camera), limit: int = Query(50, ge=1, le=200),
           before_id: int | None = Query(None, gt=0), service=Depends(get_service)):
    """按已授权摄像头读取事件历史，支持 ID 游标。"""
    return service.history(camera["camera_id"], camera["department"], limit, before_id)


@router.post("/cameras/{key}/questions", response_model=VideoAnswer)
def ask(payload: VideoQuestion, camera=Depends(scoped_camera), consumer=Depends(get_consumer)):
    """提交随新画面回答的问题并限时等待，超时取消 Future 并返回 504。"""
    if consumer is None or not camera["enabled"] or not camera["functions"][FEATURE_NAME]:
        raise HTTPException(503, "摄像头未运行或未添加到指令驱动智慧安防")
    try:
        future = consumer.ask(camera["camera_id"], camera["department"], payload.question)
        try:
            return future.result(timeout=settings.joyai.question_timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            raise HTTPException(504, "等待视频回答超时，请确认摄像头和指令驱动智慧安防服务正常") from exc
    except VideoUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
