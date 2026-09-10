"""features/detect_logistics_single_person/schema.py"""
from typing import List

from pydantic import BaseModel, ConfigDict, Field

from AiVision.features._base.roi import NormalizedRoi

class LogisticsSinglePersonValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    CONF_THRESHOLD: float = Field(0.3, ge=0, le=1)
    IOU_THR: float = Field(0.3, ge=0, le=1)
    roi_pos: NormalizedRoi = Field(default_factory=list)
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

class LogisticsSinglePersonAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)

class LogisticsSinglePersonConfigSchema(BaseModel):
    enable: bool = False
    value: LogisticsSinglePersonValueSchema = Field(default_factory=LogisticsSinglePersonValueSchema)
    alarm: LogisticsSinglePersonAlarmSchema = Field(default_factory=LogisticsSinglePersonAlarmSchema)
