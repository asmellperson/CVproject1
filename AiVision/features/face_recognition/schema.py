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
    """身份识别阈值、采样周期与记录冷却设置。"""
    model_config = ConfigDict(extra="forbid")
    roi_pos: NormalizedRoi = Field(default_factory=list)
    cap_interval: float = Field(DEFAULT_CAPTURE_INTERVAL, ge=0.1, le=1.0)
    detection_threshold: float = Field(DEFAULT_DETECTION_THRESHOLD, ge=0, le=1)
    similarity_threshold: float = Field(DEFAULT_SIMILARITY_THRESHOLD, ge=0, le=1)
    record_enabled: bool = True
    record_cooldown_seconds: float = Field(DEFAULT_RECORD_COOLDOWN_SECONDS, ge=1)
    alarm_interval: float = Field(defaults.ALARM_INTERVAL, gt=0)


class FaceRecognitionConfigSchema(BaseModel):
    """组合身份识别开关、算法参数与告警通道配置。"""
    model_config = ConfigDict(extra="forbid")
    enable: bool = False
    value: FaceRecognitionValue = Field(default_factory=FaceRecognitionValue)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)


class FacePersonItem(BaseModel):
    """人员库对外信息，区分来源同步状态与本地授权状态。"""
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
    """人员检索结果及分页信息。"""
    total: int
    page: int
    page_size: int
    items: list[FacePersonItem]


class FacePersonUpdate(BaseModel):
    """仅允许修改人员的本地通行授权，不覆盖来源同步资料。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    is_allowed: bool


class RecognitionRecordItem(BaseModel):
    """识别记录的历史快照及受接口控制的截图入口。"""
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
        """有截图引用时生成按记录 ID 查询的地址，不直接拼接磁盘路径。"""
        return f"/api/face-recognition/records/{self.id}/image" if self.image_path else None


class RecognitionRecordPage(BaseModel):
    """识别记录分页结果，包含总数与当前页数据。"""
    total: int
    page: int
    page_size: int
    items: list[RecognitionRecordItem]
