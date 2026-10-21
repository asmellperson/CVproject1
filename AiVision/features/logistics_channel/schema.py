"""物流摄像头 ROI、通道检测策略、成员请求和运行状态的数据合同。"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from AiVision.features._shared.roi import NormalizedRoi
from .schedule import LogisticsSchedule, schedule_from_storage
from AiVision.alarms.devices.binding import MAX_HORN_ID
from AiVision.features._shared import defaults
from .constants import (
    DEFAULT_PERSON_CONFIDENCE_THRESHOLD, MAX_CAMERAS_PER_CHANNEL,
    DEFAULT_EMPTY_GRACE_SECONDS, DEFAULT_MULTI_GRACE_SECONDS,
    DEFAULT_MODEL_IOU, DEFAULT_MIN_BOX_AREA,
    DEFAULT_ASPECT_RATIO_RANGE, DEFAULT_CAP_INTERVAL,
)


class LogisticsSinglePersonValueSchema(BaseModel):
    """逐路摄像头只保存画面几何 ROI；检测策略由通道统一管理。"""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    roi_pos: NormalizedRoi = Field(default_factory=list)


class LogisticsSinglePersonConfigSchema(BaseModel):
    """内部 Feature 生命周期和逐路 ROI，不作为物流业务配置 API。"""
    model_config = ConfigDict(extra="forbid", strict=True)

    enable: bool = False
    value: LogisticsSinglePersonValueSchema = Field(default_factory=LogisticsSinglePersonValueSchema)


class LogisticsCameraRoiUpdate(BaseModel):
    """逐摄像头唯一 ROI 的严格更新请求。"""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    roi_pos: NormalizedRoi


class LogisticsCameraIdentity(BaseModel):
    """ROI 编辑与预览所需的最小摄像头身份。"""
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    shm_name: str
    enable: bool


class LogisticsCameraRoiResponse(LogisticsCameraRoiUpdate):
    """返回摄像头身份及其归一化 ROI。"""
    camera: LogisticsCameraIdentity


LogisticsFeatureName = Literal[
    "detect_logistics_single_person",
]
LogisticsChannelStatusReason = Literal[
    "normal", "empty", "multiple", "unknown", "unconfigured", "inactive",
]

class LogisticsChannelAlarmChannel(BaseModel):
    """通道喇叭开关和设备事件绑定参数。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool = False
    horn_id: int | None = Field(default=None, gt=0, le=MAX_HORN_ID, strict=True)
    horn_event_id: int | None = Field(default=None, gt=0, le=MAX_HORN_ID, strict=True)

    @model_validator(mode="after")
    def _validate_enabled_horn(self) -> "LogisticsChannelAlarmChannel":
        """喇叭启用时必须同时具备设备与事件 ID。"""
        if self.enabled and (self.horn_id is None or self.horn_event_id is None):
            raise ValueError("启用喇叭告警时必须提供 horn_id 和 horn_event_id")
        return self

class LogisticsChannelWechatChannel(BaseModel):
    """通道企业微信通知开关和接收对象。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool = False
    user: str = ""

class LogisticsChannelAlarm(BaseModel):
    """组合数据库、喇叭和企业微信三个通知通道。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    sql_enable: bool = False
    horn: LogisticsChannelAlarmChannel = Field(default_factory=LogisticsChannelAlarmChannel)
    wechat: LogisticsChannelWechatChannel = Field(default_factory=LogisticsChannelWechatChannel)

class LogisticsChannelCreate(BaseModel):
    """新建通道的名称与所属事业部。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=100)
    department: str = Field(min_length=1, max_length=100)

class LogisticsChannelUpdate(BaseModel):
    """通道名称、启用状态和排序的局部修改。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    sort_order: int | None = None

class LogisticsChannelConfigUpdate(BaseModel):
    """通道统一检测时段、人体筛选、宽限期及告警策略。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schedule: LogisticsSchedule = Field(default_factory=LogisticsSchedule)
    confidence_threshold: float = Field(
        default=DEFAULT_PERSON_CONFIDENCE_THRESHOLD,
        ge=0,
        le=1,
    )
    model_iou_threshold: float = Field(default=DEFAULT_MODEL_IOU, ge=0, le=1, strict=True)
    min_box_area: int = Field(default=DEFAULT_MIN_BOX_AREA, ge=0, strict=True)
    min_aspect_ratio: float = Field(default=DEFAULT_ASPECT_RATIO_RANGE[0], ge=0, strict=True)
    max_aspect_ratio: float = Field(default=DEFAULT_ASPECT_RATIO_RANGE[1], ge=0, strict=True)
    cap_interval: float = Field(default=DEFAULT_CAP_INTERVAL, gt=0, strict=True)
    empty_grace_seconds: float = Field(default=DEFAULT_EMPTY_GRACE_SECONDS, ge=0)
    multi_grace_seconds: float = Field(default=DEFAULT_MULTI_GRACE_SECONDS, ge=0)
    alarm_interval: float = Field(default=defaults.ALARM_INTERVAL, gt=0)
    alarm: LogisticsChannelAlarm = Field(default_factory=LogisticsChannelAlarm)

    @model_validator(mode="after")
    def _validate_aspect_ratio(self) -> LogisticsChannelConfigUpdate:
        # 局部更新先校验明确提交的范围，服务层再与数据库保留值合并校验。
        """同时提交范围两端时直接校验，单端更新留给服务层合并校验。"""
        if {"min_aspect_ratio", "max_aspect_ratio"} <= self.model_fields_set:
            if self.max_aspect_ratio < self.min_aspect_ratio:
                raise ValueError("max_aspect_ratio 不得小于 min_aspect_ratio")
        return self

class LogisticsChannelPatchRequest(LogisticsChannelUpdate):
    """通道元数据及检测配置的局部更新请求。"""
    config: LogisticsChannelConfigUpdate | None = None


class LogisticsChannelMemberCreate(BaseModel):
    """互斥支持绑定已有摄像头与新建摄像头后绑定两种请求。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    camera_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    fps: int = Field(default=5, gt=0)
    shm_name: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_camera_input_mode(self) -> "LogisticsChannelMemberCreate":
        """禁止混用已有 ID 和新建字段，新建时必须同时给出名称及地址。"""
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
    """完整摄像头排列请求，受通道最大容量限制。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    camera_ids: list[Annotated[int, Field(gt=0)]] = Field(
        min_length=1,
        max_length=MAX_CAMERAS_PER_CHANNEL,
    )

    @model_validator(mode="after")
    def _validate_unique_camera_ids(self) -> "LogisticsChannelMemberOrder":
        """拒绝重复成员 ID，避免排序覆盖。"""
        if len(set(self.camera_ids)) != len(self.camera_ids):
            raise ValueError("camera_ids 不可重复")
        return self

class LogisticsChannelMemberEnabledUpdate(BaseModel):
    """启用或停用一个通道成员；成员本身不会被删除。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool

class LogisticsChannelMemberResponse(BaseModel):
    """通道成员关系、独立开关和顺序的响应结构。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    camera_id: int
    enabled: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

class LogisticsChannelConfigResponse(LogisticsChannelConfigUpdate):
    """从通道 ORM 展开完整配置，并复用配置约束核验已存值。"""
    model_config = ConfigDict(from_attributes=True, extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def _adapt_channel_orm(cls, value: Any) -> Any:
        """把扁平数据库告警字段组织为前端需要的嵌套通道配置。"""
        if isinstance(value, dict) or not hasattr(value, "detection_start"):
            return value
        return {
            "schedule": schedule_from_storage(value.detection_start, value.detection_end, value.alarm_schedule),
            "confidence_threshold": value.confidence_threshold,
            "model_iou_threshold": value.model_iou_threshold,
            "min_box_area": value.min_box_area,
            "min_aspect_ratio": value.min_aspect_ratio,
            "max_aspect_ratio": value.max_aspect_ratio,
            "cap_interval": value.cap_interval,
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
    """通道基础信息，不携带完整成员与运行快照。"""
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
    """指定查询范围的通道列表。"""
    items: list[LogisticsChannelResponse]

class LogisticsCameraInventoryMembership(BaseModel):
    """摄像头在某物流功能下的通道归属及参与状态。"""
    feature_name: LogisticsFeatureName
    channel_id: int
    channel_name: str
    enabled: bool
    online: bool

class LogisticsCameraInventoryItem(BaseModel):
    """摄像头清单项，汇总资源身份、在线状态及所有物流归属。"""
    camera_id: int
    name: str
    shm_name: str
    department: str | None = None
    enabled: bool
    online: bool
    memberships: list[LogisticsCameraInventoryMembership] = Field(default_factory=list)

class LogisticsCameraInventoryResponse(BaseModel):
    """供总览和配置清单共享的摄像头集合。"""
    items: list[LogisticsCameraInventoryItem] = Field(default_factory=list)

class LogisticsChannelDetailResponse(LogisticsChannelResponse):
    """组合基础信息、检测配置、成员与可选运行状态。"""
    config: LogisticsChannelConfigResponse
    members: list[LogisticsChannelMemberResponse] = Field(default_factory=list)
    status: LogisticsChannelStatusResponse | None = None

    @model_validator(mode="before")
    @classmethod
    def _adapt_channel_orm(cls, value: Any) -> Any:
        """将通道记录与成员关系组装为详情校验输入。"""
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
    alarm_suppressed: bool
    duration_seconds: float | None = Field(default=None, ge=0)
    threshold_seconds: float | None = Field(default=None, ge=0)
    camera_ids: list[int] = Field(default_factory=list)
    camera_counts: dict[str, int | None] = Field(default_factory=dict)
    camera_states: dict[str, LogisticsChannelCameraRuntimeStatus] = Field(default_factory=dict)
    offending_camera_ids: list[int] = Field(default_factory=list)
    updated_at: float | None = None

class LogisticsChannelAlarmResponse(BaseModel):
    """以物流通道为主体的告警历史，包含证据地址与详细元数据。"""
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
    """物流通道告警列表响应。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    items: list[LogisticsChannelAlarmResponse] = Field(default_factory=list)

class LogisticsChannelStatisticsSummary(BaseModel):
    """查询范围内总告警数及今日告警数。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    total: int = Field(ge=0)
    today: int = Field(ge=0)

class LogisticsChannelDailyStatistic(BaseModel):
    """单个日期的告警数量。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    day: str
    count: int = Field(ge=0)

class LogisticsChannelStatisticsResponse(BaseModel):
    """组合汇总数和逐日分布的统计结果。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    summary: LogisticsChannelStatisticsSummary
    daily: list[LogisticsChannelDailyStatistic] = Field(default_factory=list)

class LogisticsChannelOkResponse(BaseModel):
    """无额外返回数据的通道操作成功标志。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ok: bool
