"""features/person_dwell/schema.py"""
from typing import List
from pydantic import BaseModel, ConfigDict, Field, field_validator

from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared import defaults
from AiVision.features._shared.roi import NormalizedRoi

class HumanValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    CONF_THRESHOLD: float = Field(0.3, ge=0, le=1)
    DETECTION_IOU_THR: float = Field(defaults.DETECTION_IOU_THR, ge=0, le=1)  # 模型推理 IoU
    TRACK_IOU_THR: float = Field(defaults.TRACK_IOU_THR, ge=0, le=1)  # 跨帧跟踪 IoU
    MAX_LOST: int = Field(defaults.MAX_LOST, ge=0)
    MAX_TIME: float = Field(defaults.MAX_TIME, ge=0)
    roi_pos: NormalizedRoi = Field(default_factory=list)
    MIN_BOX_AREA: int = Field(0, ge=0)
    ASPECT_RATIO_RANGE: List[float] = Field(default_factory=lambda: [0.0, 10.0], min_length=2, max_length=2)
    CENTER_DIST_THR: float = Field(defaults.CENTER_DIST_THR, ge=0)
    AREA_RATIO_THR: float = Field(defaults.AREA_RATIO_THR, ge=0, le=1)
    MATCH_SCORE_THR: float = Field(defaults.MATCH_SCORE_THR, ge=0, le=1)
    TRACK_SMOOTH_ALPHA: float = Field(defaults.TRACK_SMOOTH_ALPHA, ge=0, le=1)
    cap_interval: float = Field(defaults.CAP_INTERVAL, gt=0)
    alarm_interval: float = Field(defaults.ALARM_INTERVAL, gt=0)

    @field_validator("ASPECT_RATIO_RANGE")
    @classmethod
    def validate_aspect_range(cls, value):
        if not 0 <= value[0] <= value[1]:
            raise ValueError("宽高比范围必须满足 0 <= 下限 <= 上限")
        return value

class HumanConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    value: HumanValueSchema = Field(default_factory=HumanValueSchema)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)
