"""features/detect_door/schema.py"""
from typing import List
from pydantic import BaseModel, Field, field_validator


class DoorValueSchema(BaseModel):
    roi_pos: List[List[List[int]]] = Field(default_factory=list)
    threshold: float = Field(0.5, ge=0)
    blur_kernel: int = Field(5, ge=1)
    diff_threshold: int = Field(5, ge=0)
    diff_threshold_env: int = Field(10, ge=0)
    env_threshold: float = Field(10.0, ge=0)
    first_alarm: int = Field(60, ge=0)
    stable_confirm_seconds: float = Field(1.0, ge=0)
    stable_confirm_hits: int = Field(3, ge=1)
    background_update_alpha: float = Field(0.05, ge=0, le=1)
    global_motion_threshold: float = Field(0.22, ge=0)
    min_local_change_ratio: float = Field(0.01, ge=0, le=1)
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


class DoorAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)


class DoorConfigSchema(BaseModel):
    enable: bool = False
    value: DoorValueSchema = Field(default_factory=DoorValueSchema)
    alarm: DoorAlarmSchema = Field(default_factory=DoorAlarmSchema)
