"""按事业部隔离人脸识别通行授权和识别记录。"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from auth.auth import get_current_user, require_admin
from auth.feature_permissions import feature_departments, require_feature_access
from AiVision.features.face_recognition.records import get_recognition_image, list_recognition_records
from AiVision.features.face_recognition.library.service import FaceLibraryService
from AiVision.features.face_recognition.schema import FacePersonItem, FacePersonPage, FacePersonUpdate, RecognitionRecordPage

router = APIRouter(prefix="/api/face-recognition", tags=["face-recognition"])


@router.get("/persons", response_model=FacePersonPage)
def get_persons(
    department: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=255),
    source: Literal["one", "two"] | None = None,
    is_active: bool | None = None,
    is_allowed: bool | None = None,
    user: dict = Depends(get_current_user),
):
    """校验具体事业部的功能权限，返回该事业部的通行授权状态。"""
    require_feature_access(user, "recognize_face", department)
    return FaceLibraryService().list_persons(
        department=department,
        page=page, page_size=page_size, keyword=keyword,
        source=source, is_active=is_active, is_allowed=is_allowed,
    )


@router.patch("/persons/{person_id}", response_model=FacePersonItem)
def update_person(
    person_id: int, payload: FacePersonUpdate,
    department: str = Query(...), user: dict = Depends(require_admin),
):
    """管理员仅可修改已分配人脸识别功能的指定事业部白名单。"""
    require_feature_access(user, "recognize_face", department)
    person = FaceLibraryService().update_person_allowed(person_id, payload.is_allowed, department=department)
    if person is None:
        raise HTTPException(status_code=404, detail="person not found")
    return person


@router.get("/records", response_model=RecognitionRecordPage)
def get_records(
    department: str = Query(...),
    camera_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """要求明确事业部并校验功能权限，再分页读取识别记录。"""
    require_feature_access(user, "recognize_face", department)
    return list_recognition_records(camera_id, page, page_size, department=department)


@router.get("/records/{record_id}/image")
def get_record_image(record_id: int, user: dict = Depends(get_current_user)):
    """仅返回账号授权事业部内的记录截图，并禁止客户端缓存。"""
    departments = feature_departments(user, "recognize_face")
    path = get_recognition_image(record_id, departments=departments)
    if path is None:
        raise HTTPException(status_code=404, detail="recognition image not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})
