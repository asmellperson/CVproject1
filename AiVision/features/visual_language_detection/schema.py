"""指令驱动智慧安防的摄像头参数与 API 数据契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from AiVision.features._shared import defaults
from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared.roi import NormalizedRoi

FEATURE_NAME = "visual_language_detection"


class VisualLanguageValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, str_strip_whitespace=True)

    cap_interval: float = Field(1.0, ge=0.1, le=300)
    roi_pos: NormalizedRoi = Field(default_factory=list)
    alarm_interval: float = Field(defaults.ALARM_INTERVAL, gt=0)
    jpeg_quality: int = Field(80, ge=1, le=100)
    max_image_width: int = Field(960, ge=160, le=3840)
    max_tokens: int = Field(256, ge=1, le=8192)
    temperature: float = Field(0.8, ge=0, le=2)
    top_p: float = Field(0.9, gt=0, le=1)
    observation_prompt: str = Field(
        "请持续观察当前视频，用中文简洁描述值得关注的人员活动、物品变化和异常情况；没有值得报告的变化时保持静默。",
        min_length=1, max_length=8000,
    )


class VisualLanguageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    value: VisualLanguageValue = Field(default_factory=VisualLanguageValue)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)


class VideoQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=2000)


class VideoAnswer(BaseModel):
    text: str | None
    latency_seconds: float
    captured_at: datetime


class VisualLanguageStatus(BaseModel):
    processed_frames: int = 0
    latest_result: str | None = None
    latest_result_at: datetime | None = None
    latency_seconds: float | None = None
    error: str | None = None


class VisualLanguageEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: Literal["observation", "question", "error"]
    text: str
    question: str | None
    captured_at: datetime
    latency_seconds: float | None


class VisualLanguageHistory(BaseModel):
    items: list[VisualLanguageEvent]
