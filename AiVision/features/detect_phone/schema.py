"""features/detect_phone/schema.py"""
from typing import List
from pydantic import BaseModel, Field, field_validator


class PhoneValueSchema(BaseModel):
    roi_pos: List[List[List[int]]] = Field(default_factory=list)
    CONF_THRESHOLD: float = Field(0.7, ge=0, le=1)
    IOU_THR: float = Field(0.5, ge=0, le=1)
    cap_interval: float = Field(0.1, gt=0)
    alarm_interval: float = Field(5.0, gt=0)

    @field_validator("roi_pos", mode="before")
    @classmethod
    def _normalize_roi(cls, v):
        if not isinstance(v, list) or not v:
            return v
        first = v[0]
        if isinstance(first, list) and first and not isinstance(first[0], list):
            return [v]
        return v


class _AlarmChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=dict)


class _WechatChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=lambda: {"user": ""})


class PhoneAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)


class PhoneConfigSchema(BaseModel):
    enable: bool = False
    value: PhoneValueSchema = Field(default_factory=PhoneValueSchema)
    alarm: PhoneAlarmSchema = Field(default_factory=PhoneAlarmSchema)
