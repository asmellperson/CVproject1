"""报警处置状态、备注和历史记录接口。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from auth.auth import get_current_user
from AiVision.alarms.records import dispositions
from AiVision.alarms.records.schema import AlarmDisposition, AlarmId, DispositionPage, DispositionUpdate

router = APIRouter(prefix="/api/alarm-dispositions", tags=["alarms"])


class DispositionUpdateResponse(BaseModel):
    """处置保存结果及实际持久化的当前记录。"""
    success: bool
    item: AlarmDisposition


@router.get("", response_model=DispositionPage)
def list_dispositions(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[AlarmId | None, Query()] = None,
    user: dict = Depends(get_current_user),
):
    """按用户可访问范围和告警 ID 游标读取处置列表。"""
    return dispositions.list_dispositions(user, limit, cursor)


@router.get("/{alarm_id}", response_model=AlarmDisposition)
def get_disposition(alarm_id: AlarmId, user: dict = Depends(get_current_user)):
    """查询单条可见告警处置，授权与不存在处理交由服务层。"""
    return dispositions.get_disposition(user, alarm_id)


@router.post("", response_model=DispositionUpdateResponse)
def update_disposition(payload: DispositionUpdate, user: dict = Depends(get_current_user)):
    """使用当前登录人作为操作者，保存状态、备注及历史。"""
    return {"success": True, "item": dispositions.update_disposition(user, payload)}
