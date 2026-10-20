"""登录账号下的非法闯闸实时状态，授权按摄像头实际部门校验。"""
from fastapi import APIRouter, Depends

from auth.auth import get_current_user
from auth.feature_permissions import require_feature_access
from AiVision.api.deps import get_camera_config_manager, get_optional_orchestrator
from AiVision.api.routes.cameras import get_camera_for_user
from AiVision.features.tailgating.schema import FEATURE, TailgatingStatus
from AiVision.features.tailgating.service import camera_status

router = APIRouter(prefix="/api/tailgating", tags=["tailgating"])


@router.get("/cameras/{key}/status", response_model=TailgatingStatus)
def status(key: str, user=Depends(get_current_user), manager=Depends(get_camera_config_manager),
           orchestrator=Depends(get_optional_orchestrator)):
    camera = get_camera_for_user(manager, key, user)
    require_feature_access(user, FEATURE, camera["department"])
    return camera_status(camera, orchestrator)
