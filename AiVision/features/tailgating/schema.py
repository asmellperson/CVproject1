"""非法闯闸的配置、检测结果与平台状态契约。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared.roi import NormalizedLine, NormalizedRoi

FEATURE = "tailgating"
ALARM_TYPE = 17
STATUS_STALE_SECONDS = 2.0
LINE_MARGIN_RATIO = 0.005


class TailgatingValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    roi_pos: NormalizedRoi = Field(default_factory=list)
    line_points: NormalizedLine = Field(default_factory=list)
    direction: int = Field(1, ge=-1, le=1)
    overlap_seconds: float = Field(0.3, ge=0.1, le=5)
    crossing_window_seconds: float = Field(3.0, ge=0.5, le=10)
    max_frame_gap_seconds: float = Field(1.0, ge=0.2, le=3)
    foot_ratio: float = Field(0.93, ge=0.5, le=1)
    threshold: float = Field(
        0.5, ge=0.01, le=1, title="人体检测置信度",
        description="人体检测结果的置信度阈值，也称人体置信度、人体置信度配置值；低于该值的目标不参与通行判定",
    )
    cap_interval: float = Field(0.1, ge=0.05, le=0.5)
    alarm_interval: float = Field(30.0, ge=1)

    @model_validator(mode="after")
    def valid_intervals(self):
        if self.max_frame_gap_seconds <= self.cap_interval:
            raise ValueError("允许采样间隔必须大于检测间隔")
        if self.crossing_window_seconds < self.overlap_seconds:
            raise ValueError("通行关联窗口不能小于共同出现确认时间")
        return self

    @property
    def configured(self) -> bool:
        return bool(self.roi_pos and self.line_points)


class TailgatingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    value: TailgatingValue = Field(default_factory=TailgatingValue)
    alarm: AlarmConfigSchema = Field(default_factory=lambda: AlarmConfigSchema.model_validate({"sql": {"enable": True}}))


class TailgatingPerson(BaseModel):
    track_id: int
    bbox: list[float]
    in_roi: bool
    direction: int | None


class TailgatingEvent(BaseModel):
    id: str
    track_ids: list[int]
    direction: int
    overlap_seconds: float


class TailgatingStatus(BaseModel):
    camera_key: str
    camera_name: str
    department: str
    online: bool
    state: Literal["disabled", "offline", "waiting", "stale", "error", "ready"]
    reason: str
    count: int | None = None
    alarm: bool = False
    persons: list[TailgatingPerson] = Field(default_factory=list)
    events: list[TailgatingEvent] = Field(default_factory=list)
    sample_interval_seconds: float | None = None
    updated_at: str | None = None
    valid_for_seconds: float = Field(0.0, ge=0, le=STATUS_STALE_SECONDS)
    error: str | None = None


class TailgatingAlarm(BaseModel):
    """外部报警沿用通行事件字段，不暴露服务器证据路径。"""

    id: str
    camera_key: str | None
    camera_name: str
    department: str
    reason: str
    created_at: str
    tailgating: TailgatingEvent | None
    image_url: str | None


class TailgatingHistory(BaseModel):
    total: int
    items: list[TailgatingAlarm]
