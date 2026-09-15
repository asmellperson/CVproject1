"""身份识别配置和查询返回模型。"""
from datetime import datetime
from typing import Generic, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from AiVision.features._base.alarm_schema import Params, SqlAlarmParams, HornAlarmParams, WechatAlarmParams
from AiVision.features._base.roi import NormalizedRoi
from AiVision.features.recognize_face.library.constants import (
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
    alarm_interval: float = Field(5.0, gt=0)


class DisabledAlarmChannel(BaseModel, Generic[Params]):
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: Literal[False] = False
    parm: Params = Field(default_factory=dict, validate_default=True)


class DisabledRecognitionAlarm(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sql: DisabledAlarmChannel[SqlAlarmParams] = Field(
        default_factory=lambda: DisabledAlarmChannel(parm=SqlAlarmParams()))
    horn: DisabledAlarmChannel[HornAlarmParams] = Field(
        default_factory=lambda: DisabledAlarmChannel(parm=HornAlarmParams()))
    wechat: DisabledAlarmChannel[WechatAlarmParams] = Field(
        default_factory=lambda: DisabledAlarmChannel(parm=WechatAlarmParams()))


class FaceRecognitionConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enable: bool = False
    value: FaceRecognitionValue = Field(default_factory=FaceRecognitionValue)
    alarm: DisabledRecognitionAlarm = Field(default_factory=DisabledRecognitionAlarm)


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
