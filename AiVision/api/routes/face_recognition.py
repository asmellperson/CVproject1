"""按摄像头事业部隔离的识别记录与平台统一人员权限接口。"""
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
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=255),
    source: Literal["one", "two"] | None = None,
    is_active: bool | None = None,
    is_allowed: bool | None = None,
    user: dict = Depends(get_current_user),
):
    require_feature_access(user, "recognize_face")
    return FaceLibraryService().list_persons(
        page=page, page_size=page_size, keyword=keyword,
        source=source, is_active=is_active, is_allowed=is_allowed,
    )


@router.patch("/persons/{person_id}", response_model=FacePersonItem)
def update_person(person_id: int, payload: FacePersonUpdate, _user: dict = Depends(require_admin)):
    person = FaceLibraryService().update_person_allowed(person_id, payload.is_allowed)
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
    require_feature_access(user, "recognize_face", department)
    return list_recognition_records(camera_id, page, page_size, department=department)


@router.get("/records/{record_id}/image")
def get_record_image(record_id: int, user: dict = Depends(get_current_user)):
    departments = feature_departments(user, "recognize_face")
    path = get_recognition_image(record_id, departments=departments)
    if path is None:
        raise HTTPException(status_code=404, detail="recognition image not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})
