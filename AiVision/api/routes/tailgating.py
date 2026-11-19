"""登录账号下的非法闯闸实时状态，授权按摄像头实际部门校验。"""
from fastapi import APIRouter, Depends, Request, Response

from auth.auth import get_current_user
from AiVision.api.deps import get_camera_config_manager, get_optional_orchestrator
from AiVision.api.routes.cameras import get_camera_for_status
from AiVision.api.status_timing import status_sample_marker
from AiVision.features.tailgating.schema import FEATURE, TailgatingStatus
from AiVision.features.tailgating.service import camera_status

router = APIRouter(prefix="/api/tailgating", tags=["tailgating"])


@router.get("/cameras/{key}/status", response_model=TailgatingStatus)
def status(key: str, request: Request, response: Response, user=Depends(get_current_user), manager=Depends(get_camera_config_manager),
           orchestrator=Depends(get_optional_orchestrator)):
    camera = get_camera_for_status(manager, key, user, FEATURE)
    return camera_status(camera, orchestrator, mark_sample=status_sample_marker(request, response))
