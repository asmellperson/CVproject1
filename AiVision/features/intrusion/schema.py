"""features/intrusion/schema.py — 区域入侵检测前端入参校验"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared import defaults
from AiVision.features._shared.roi import NormalizedRoi, NormalizedLine

class BlocksValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    roi_pos: NormalizedRoi = Field(default_factory=list)
    line_points: NormalizedLine = Field(default_factory=list)
    alarm_side: Literal[-1, 1] = 1
    foot_ratio: float = Field(0.93, ge=0.0, le=1.0)
    threshold: float = Field(defaults.BLOCKS_CONFIDENCE, ge=0, le=1)  # 人体检测置信度
    cap_interval: float = Field(defaults.CAP_INTERVAL, gt=0)
    alarm_interval: float = Field(defaults.ALARM_INTERVAL, gt=0)

class BlocksConfigSchema(BaseModel):
    """blocks 完整配置 — 前端 PUT 时的请求体格式"""
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    value: BlocksValueSchema = Field(default_factory=BlocksValueSchema)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)
