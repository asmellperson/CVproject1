"""保安室数据合同；局部更新与已存值合并后再次执行完整校验。"""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AliasPath, BaseModel, ConfigDict, Field, field_validator, model_validator

from AiVision.alarms.devices.binding import MAX_HORN_ID
from AiVision.departments.department_registry import require_department
from AiVision.features._shared.roi import NormalizedRoi
from .constants import (
    ALARM_POLICY_DEFAULTS, MAX_CAMERAS_PER_SITE, MAX_MODEL_IMGSZ, MIN_MODEL_IMGSZ,
    SITE_POLICY_DEFAULTS, require_alarm_type,
)


PositiveId = Annotated[int, Field(gt=0)]
Probability = Annotated[float, Field(ge=0, le=1)]
NonNegative = Annotated[float, Field(ge=0)]
PositiveSeconds = Annotated[float, Field(gt=0)]
ImageSize = Annotated[int, Field(ge=MIN_MODEL_IMGSZ, le=MAX_MODEL_IMGSZ)]
PositiveCount = Annotated[int, Field(ge=1)]
HornId = Annotated[int, Field(gt=0, le=MAX_HORN_ID)]


class _StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, from_attributes=True)


class _TimestampsResponse(_StrictSchema):
    created_at: datetime
    updated_at: datetime


class GuardBehaviorSiteCreate(_StrictSchema):
    name: str = Field(min_length=1, max_length=100)
    department: str
    enabled: bool = True
    sort_order: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("保安室名称不能为空")
        return value

    @field_validator("department")
    @classmethod
    def _department(cls, value: str) -> str:
        return require_department(value)


class GuardBehaviorSiteUpdate(_StrictSchema):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _non_null(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("保安室字段不能为 null")
        return self


class GuardBehaviorSiteResponse(GuardBehaviorSiteCreate, _TimestampsResponse):
    id: PositiveId


class GuardBehaviorMemberCreate(_StrictSchema):
    camera_id: PositiveId


class GuardBehaviorMemberEnabledUpdate(_StrictSchema):
    enabled: bool


class GuardBehaviorMemberOrder(_StrictSchema):
    camera_ids: list[PositiveId] = Field(max_length=MAX_CAMERAS_PER_SITE)

    @field_validator("camera_ids")
    @classmethod
    def _unique(cls, values: list[int]) -> list[int]:
        if len(values) != len(set(values)):
            raise ValueError("camera_ids 不可重复")
        return values


class GuardBehaviorMemberResponse(_TimestampsResponse):
    model_config = ConfigDict(populate_by_name=True)

    id: PositiveId
    camera_id: PositiveId
    name: str = Field(validation_alias=AliasPath("camera", "name"))
    shm_name: str = Field(validation_alias=AliasPath("camera", "shm_name"))
    department: str = Field(validation_alias=AliasPath("camera", "department"))
    physical_enabled: bool = Field(validation_alias=AliasPath("camera", "enable"))
    member_enabled: bool = Field(validation_alias="enabled")
    sort_order: int


class GuardBehaviorCameraRoiUpdate(_StrictSchema):
    vehicle_roi_pos: NormalizedRoi


class GuardBehaviorCameraRoiResponse(GuardBehaviorCameraRoiUpdate):
    camera_id: PositiveId
    enable: bool


class GuardBehaviorSitePolicyUpdate(_StrictSchema):
    cap_interval: PositiveSeconds = SITE_POLICY_DEFAULTS["cap_interval"]
    person_confidence_threshold: Probability = SITE_POLICY_DEFAULTS["person_confidence_threshold"]
    phone_confidence_threshold: Probability = SITE_POLICY_DEFAULTS["phone_confidence_threshold"]
    uniform_confidence_threshold: Probability = SITE_POLICY_DEFAULTS["uniform_confidence_threshold"]
    vehicle_confidence_threshold: Probability = SITE_POLICY_DEFAULTS["vehicle_confidence_threshold"]
    model_iou_threshold: Probability = SITE_POLICY_DEFAULTS["model_iou_threshold"]
    person_phone_imgsz: ImageSize = SITE_POLICY_DEFAULTS["person_phone_imgsz"]
    phone_crop_imgsz: ImageSize = SITE_POLICY_DEFAULTS["phone_crop_imgsz"]
    pose_imgsz: ImageSize = SITE_POLICY_DEFAULTS["pose_imgsz"]
    vehicle_imgsz: ImageSize = SITE_POLICY_DEFAULTS["vehicle_imgsz"]
    guard_hold_seconds: NonNegative = SITE_POLICY_DEFAULTS["guard_hold_seconds"]
    absent_alarm_seconds: PositiveSeconds = SITE_POLICY_DEFAULTS["absent_alarm_seconds"]
    phone_seconds: PositiveSeconds = SITE_POLICY_DEFAULTS["phone_seconds"]
    phone_window_seconds: PositiveSeconds = SITE_POLICY_DEFAULTS["phone_window_seconds"]
    phone_min_hits_in_window: PositiveCount = SITE_POLICY_DEFAULTS["phone_min_hits_in_window"]
    phone_grace_seconds: NonNegative = SITE_POLICY_DEFAULTS["phone_grace_seconds"]
    phone_near_person_px: NonNegative = SITE_POLICY_DEFAULTS["phone_near_person_px"]
    phone_near_head_px: NonNegative = SITE_POLICY_DEFAULTS["phone_near_head_px"]
    prone_sleep_seconds: PositiveSeconds = SITE_POLICY_DEFAULTS["prone_sleep_seconds"]
    static_motion_threshold: NonNegative = SITE_POLICY_DEFAULTS["static_motion_threshold"]
    prone_head_down_ratio_threshold: Probability = SITE_POLICY_DEFAULTS["prone_head_down_ratio_threshold"]
    prone_bbox_height_ratio_threshold: Probability = SITE_POLICY_DEFAULTS["prone_bbox_height_ratio_threshold"]
    prone_consecutive_frames: PositiveCount = SITE_POLICY_DEFAULTS["prone_consecutive_frames"]
    state_ttl_seconds: PositiveSeconds = SITE_POLICY_DEFAULTS["state_ttl_seconds"]
    vehicle_inspection_enabled: bool = SITE_POLICY_DEFAULTS["vehicle_inspection_enabled"]
    vehicle_camera_id: PositiveId | None = SITE_POLICY_DEFAULTS["vehicle_camera_id"]
    vehicle_occlusion_seconds: PositiveSeconds = SITE_POLICY_DEFAULTS["vehicle_occlusion_seconds"]
    vehicle_near_px: NonNegative = SITE_POLICY_DEFAULTS["vehicle_near_px"]
    vehicle_exit_direction: Literal["any", "left", "right", "up", "down"] = SITE_POLICY_DEFAULTS["vehicle_exit_direction"]
    vehicle_direction_min_delta_ratio: Probability = SITE_POLICY_DEFAULTS["vehicle_direction_min_delta_ratio"]
    vehicle_reassociate_seconds: NonNegative = SITE_POLICY_DEFAULTS["vehicle_reassociate_seconds"]


class GuardBehaviorSitePolicySchema(GuardBehaviorSitePolicyUpdate):
    @model_validator(mode="after")
    def _vehicle_camera(self):
        if self.vehicle_inspection_enabled and self.vehicle_camera_id is None:
            raise ValueError("启用车辆检查必须提供 vehicle_camera_id")
        if not self.vehicle_inspection_enabled and self.vehicle_camera_id is not None:
            raise ValueError("关闭车辆检查时 vehicle_camera_id 必须为 None")
        return self


class GuardBehaviorSitePolicyResponse(GuardBehaviorSitePolicyUpdate, _TimestampsResponse):
    """读取保留物理 Camera 删除后 SET NULL 的事实；保存必须通过完整策略校验。"""

    id: PositiveId
    site_id: PositiveId


class GuardBehaviorAlarmPolicyUpdate(_StrictSchema):
    alarm_interval: PositiveSeconds | None = None
    sql_enable: bool = ALARM_POLICY_DEFAULTS["sql_enable"]
    horn_enable: bool = ALARM_POLICY_DEFAULTS["horn_enable"]
    horn_id: HornId | None = ALARM_POLICY_DEFAULTS["horn_id"]
    horn_event_id: HornId | None = ALARM_POLICY_DEFAULTS["horn_event_id"]
    wechat_enable: bool = ALARM_POLICY_DEFAULTS["wechat_enable"]
    wechat_user: str = Field(default=ALARM_POLICY_DEFAULTS["wechat_user"], max_length=255)

    @model_validator(mode="after")
    def _non_null_interval(self):
        if "alarm_interval" in self.model_fields_set and self.alarm_interval is None:
            raise ValueError("alarm_interval 不能为 null")
        return self


class GuardBehaviorAlarmPolicyResponse(GuardBehaviorAlarmPolicyUpdate, _TimestampsResponse):
    id: PositiveId
    site_id: PositiveId
    violation_type: int
    alarm_interval: PositiveSeconds

    @field_validator("violation_type")
    @classmethod
    def _alarm_type(cls, value: int) -> int:
        return require_alarm_type(value)
