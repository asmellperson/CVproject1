"""features/detect_logistics_single_person_precious_metal_recycling/schema.py"""
from typing import List

from pydantic import BaseModel, Field


class LogisticsSinglePersonPreciousMetalRecyclingValueSchema(BaseModel):
    CONF_THRESHOLD: float = Field(0.3, ge=0, le=1)
    IOU_THR: float = Field(0.3, ge=0, le=1)
    roi_pos: list = Field(default_factory=list)
    region: List[int] = Field(default_factory=list)
    MIN_BOX_AREA: int = Field(0, ge=0)
    ASPECT_RATIO_RANGE: List[float] = Field(default_factory=lambda: [0.0, 10.0])
    empty_grace_seconds: float = Field(2.0, ge=0)
    multi_grace_seconds: float = Field(1.0, ge=0)
    cap_interval: float = Field(0.2, gt=0)
    alarm_interval: float = Field(5.0, gt=0)


class _AlarmChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=dict)


class _WechatChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=lambda: {"user": ""})


class LogisticsSinglePersonPreciousMetalRecyclingAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)


class LogisticsSinglePersonPreciousMetalRecyclingConfigSchema(BaseModel):
    enable: bool = False
    value: LogisticsSinglePersonPreciousMetalRecyclingValueSchema = Field(default_factory=LogisticsSinglePersonPreciousMetalRecyclingValueSchema)
    alarm: LogisticsSinglePersonPreciousMetalRecyclingAlarmSchema = Field(default_factory=LogisticsSinglePersonPreciousMetalRecyclingAlarmSchema)
