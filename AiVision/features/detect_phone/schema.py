"""features/detect_phone/schema.py"""
from typing import List
from pydantic import BaseModel, Field, field_validator


class PhoneValueSchema(BaseModel):
    roi_pos: List[List[List[int]]] = Field(default_factory=list)
    CONF_THRESHOLD: float = Field(0.7, ge=0, le=1)
    IOU_THR: float = Field(0.5, ge=0, le=1)
    cap_interval: float = Field(0.1, gt=0)
    alarm_interval: float = Field(5.0, gt=0)
    MIN_CONFIRM_SECONDS: float = Field(1.2, ge=0)
    MIN_CONSECUTIVE_HITS: int = Field(3, ge=1)
    MAX_MISSED_SECONDS: float = Field(0.6, ge=0)
    TRACK_TTL_SECONDS: float = Field(2.0, gt=0)
    TRACK_IOU_THRESHOLD: float = Field(0.2, ge=0, le=1)
    PERSON_CONF_THRESHOLD: float = Field(0.3, ge=0, le=1)
    PERSON_IOU_THR: float = Field(0.3, ge=0, le=1)
    REQUIRE_PERSON_ASSOCIATION: bool = True
    PERSON_EXPAND_RATIO: float = Field(0.18, ge=0, le=1)
    HAND_REGION_MAX_Y_RATIO: float = Field(0.85, ge=0, le=1.5)
    MIN_PERSON_PHONE_OVERLAP: float = Field(0.08, ge=0, le=1)

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
