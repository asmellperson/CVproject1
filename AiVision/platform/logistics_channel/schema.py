"""物流通道 API 的 Pydantic DTO。"""
from __future__ import annotations

from datetime import datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constants import DEFAULT_DETECTION_END, DEFAULT_DETECTION_START, MAX_CAMERAS_PER_CHANNEL


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
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    horn_id: int | None = Field(default=None, gt=0)
    horn_event_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _validate_enabled_horn(self) -> "LogisticsChannelAlarmChannel":
        if self.enabled and (self.horn_id is None or self.horn_event_id is None):
            raise ValueError("启用喇叭告警时必须提供 horn_id 和 horn_event_id")
        return self


class LogisticsChannelWechatChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    user: str = ""


class LogisticsChannelAlarm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql_enable: bool = False
    horn: LogisticsChannelAlarmChannel = Field(default_factory=LogisticsChannelAlarmChannel)
    wechat: LogisticsChannelWechatChannel = Field(default_factory=LogisticsChannelWechatChannel)


class LogisticsChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)


class LogisticsChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    sort_order: int | None = None


class LogisticsChannelConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    detection_start: time = DEFAULT_DETECTION_START
    detection_end: time = DEFAULT_DETECTION_END
    empty_grace_seconds: float = Field(default=2.0, ge=0)
    multi_grace_seconds: float = Field(default=1.0, ge=0)
    alarm_interval: float = Field(default=5.0, gt=0)
    alarm: LogisticsChannelAlarm = Field(default_factory=LogisticsChannelAlarm)

    @model_validator(mode="after")
    def _validate_detection_window(self) -> "LogisticsChannelConfigUpdate":
        if (
            self.detection_start.tzinfo is not None
            or self.detection_start.utcoffset() is not None
            or self.detection_end.tzinfo is not None
            or self.detection_end.utcoffset() is not None
        ):
            raise ValueError("detection_start 和 detection_end 不支持时区")
        if self.detection_start >= self.detection_end:
            raise ValueError("detection_start 必须早于 detection_end")
        return self


class LogisticsChannelMemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
        if has_existing_camera:
            new_camera_fields = {"name", "url", "fps", "max_restart", "department", "shm_name"}
            supplied = new_camera_fields & self.model_fields_set
            if supplied:
                raise ValueError("camera_id 模式不得提供新摄像头字段")
        if has_new_camera and (self.name is None or self.url is None):
            raise ValueError("新摄像头必须同时提供 name 和 url")
        return self


class LogisticsChannelMemberOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_ids: list[Annotated[int, Field(gt=0)]] = Field(
        min_length=1,
        max_length=MAX_CAMERAS_PER_CHANNEL,
    )

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

    @model_validator(mode="before")
    @classmethod
    def _adapt_channel_orm(cls, value: Any) -> Any:
        if isinstance(value, dict) or not hasattr(value, "detection_start"):
            return value
        return {
            "enabled": value.enabled,
            "detection_start": value.detection_start,
            "detection_end": value.detection_end,
            "empty_grace_seconds": value.empty_grace_seconds,
            "multi_grace_seconds": value.multi_grace_seconds,
            "alarm_interval": value.alarm_interval,
            "alarm": {
                "sql_enable": value.sql_enable,
                "horn": {
                    "enabled": value.horn_enable,
                    "horn_id": value.horn_id,
                    "horn_event_id": value.horn_event_id,
                },
                "wechat": {
                    "enabled": value.wechat_enable,
                    "user": value.wechat_user or "",
                },
            },
        }


class LogisticsChannelStatusResponse(BaseModel):
    """运行时状态响应；调用方传入已组装的 dict，不接受 ORM 对象。"""
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

    @model_validator(mode="before")
    @classmethod
    def _adapt_channel_orm(cls, value: Any) -> Any:
        if isinstance(value, dict) or not hasattr(value, "feature_name"):
            return value
        return {
            "id": value.id,
            "name": value.name,
            "feature_name": value.feature_name,
            "enabled": value.enabled,
            "sort_order": value.sort_order,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
            "config": value,
            "members": value.cameras,
            "status": getattr(value, "status", None),
        }
