"""烟雾设备配置仅面向获授权的配置管理员；运行状态可供普通用户读取。"""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from auth.auth import get_current_user, require_config_manager
from auth.feature_permissions import require_department_write_access, require_feature_access
from AiVision.api.deps import get_camera_config_manager, get_current_orchestrator
from AiVision.core.logger import logger
from AiVision.features._shared.config_manager import feature_config_manager
from AiVision.features.registry import get_spec
from AiVision.features.smoke_detection.device import SmokeDeviceError
from AiVision.features.smoke_detection.device_schema import (
    SmokeParametersState, SmokeParametersUpdate, SmokeShieldState, SmokeShieldUpdate,
)
from AiVision.features.smoke_detection.service import smoke_device_service


FEATURE = "smoke_detection"
router = APIRouter(prefix="/api/smoke", tags=["smoke-detection"])


class SmokeMonitorState(BaseModel):
    camera_key: str
    feature: Literal["smoke_detection"] = FEATURE
    online: bool = False
    connection_state: str = "disabled"
    alarm: bool | None = None
    alarm_state: Literal["active", "inactive", "unknown"] = "unknown"
    event_protocol_verified: bool = False
    reason: str = "disabled"
    message: str = "设备报警接收未启动"
    event_channel_id: int
    last_event_at: str | None = None
    updated_at: str | None = None
    valid_for_seconds: float = 0
    details: list[dict] = Field(default_factory=list)


def get_smoke_device_service():
    return smoke_device_service


def smoke_camera(key: str, department: str, user: dict, manager, *, configuring: bool):
    """以资源真实归属授权，不能通过请求的事业部扩大访问范围。"""
    camera = manager.get_camera(key)
    if camera is None:
        raise HTTPException(404, "摄像头不存在")
    actual_department = camera.get("department")
    if not actual_department or department != actual_department:
        raise HTTPException(403, "摄像头不属于当前事业部")
    require_feature_access(user, FEATURE, actual_department)
    if configuring:
        require_department_write_access(user, actual_department)
        if not camera.get("enabled"):
            raise HTTPException(409, "摄像头已停用")
    result = feature_config_manager.get_config(get_spec(FEATURE), key)
    if result is None:
        raise HTTPException(404, "摄像头烟雾检测配置不存在")
    current = result["camera"]
    if current.get("department") != actual_department or current.get("camera_id") != camera.get("camera_id"):
        raise HTTPException(409, "摄像头归属已变化，请重新加载")
    return current, result["config"]


def _device_call(method, camera, config, *args):
    try:
        return method(camera, config, *args)
    except SmokeDeviceError as exc:
        logger.warning(f"[SmokeDevice] camera_id={camera['camera_id']}：{exc}")
        raise HTTPException(exc.status_code, str(exc)) from None


@router.get("/{key}/parameters", response_model=SmokeParametersState)
def get_parameters(key: str, department: str = Query(..., min_length=1),
                   user: dict = Depends(require_config_manager), manager=Depends(get_camera_config_manager),
                   service=Depends(get_smoke_device_service)):
    camera, config = smoke_camera(key, department, user, manager, configuring=True)
    return _device_call(service.parameters, camera, config)


@router.put("/{key}/parameters", response_model=SmokeParametersState)
def save_parameters(key: str, payload: SmokeParametersUpdate, department: str = Query(..., min_length=1),
                    user: dict = Depends(require_config_manager), manager=Depends(get_camera_config_manager),
                    service=Depends(get_smoke_device_service)):
    camera, config = smoke_camera(key, department, user, manager, configuring=True)
    return _device_call(service.save_parameters, camera, config, payload)


@router.get("/{key}/shields", response_model=SmokeShieldState)
def get_shields(key: str, department: str = Query(..., min_length=1),
                user: dict = Depends(require_config_manager), manager=Depends(get_camera_config_manager),
                service=Depends(get_smoke_device_service)):
    camera, config = smoke_camera(key, department, user, manager, configuring=True)
    return _device_call(service.shields, camera, config)


@router.put("/{key}/shields", response_model=SmokeShieldState)
def save_shields(key: str, payload: SmokeShieldUpdate, department: str = Query(..., min_length=1),
                 user: dict = Depends(require_config_manager), manager=Depends(get_camera_config_manager),
                 service=Depends(get_smoke_device_service)):
    camera, config = smoke_camera(key, department, user, manager, configuring=True)
    return _device_call(service.save_shields, camera, config, payload)


@router.get("/{key}/picture")
def get_picture(key: str, department: str = Query(..., min_length=1),
                user: dict = Depends(require_config_manager), manager=Depends(get_camera_config_manager),
                service=Depends(get_smoke_device_service)):
    camera, config = smoke_camera(key, department, user, manager, configuring=True)
    content = _device_call(service.picture, camera, config)
    return Response(content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/{key}/status", response_model=SmokeMonitorState)
def get_status(key: str, department: str = Query(..., min_length=1),
               user: dict = Depends(get_current_user), manager=Depends(get_camera_config_manager),
               orchestrator=Depends(get_current_orchestrator)):
    camera, config = smoke_camera(key, department, user, manager, configuring=False)
    consumer = orchestrator.consumers.get(FEATURE)
    snapshot = (consumer.get_monitor_status(key) if consumer and consumer.running else None) or {}
    updated = snapshot.get("updated_at_s")
    updated_at = datetime.fromtimestamp(updated, timezone.utc).astimezone().isoformat() if updated else None
    connected = snapshot.get("connection_state") == "connected"
    alarm_state = snapshot.get("alarm_state", "unknown") if connected else "unknown"
    return SmokeMonitorState(
        camera_key=key,
        online=bool(camera.get("enabled") and key in orchestrator.camera_runtime_manager.list_running()),
        connection_state=snapshot.get("connection_state", "disabled"),
        alarm=alarm_state == "active" if alarm_state != "unknown" else None,
        alarm_state=alarm_state,
        event_protocol_verified=bool(snapshot.get("event_protocol_verified")),
        reason=snapshot.get("reason", "disabled"),
        message=snapshot.get("message", "设备报警接收未启动"),
        event_channel_id=config["value"]["event_channel_id"],
        last_event_at=snapshot.get("last_event_at"),
        updated_at=updated_at,
        valid_for_seconds=snapshot.get("valid_for_seconds", 0) if connected else 0,
        details=snapshot.get("details", []),
    )
