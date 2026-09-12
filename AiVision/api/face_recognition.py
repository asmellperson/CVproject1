"""电子电工事业部识别记录的只读接口。"""
from fastapi import APIRouter, Depends, Query

from auth.auth import get_current_user
from AiVision.api.cameras import camera_read_department
from AiVision.features.recognize_face.records import list_recognition_records
from AiVision.features.recognize_face.schema import RecognitionRecordPage

router = APIRouter(prefix="/api/face-recognition", tags=["face-recognition"])


@router.get("/records", response_model=RecognitionRecordPage)
def get_records(
    camera_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    camera_read_department(user, "electronics_electrician")
    return list_recognition_records(camera_id, page, page_size)
