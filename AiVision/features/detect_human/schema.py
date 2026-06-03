"""features/detect_human/schema.py"""
from typing import List
from pydantic import BaseModel, Field, field_validator


class HumanValueSchema(BaseModel):
    CONF_THRESHOLD: float = Field(0.3, ge=0, le=1)
    IOU_THR: float = Field(0.3, ge=0, le=1)
    MAX_LOST: int = Field(5, ge=0)
    MAX_TIME: float = Field(10.0, ge=0)
    roi_pos: list = Field(default_factory=lambda: [100, 100, 500, 500])
    region: List[int] = Field(default_factory=lambda: [100, 100, 500, 500])
    MIN_BOX_AREA: int = Field(0, ge=0)
    ASPECT_RATIO_RANGE: List[float] = Field(default_factory=lambda: [0.0, 10.0])
    CENTER_DIST_THR: float = Field(0.65, ge=0)
    AREA_RATIO_THR: float = Field(0.55, ge=0, le=1)
    MATCH_SCORE_THR: float = Field(0.35, ge=0, le=1)
    TRACK_SMOOTH_ALPHA: float = Field(0.7, ge=0, le=1)
    cap_interval: float = Field(0.1, gt=0)
    alarm_interval: float = Field(5.0, gt=0)


class _AlarmChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=dict)


class _WechatChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=lambda: {"user": ""})


class HumanAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)


class HumanConfigSchema(BaseModel):
    enable: bool = False
    value: HumanValueSchema = Field(default_factory=HumanValueSchema)
    alarm: HumanAlarmSchema = Field(default_factory=HumanAlarmSchema)
