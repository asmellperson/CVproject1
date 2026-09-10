"""features/blocks/schema.py — 区域入侵检测前端入参校验"""
from typing import List
from pydantic import BaseModel, ConfigDict, Field, field_validator

from AiVision.features._base.roi import NormalizedRoi, NormalizedLine

class BlocksValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roi_pos: NormalizedRoi = Field(default_factory=list)
    line_points: NormalizedLine = Field(default_factory=list)
    alarm_side: int = Field(1)
    foot_ratio: float = Field(0.93, ge=0.0, le=1.0)
    threshold: float = Field(0.1, ge=0)
    blur_kernel: int = Field(5, ge=1)
    diff_threshold: int = Field(10, ge=0)
    diff_threshold_env: int = Field(10, ge=0)
    env_threshold: float = Field(0.5, ge=0)
    cap_interval: float = Field(0.1, gt=0)
    alarm_interval: float = Field(5.0, gt=0)

    @field_validator("alarm_side", mode="before")
    @classmethod
    def _normalize_alarm_side(cls, v):
        return -1 if int(v or 1) < 0 else 1

class _AlarmChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=dict)

class _WechatChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=lambda: {"user": ""})


class BlocksAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)

class BlocksConfigSchema(BaseModel):
    """blocks 完整配置 — 前端 PUT 时的请求体格式"""
    enable: bool = False
    value: BlocksValueSchema = Field(default_factory=BlocksValueSchema)
    alarm: BlocksAlarmSchema = Field(default_factory=BlocksAlarmSchema)
