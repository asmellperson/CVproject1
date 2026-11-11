"""
api/routes/exception_alerts.py
系统异常告警配置接口。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.auth import require_admin
from AiVision.core.system_config import system_config_service


router = APIRouter(prefix="/api/exception-alert", tags=["exception-alert"])


# 定义系统异常告警配置的数据模型，包含三个字段：
# BaseModel主要作用：1、接收前端传来的JSON；2、检查字段类型；3、自动转成Python对象
class ExceptionAlertSettings(BaseModel):
    """系统运行异常的企业微信开关、接收对象和重复通知间隔。"""
    wechat_enable: bool = False                              # 是否开启'系统异常'的启用微信停止
    wechat_user: str = ""                                    # 微信用户ID，多个用户用逗号分隔
    repeat_interval_minutes: int = 60                        # 重复告警的间隔时间


@router.get("", dependencies=[Depends(require_admin)])
def get_exception_alert() -> dict:
    """读取当前系统异常告警的配置。企微通知开关、接收人、重复告警间隔。"""
    return system_config_service.get_exception_alert()


@router.put("")
def update_exception_alert(
    payload: ExceptionAlertSettings,         # payload：已经校验过的数据对象
    _user: dict = Depends(require_admin),    # 修改这项配置的必须是管理员
) -> dict:
    """修改系统异常报警配置"""
    try:
        # 保存异常告警配置到数据库中，返回保存后的配置
        return system_config_service.save_exception_alert(payload.model_dump())          # payload.model_dump()：将Pydantic模型对象转换为字典
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
