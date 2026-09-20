"""报警处置状态、备注和历史记录接口。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from auth.auth import get_current_user
from AiVision.alarms.records import dispositions
from AiVision.alarms.records.schema import AlarmDisposition, AlarmId, DispositionPage, DispositionUpdate

router = APIRouter(prefix="/api/alarm-dispositions", tags=["alarms"])


class DispositionUpdateResponse(BaseModel):
    success: bool
    item: AlarmDisposition


@router.get("", response_model=DispositionPage)
def list_dispositions(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[AlarmId | None, Query()] = None,
    user: dict = Depends(get_current_user),
):
    return dispositions.list_dispositions(user, limit, cursor)


@router.get("/{alarm_id}", response_model=AlarmDisposition)
def get_disposition(alarm_id: AlarmId, user: dict = Depends(get_current_user)):
    return dispositions.get_disposition(user, alarm_id)


@router.post("", response_model=DispositionUpdateResponse)
def update_disposition(payload: DispositionUpdate, user: dict = Depends(get_current_user)):
    return {"success": True, "item": dispositions.update_disposition(user, payload)}
