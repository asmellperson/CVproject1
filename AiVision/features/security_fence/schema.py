"""围栏配置和监控契约；人员资料共享，准入授权按摄像头隔离。"""
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared.roi import NormalizedRoi

FEATURE = "security_fence"
FORBIDDEN_ALARM = 15
UNAUTHORIZED_ALARM = 16
STALE_SECONDS = 5.0
ClockTime = Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]


class FenceValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    roi_pos: NormalizedRoi = Field(default_factory=list)
    forbidden_start: ClockTime = "22:00"
    forbidden_end: ClockTime = "08:00"
    timezone: str = "Asia/Shanghai"
    allowed_person_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=10000)
    cap_interval: float = Field(0.2, ge=0.1, le=1.0)
    alarm_interval: float = Field(30.0, ge=1)
    threshold: float = Field(0.5, gt=0, le=1)
    detection_threshold: float = Field(0.7, gt=0, le=1)
    similarity_threshold: float = Field(0.5, gt=0, le=1)
    unknown_similarity_threshold: float = Field(0.3, ge=0, lt=1)
    confirmation_frames: int = Field(3, ge=2, le=10)
    min_face_size: int = Field(80, ge=32, le=512)
    min_face_sharpness: float = Field(60.0, ge=0)
    max_face_asymmetry: float = Field(0.35, gt=0, le=1)
    tracking_overlap_threshold: float = Field(0.2, gt=0, le=1)
    tracking_gap_seconds: float = Field(2.0, ge=1, le=5)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("请选择有效的 IANA 时区") from exc
        return value

    @field_validator("allowed_person_ids")
    @classmethod
    def unique_people(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("白名单人员不能重复")
        return sorted(value)

    @model_validator(mode="after")
    def separate_thresholds(self):
        if self.unknown_similarity_threshold >= self.similarity_threshold:
            raise ValueError("未匹配判定阈值必须小于身份匹配阈值")
        return self


class FenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    value: FenceValue = Field(default_factory=FenceValue)
    alarm: AlarmConfigSchema = Field(default_factory=lambda: AlarmConfigSchema.model_validate({"sql": {"enable": True}}))


class FencePerson(BaseModel):
    track_id: int
    bbox: list[float]
    in_roi: bool
    identity: Literal["pending", "allowed", "unauthorized"]
    person_id: int | None = None
    person_name: str | None = None
    similarity: float | None = None
    alarm: bool = False
    reason: Literal["forbidden_time", "unauthorized", "unknown_face"] | None = None


class FenceStatus(BaseModel):
    camera_id: int
    camera_key: str
    camera_name: str
    department: str
    online: bool
    state: Literal["disabled", "offline", "waiting", "stale", "error", "ready"]
    mode: Literal["forbidden", "whitelist"]
    timezone: str
    count: int | None = None
    pending_count: int | None = None
    alarm: bool | None = None
    persons: list[FencePerson] = Field(default_factory=list)
    frame_width: int | None = None
    frame_height: int | None = None
    updated_at: str | None = None
    error: str | None = None


class PersonChoice(BaseModel):
    id: int
    person_name: str | None
    job_no: str | None
    is_active: bool


class PersonChoices(BaseModel):
    total: int
    items: list[PersonChoice]


class FenceAlarm(BaseModel):
    id: str
    camera_key: str | None
    camera_name: str
    department: str
    reason: str
    created_at: str
    person: FencePerson | None
    image_url: str | None


class FenceHistory(BaseModel):
    total: int
    by_reason: dict[str, int]
    items: list[FenceAlarm]
