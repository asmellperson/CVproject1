"""手机检测参数校验，统一约束模型阈值、人体关联比例和时间窗口。"""
from pydantic import BaseModel, ConfigDict, Field

from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared import defaults
from AiVision.features._shared.roi import NormalizedRoi

class PhoneValueSchema(BaseModel):
    """手机候选筛选与持续确认参数，时间窗口均以秒计。"""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    roi_pos: NormalizedRoi = Field(default_factory=list)
    CONF_THRESHOLD: float = Field(0.7, ge=0, le=1)
    IOU_THR: float = Field(0.5, ge=0, le=1)
    cap_interval: float = Field(defaults.CAP_INTERVAL, gt=0)
    alarm_interval: float = Field(defaults.ALARM_INTERVAL, gt=0)
    MIN_CONFIRM_SECONDS: float = Field(1.2, ge=0)
    MIN_CONSECUTIVE_HITS: int = Field(defaults.MIN_CONSECUTIVE_HITS, ge=1)
    MAX_MISSED_SECONDS: float = Field(0.6, ge=0)
    TRACK_TTL_SECONDS: float = Field(2.0, gt=0)
    TRACK_IOU_THRESHOLD: float = Field(0.2, ge=0, le=1)
    PERSON_CONF_THRESHOLD: float = Field(0.3, ge=0, le=1)
    PERSON_IOU_THR: float = Field(0.3, ge=0, le=1)
    REQUIRE_PERSON_ASSOCIATION: bool = True
    PERSON_EXPAND_RATIO: float = Field(0.18, ge=0, le=1)
    HAND_REGION_MAX_Y_RATIO: float = Field(0.85, ge=0, le=1.5)
    MIN_PERSON_PHONE_OVERLAP: float = Field(0.08, ge=0, le=1)


class PhoneConfigSchema(BaseModel):
    """手机检测开关、算法参数及各告警通道配置。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    value: PhoneValueSchema = Field(default_factory=PhoneValueSchema)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)
