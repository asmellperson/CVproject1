"""人员逗留参数校验，包括人体框宽高比范围与跨帧跟踪稳定性参数。"""
from typing import List
from pydantic import BaseModel, ConfigDict, Field, field_validator

from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared import defaults
from AiVision.features._shared.roi import NormalizedRoi

FEATURE = "detect_human"
ALARM_TYPE = 5

class HumanValueSchema(BaseModel):
    """约束检测、跟踪和停留计时参数，拒绝非有限数值与未知字段。"""
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
        """保证宽高比下限非负且不大于上限，避免所有候选框被错误过滤。"""
        if not 0 <= value[0] <= value[1]:
            raise ValueError("宽高比范围必须满足 0 <= 下限 <= 上限")
        return value

class HumanConfigSchema(BaseModel):
    """包装人员逗留的功能开关、参数和告警配置。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    value: HumanValueSchema = Field(default_factory=HumanValueSchema)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)


class HumanDwellAlarm(BaseModel):
    """外部人员逗留报警字段，不暴露服务器图片或录像路径。"""

    id: str
    feature_name: str
    violation_type: int
    event_type: str
    event_label: str
    camera_key: str | None
    camera_name: str
    department: str
    reason: str
    created_at: str
    image_url: str | None


class HumanDwellHistory(BaseModel):
    total: int
    items: list[HumanDwellAlarm]
