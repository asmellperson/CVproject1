"""平台登录会话下的围栏状态和共享人员选择接口。"""
from fastapi import APIRouter, Depends, Query

from auth.auth import get_current_user
from auth.feature_permissions import require_feature_access
from AiVision.api.deps import get_camera_config_manager, get_optional_orchestrator
from AiVision.api.routes.cameras import get_camera_for_user
from AiVision.features.security_fence import service
from AiVision.features.security_fence.schema import FEATURE, FenceStatus, PersonChoices

router = APIRouter(prefix="/api/security-fence", tags=["security-fence"])


@router.get("/cameras/{key}/status", response_model=FenceStatus)
def status(key: str, user=Depends(get_current_user), manager=Depends(get_camera_config_manager), orchestrator=Depends(get_optional_orchestrator)):
    camera = get_camera_for_user(manager, key, user)
    require_feature_access(user, FEATURE, camera["department"])
    return service.camera_status(camera, orchestrator)


@router.get("/persons", response_model=PersonChoices)
def persons(department: str, keyword: str | None = Query(None, max_length=255),
            page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
            person_ids: list[int] | None = Query(None, max_length=10000), user=Depends(get_current_user)):
    require_feature_access(user, FEATURE, department)
    return service.person_choices(keyword, page, page_size, person_ids)
