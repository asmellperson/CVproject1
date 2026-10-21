"""普通检测的三通道告警契约；任何层级的未定义字段均拒绝。"""
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class SqlAlarmParams(BaseModel):
    """数据库告警通道的参数占位结构，拒绝未声明字段。"""
    model_config = ConfigDict(extra="forbid", strict=True)


class HornAlarmParams(SqlAlarmParams):
    """喇叭通道的设备与事件绑定参数；允许尚未配置绑定。"""
    horn_id: int | None = Field(None, gt=0)
    horn_event_id: int | None = Field(None, ge=0)


class WechatAlarmParams(SqlAlarmParams):
    """企业微信接收对象配置，空字符串表示未指定接收对象。"""
    user: str = ""


Params = TypeVar("Params", bound=BaseModel)


class AlarmChannel(BaseModel, Generic[Params]):
    """统一包装通道开关和参数，参数类型由具体通道约束。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    parm: Params = Field(default_factory=dict, validate_default=True)


class TimedAlarmChannel(AlarmChannel[Params], Generic[Params]):
    """通知通道独立冷却；未设置时沿用当前配置的报警记录间隔。"""
    interval: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class AlarmConfigSchema(BaseModel):
    """数据库、喇叭和企业微信三个独立告警通道的配置。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    sql: AlarmChannel[SqlAlarmParams] = Field(
        default_factory=lambda: AlarmChannel(parm=SqlAlarmParams()))
    horn: TimedAlarmChannel[HornAlarmParams] = Field(
        default_factory=lambda: TimedAlarmChannel(parm=HornAlarmParams()))
    wechat: TimedAlarmChannel[WechatAlarmParams] = Field(
        default_factory=lambda: TimedAlarmChannel(parm=WechatAlarmParams()))
