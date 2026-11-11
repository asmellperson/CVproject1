"""镜头控制属于设备管理，仅对已登录管理员开放。"""
from fastapi import APIRouter, Depends, HTTPException, Query

from auth.auth import require_config_manager
from auth.feature_permissions import require_feature_access
from AiVision.api.deps import get_camera_config_manager, get_camera_zoom_service
from AiVision.cameras.zoom import CameraZoomError
from AiVision.cameras.zoom_schema import CameraZoomCapabilities, CameraZoomRequest, CameraZoomResult
from AiVision.core.logger import logger


router = APIRouter(prefix="/api/cameras", tags=["camera-zoom"])


def zoom_camera(key: str, feature: str, user: dict, manager, *, stopping: bool = False):
    """每次从数据库获取真实源与归属；停止允许摄像头刚被停用的在途动作收尾。"""
    camera = manager.get_camera(key)
    if camera is None:
        raise HTTPException(404, "摄像头不存在")
    if camera["department"] is None:
        raise HTTPException(403, "摄像头尚未分配事业部")
    require_feature_access(user, feature, camera["department"])
    if not stopping and not camera["enabled"]:
        raise HTTPException(409, "摄像头已停用")
    return camera


@router.get("/{key}/zoom", response_model=CameraZoomCapabilities)
def get_camera_zoom(
    key: str,
    feature: str = Query(..., min_length=1),
    user: dict = Depends(require_config_manager),
    manager=Depends(get_camera_config_manager),
    service=Depends(get_camera_zoom_service),
):
    """查询真实设备能力，不依据预先整理的 IP 名单判断。"""
    return service.capabilities(zoom_camera(key, feature, user, manager))


@router.post("/{key}/zoom", response_model=CameraZoomResult)
def control_camera_zoom(
    key: str,
    payload: CameraZoomRequest,
    feature: str = Query(..., min_length=1),
    user: dict = Depends(require_config_manager),
    manager=Depends(get_camera_config_manager),
    service=Depends(get_camera_zoom_service),
):
    """接受有限动作与受限速度比例，源、通道及单步持续时间由后端决定。"""
    camera = zoom_camera(key, feature, user, manager, stopping=payload.action == "stop")
    try:
        result = service.control(camera, payload.action, speed_fraction=payload.speed_fraction)
    except CameraZoomError as exc:
        logger.warning(f"[CameraZoom] camera_id={camera['camera_id']} feature={feature} action={payload.action}：{exc}")
        raise HTTPException(exc.status_code, str(exc)) from None
    logger.info(f"[CameraZoom] camera_id={camera['camera_id']} feature={feature} action={payload.action} 已停止")
    return result
