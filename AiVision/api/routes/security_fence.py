"""平台登录会话下的围栏状态及事业部通行白名单接口。"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.auth import get_current_user, require_admin
from auth.feature_permissions import require_feature_access
from AiVision.api.deps import get_camera_config_manager, get_optional_orchestrator
from AiVision.api.routes.cameras import get_camera_for_user
from AiVision.features.security_fence import service
from AiVision.features.security_fence.schema import FEATURE, FenceStatus
from AiVision.features.face_recognition.schema import FacePersonItem, FacePersonPage, FacePersonUpdate

router = APIRouter(prefix="/api/security-fence", tags=["security-fence"])


@router.get("/cameras/{key}/status", response_model=FenceStatus)
def status(key: str, user=Depends(get_current_user), manager=Depends(get_camera_config_manager), orchestrator=Depends(get_optional_orchestrator)):
    camera = get_camera_for_user(manager, key, user)
    require_feature_access(user, FEATURE, camera["department"])
    return service.camera_status(camera, orchestrator)


@router.get("/persons", response_model=FacePersonPage)
def persons(department: str, keyword: str | None = Query(None, max_length=255),
            page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
            source: Literal["one", "two"] | None = None, is_active: bool | None = None,
            is_allowed: bool | None = None, user=Depends(get_current_user)):
    """共享人员资料，允许状态只反映指定事业部的围栏授权。"""
    require_feature_access(user, FEATURE, department)
    return service.person_library.list_persons(
        department=department, keyword=keyword, page=page, page_size=page_size,
        source=source, is_active=is_active, is_allowed=is_allowed,
    )


@router.patch("/persons/{person_id}", response_model=FacePersonItem)
def update_person(person_id: int, payload: FacePersonUpdate, department: str = Query(...),
                  user=Depends(require_admin)):
    """仅管理员可保存已分配围栏功能的当前事业部授权。"""
    require_feature_access(user, FEATURE, department)
    person = service.person_library.update_person_allowed(person_id, payload.is_allowed, department=department)
    if person is None:
        raise HTTPException(status_code=404, detail="person not found")
    return person
