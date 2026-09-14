"""普通检测的三通道告警契约；任何层级的未定义字段均拒绝。"""
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class SqlAlarmParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HornAlarmParams(SqlAlarmParams):
    horn_id: int | None = Field(None, gt=0)
    horn_event_id: int | None = Field(None, ge=0)


class WechatAlarmParams(SqlAlarmParams):
    user: str = ""


Params = TypeVar("Params", bound=BaseModel)


class AlarmChannel(BaseModel, Generic[Params]):
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    parm: Params = Field(default_factory=dict, validate_default=True)


class AlarmConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sql: AlarmChannel[SqlAlarmParams] = Field(
        default_factory=lambda: AlarmChannel(parm=SqlAlarmParams()))
    horn: AlarmChannel[HornAlarmParams] = Field(
        default_factory=lambda: AlarmChannel(parm=HornAlarmParams()))
    wechat: AlarmChannel[WechatAlarmParams] = Field(
        default_factory=lambda: AlarmChannel(parm=WechatAlarmParams()))
