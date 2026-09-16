"""身份识别配置和查询返回模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from AiVision.features._shared import defaults
from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared.roi import NormalizedRoi
from AiVision.features.face_recognition.library.constants import (
    DEFAULT_CAPTURE_INTERVAL, DEFAULT_DETECTION_THRESHOLD, DEFAULT_RECORD_COOLDOWN_SECONDS,
    DEFAULT_SIMILARITY_THRESHOLD,
)


class FaceRecognitionValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roi_pos: NormalizedRoi = Field(default_factory=list)
    cap_interval: float = Field(DEFAULT_CAPTURE_INTERVAL, ge=0.1, le=1.0)
    detection_threshold: float = Field(DEFAULT_DETECTION_THRESHOLD, ge=0, le=1)
    similarity_threshold: float = Field(DEFAULT_SIMILARITY_THRESHOLD, ge=0, le=1)
    record_enabled: bool = True
    record_cooldown_seconds: float = Field(DEFAULT_RECORD_COOLDOWN_SECONDS, ge=1)
    alarm_interval: float = Field(defaults.ALARM_INTERVAL, gt=0)


class FaceRecognitionConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enable: bool = False
    value: FaceRecognitionValue = Field(default_factory=FaceRecognitionValue)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)


class FacePersonItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    hik_source: Literal["one", "two"]
    hik_person_id: str
    person_name: str | None
    job_no: str | None
    person_code: str | None
    org_index_code: str | None
    server_index_code: str | None
    pic_uri: str | None
    is_active: bool
    is_allowed: bool
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime


class FacePersonPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[FacePersonItem]


class FacePersonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    is_allowed: bool


class RecognitionRecordItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    camera_id: int
    person_id: int | None
    person_name: str
    similarity: float
    image_path: str | None
    recognized_at: datetime

    @computed_field
    @property
    def image_url(self) -> str | None:
        return f"/api/face-recognition/records/{self.id}/image" if self.image_path else None


class RecognitionRecordPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[RecognitionRecordItem]
