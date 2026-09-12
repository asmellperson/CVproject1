"""身份识别配置和查询返回模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from AiVision.features._base.roi import NormalizedRoi
from AiVision.platform.face_library.constants import (
    DEFAULT_CAPTURE_INTERVAL, DEFAULT_RECORD_COOLDOWN_SECONDS, DEFAULT_SIMILARITY_THRESHOLD,
)


class FaceRecognitionValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roi_pos: NormalizedRoi = Field(default_factory=list)
    cap_interval: float = Field(DEFAULT_CAPTURE_INTERVAL, ge=0.1, le=1.0)
    similarity_threshold: float = Field(DEFAULT_SIMILARITY_THRESHOLD, ge=0, le=1)
    record_enabled: bool = True
    record_cooldown_seconds: float = Field(DEFAULT_RECORD_COOLDOWN_SECONDS, ge=1)
    alarm_interval: float = Field(5.0, gt=0)


class DisabledAlarmChannel(BaseModel):
    enable: Literal[False] = False
    parm: dict = Field(default_factory=dict)


class DisabledRecognitionAlarm(BaseModel):
    sql: DisabledAlarmChannel = Field(default_factory=DisabledAlarmChannel)
    horn: DisabledAlarmChannel = Field(default_factory=DisabledAlarmChannel)
    wechat: DisabledAlarmChannel = Field(default_factory=DisabledAlarmChannel)


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
    recognized_at: datetime


class RecognitionRecordPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[RecognitionRecordItem]
