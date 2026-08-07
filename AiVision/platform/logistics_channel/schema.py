"""物流通道 API 的 Pydantic DTO。"""
from __future__ import annotations

from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constants import DEFAULT_DETECTION_END, DEFAULT_DETECTION_START


LogisticsFeatureName = Literal[
    "detect_logistics_single_person",
    "detect_logistics_single_person_electronics_electrician",
    "detect_logistics_single_person_electrical_components",
    "detect_logistics_single_person_precious_metal_recycling",
]
LogisticsChannelStatusReason = Literal[
    "normal", "empty", "multiple", "unknown", "unconfigured", "inactive",
]


class LogisticsChannelAlarmChannel(BaseModel):
    enabled: bool = False
    horn_id: int | None = None
    horn_event_id: int | None = None


class LogisticsChannelWechatChannel(BaseModel):
    enabled: bool = False
    user: str = ""


class LogisticsChannelAlarm(BaseModel):
    sql_enable: bool = False
    horn: LogisticsChannelAlarmChannel = Field(default_factory=LogisticsChannelAlarmChannel)
    wechat: LogisticsChannelWechatChannel = Field(default_factory=LogisticsChannelWechatChannel)


class LogisticsChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class LogisticsChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    sort_order: int | None = None


class LogisticsChannelConfigUpdate(BaseModel):
    enabled: bool = True
    detection_start: time = DEFAULT_DETECTION_START
    detection_end: time = DEFAULT_DETECTION_END
    empty_grace_seconds: float = Field(default=2.0, ge=0)
    multi_grace_seconds: float = Field(default=1.0, ge=0)
    alarm_interval: float = Field(default=5.0, gt=0)
    alarm: LogisticsChannelAlarm = Field(default_factory=LogisticsChannelAlarm)

    @model_validator(mode="after")
    def _validate_detection_window(self) -> "LogisticsChannelConfigUpdate":
        if self.detection_start >= self.detection_end:
            raise ValueError("detection_start 必须早于 detection_end")
        return self


class LogisticsChannelMemberCreate(BaseModel):
    camera_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    fps: int = Field(default=5, gt=0)
    max_restart: int = Field(default=10, ge=0)
    department: str | None = Field(default=None, max_length=100)
    shm_name: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_camera_input_mode(self) -> "LogisticsChannelMemberCreate":
        has_existing_camera = self.camera_id is not None
        has_new_camera = self.name is not None or self.url is not None
        if has_existing_camera == has_new_camera:
            raise ValueError("必须且只能提供 camera_id 或 name 和 url")
        if has_new_camera and (self.name is None or self.url is None):
            raise ValueError("新摄像头必须同时提供 name 和 url")
        return self


class LogisticsChannelMemberOrder(BaseModel):
    camera_ids: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_unique_camera_ids(self) -> "LogisticsChannelMemberOrder":
        if len(set(self.camera_ids)) != len(self.camera_ids):
            raise ValueError("camera_ids 不可重复")
        return self


class LogisticsChannelMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    camera_id: int
    enabled: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LogisticsChannelConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    detection_start: time
    detection_end: time
    empty_grace_seconds: float
    multi_grace_seconds: float
    alarm_interval: float
    alarm: LogisticsChannelAlarm


class LogisticsChannelStatusResponse(BaseModel):
    reason: LogisticsChannelStatusReason
    online: bool | None = None
    person_count: int | None = None
    stale: bool = False
    stale_reason: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    updated_at: datetime | None = None


class LogisticsChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    feature_name: LogisticsFeatureName
    enabled: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LogisticsChannelListResponse(BaseModel):
    items: list[LogisticsChannelResponse]


class LogisticsChannelDetailResponse(LogisticsChannelResponse):
    config: LogisticsChannelConfigResponse
    members: list[LogisticsChannelMemberResponse] = Field(default_factory=list)
    status: LogisticsChannelStatusResponse | None = None
