"""物流摄像头参数、通道配置、成员请求和运行状态的数据合同。"""
from __future__ import annotations

from datetime import datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from AiVision.features._base.roi import NormalizedRoi
from AiVision.alarms.devices.binding import MAX_HORN_ID
from AiVision.features._base import defaults
from .constants import (
    DEFAULT_DETECTION_END, DEFAULT_DETECTION_START,
    DEFAULT_PERSON_CONFIDENCE_THRESHOLD, MAX_CAMERAS_PER_CHANNEL,
    DEFAULT_EMPTY_GRACE_SECONDS, DEFAULT_MULTI_GRACE_SECONDS,
    DEFAULT_MODEL_IOU, DEFAULT_MIN_BOX_AREA,
    DEFAULT_ASPECT_RATIO_RANGE, DEFAULT_CAP_INTERVAL,
)


class LogisticsSinglePersonValueSchema(BaseModel):
    """单路几何过滤和处理频率；告警及人体置信度由通道管理。"""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    IOU_THR: float = Field(DEFAULT_MODEL_IOU, ge=0, le=1)
    roi_pos: NormalizedRoi = Field(default_factory=list)
    MIN_BOX_AREA: int = Field(DEFAULT_MIN_BOX_AREA, ge=0, description="检测框最小面积，像素平方")
    ASPECT_RATIO_RANGE: list[Annotated[float, Field(ge=0)]] = Field(
        default_factory=lambda: list(DEFAULT_ASPECT_RATIO_RANGE), min_length=2, max_length=2,
        description="检测框宽/高的最小值和最大值",
    )
    cap_interval: float = Field(DEFAULT_CAP_INTERVAL, gt=0, description="画面处理间隔，秒")

    @model_validator(mode="after")
    def _ordered_aspect_range(self) -> LogisticsSinglePersonValueSchema:
        if self.ASPECT_RATIO_RANGE[0] > self.ASPECT_RATIO_RANGE[1]:
            raise ValueError("ASPECT_RATIO_RANGE 最小值不得大于最大值")
        return self


class LogisticsSinglePersonConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enable: bool = False
    value: LogisticsSinglePersonValueSchema = Field(default_factory=LogisticsSinglePersonValueSchema)


LogisticsFeatureName = Literal[
    "detect_logistics_single_person",
]
LogisticsChannelStatusReason = Literal[
    "normal", "empty", "multiple", "unknown", "unconfigured", "inactive",
]

class LogisticsChannelAlarmChannel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool = False
    horn_id: int | None = Field(default=None, gt=0, le=MAX_HORN_ID, strict=True)
    horn_event_id: int | None = Field(default=None, gt=0, le=MAX_HORN_ID, strict=True)

    @model_validator(mode="after")
    def _validate_enabled_horn(self) -> "LogisticsChannelAlarmChannel":
        if self.enabled and (self.horn_id is None or self.horn_event_id is None):
            raise ValueError("启用喇叭告警时必须提供 horn_id 和 horn_event_id")
        return self

class LogisticsChannelWechatChannel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool = False
    user: str = ""

class LogisticsChannelAlarm(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    sql_enable: bool = False
    horn: LogisticsChannelAlarmChannel = Field(default_factory=LogisticsChannelAlarmChannel)
    wechat: LogisticsChannelWechatChannel = Field(default_factory=LogisticsChannelWechatChannel)

class LogisticsChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=100)
    department: str = Field(min_length=1, max_length=100)

class LogisticsChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    sort_order: int | None = None

class LogisticsChannelConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    detection_start: time = DEFAULT_DETECTION_START
    detection_end: time = DEFAULT_DETECTION_END
    confidence_threshold: float = Field(
        default=DEFAULT_PERSON_CONFIDENCE_THRESHOLD,
        ge=0,
        le=1,
    )
    empty_grace_seconds: float = Field(default=DEFAULT_EMPTY_GRACE_SECONDS, ge=0)
    multi_grace_seconds: float = Field(default=DEFAULT_MULTI_GRACE_SECONDS, ge=0)
    alarm_interval: float = Field(default=defaults.ALARM_INTERVAL, gt=0)
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

class LogisticsChannelPatchRequest(LogisticsChannelUpdate):
    """通道元数据及检测配置的局部更新请求。"""
    config: LogisticsChannelConfigUpdate | None = None


class LogisticsChannelMemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    camera_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    fps: int = Field(default=5, gt=0)
    shm_name: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_camera_input_mode(self) -> "LogisticsChannelMemberCreate":
        has_existing_camera = self.camera_id is not None
        has_new_camera = self.name is not None or self.url is not None
        if has_existing_camera == has_new_camera:
            raise ValueError("必须且只能提供 camera_id 或 name 和 url")
        if has_existing_camera:
            new_camera_fields = {"name", "url", "fps", "shm_name"}
            supplied = new_camera_fields & self.model_fields_set
            if supplied:
                raise ValueError("camera_id 模式不得提供新摄像头字段")
        if has_new_camera and (self.name is None or self.url is None):
            raise ValueError("新摄像头必须同时提供 name 和 url")
        return self

class LogisticsChannelMemberOrder(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    camera_ids: list[Annotated[int, Field(gt=0)]] = Field(
        min_length=1,
        max_length=MAX_CAMERAS_PER_CHANNEL,
    )

    @model_validator(mode="after")
    def _validate_unique_camera_ids(self) -> "LogisticsChannelMemberOrder":
        if len(set(self.camera_ids)) != len(self.camera_ids):
            raise ValueError("camera_ids 不可重复")
        return self

class LogisticsChannelMemberEnabledUpdate(BaseModel):
    """启用或停用一个通道成员；成员本身不会被删除。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool

class LogisticsChannelMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    camera_id: int
    enabled: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

class LogisticsChannelConfigResponse(LogisticsChannelConfigUpdate):
    model_config = ConfigDict(from_attributes=True, extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def _adapt_channel_orm(cls, value: Any) -> Any:
        if isinstance(value, dict) or not hasattr(value, "detection_start"):
            return value
        return {
            "detection_start": value.detection_start,
            "detection_end": value.detection_end,
            "confidence_threshold": value.confidence_threshold,
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
    department: str
    enabled: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

class LogisticsChannelListResponse(BaseModel):
    items: list[LogisticsChannelResponse]

class LogisticsCameraInventoryMembership(BaseModel):
    feature_name: LogisticsFeatureName
    channel_id: int
    channel_name: str
    enabled: bool
    online: bool

class LogisticsCameraInventoryItem(BaseModel):
    camera_id: int
    name: str
    shm_name: str
    department: str | None = None
    enabled: bool
    online: bool
    memberships: list[LogisticsCameraInventoryMembership] = Field(default_factory=list)

class LogisticsCameraInventoryResponse(BaseModel):
    items: list[LogisticsCameraInventoryItem] = Field(default_factory=list)

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
            "department": value.department,
            "enabled": value.enabled,
            "sort_order": value.sort_order,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
            "config": value,
            "members": value.cameras,
            "status": getattr(value, "status", None),
        }

class LogisticsChannelCameraRuntimeStatus(BaseModel):
    """通道状态中单路摄像头的最新运行时快照。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    camera_id: int
    camera_name: str
    count: int | None = Field(default=None, ge=0)
    status: LogisticsChannelStatusReason
    online: bool
    updated_at: float | None = None
    stale_reason: str | None = None

class LogisticsChannelRuntimeStatusResponse(BaseModel):
    """通道聚合运行状态；时间戳沿用运行时 Unix 秒格式。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    feature_name: LogisticsFeatureName
    department: str
    channel_id: int
    channel_name: str
    reason: LogisticsChannelStatusReason
    alarm: bool
    duration_seconds: float | None = Field(default=None, ge=0)
    threshold_seconds: float | None = Field(default=None, ge=0)
    camera_ids: list[int] = Field(default_factory=list)
    camera_counts: dict[str, int | None] = Field(default_factory=dict)
    camera_states: dict[str, LogisticsChannelCameraRuntimeStatus] = Field(default_factory=dict)
    offending_camera_ids: list[int] = Field(default_factory=list)
    updated_at: float | None = None

class LogisticsChannelAlarmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str
    feature_name: LogisticsFeatureName | None = None
    department: str | None = None
    channel_id: int
    channel_name: str | None = None
    reason: str | None = None
    created_at: str | None = None
    image_url: str
    metadata: dict[str, Any] = Field(default_factory=dict)

class LogisticsChannelAlarmListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    items: list[LogisticsChannelAlarmResponse] = Field(default_factory=list)

class LogisticsChannelStatisticsSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    total: int = Field(ge=0)
    today: int = Field(ge=0)

class LogisticsChannelDailyStatistic(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    day: str
    count: int = Field(ge=0)

class LogisticsChannelStatisticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    summary: LogisticsChannelStatisticsSummary
    daily: list[LogisticsChannelDailyStatistic] = Field(default_factory=list)

class LogisticsChannelOkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ok: bool
