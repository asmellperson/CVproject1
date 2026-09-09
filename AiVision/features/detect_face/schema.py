"""features/detect_face/schema.py"""
from typing import List
from pydantic import BaseModel, Field, field_validator

class FaceValueSchema(BaseModel):
    roi_pos: List[List[List[int]]] = Field(default_factory=list)
    FACE_SCORE_THR: float = Field(0.6, ge=0, le=1)
    YAW_THRESHOLD: List[float] = Field(default_factory=lambda: [0.0, 0.3])
    MAX_TIME: float = Field(10.0, ge=0)
    IOU_THR: float = Field(0.3, ge=0, le=1)
    MAX_LOST: int = Field(5, ge=0)
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

class FaceAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)

class FaceConfigSchema(BaseModel):
    enable: bool = False
    value: FaceValueSchema = Field(default_factory=FaceValueSchema)
    alarm: FaceAlarmSchema = Field(default_factory=FaceAlarmSchema)
