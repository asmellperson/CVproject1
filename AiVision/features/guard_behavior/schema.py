"""保安室数据合同；局部更新与已存值合并后再次执行完整校验。"""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AliasPath, BaseModel, ConfigDict, Field, field_validator, model_validator

from AiVision.alarms.devices.binding import MAX_HORN_ID
from AiVision.departments.department_registry import require_department
from AiVision.features._shared.roi import NormalizedRoi
from .constants import (
    ALARM_POLICY_DEFAULTS, GUARD_ALARM_TYPES, MAX_CAMERAS_PER_SITE, MAX_MODEL_IMGSZ, MIN_MODEL_IMGSZ,
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
    """公共校验基类，拒绝未知字段、隐式类型转换与非有限数值。"""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, from_attributes=True)


class _TimestampsResponse(_StrictSchema):
    """对外提供持久化记录的创建和更新时间。"""
    created_at: datetime
    updated_at: datetime


class GuardBehaviorSiteCreate(_StrictSchema):
    """新建保安室的名称、事业部与初始展示顺序。"""
    name: str = Field(min_length=1, max_length=100)
    department: str
    enabled: bool = True
    sort_order: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        """去除名称首尾空白并拒绝空名称。"""
        value = value.strip()
        if not value:
            raise ValueError("保安室名称不能为空")
        return value

    @field_validator("department")
    @classmethod
    def _department(cls, value: str) -> str:
        """要求事业部属于项目正式注册范围。"""
        return require_department(value)


class GuardBehaviorSiteUpdate(_StrictSchema):
    """保安室局部更新字段，未提交字段保留原值。"""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _non_null(self):
        """区分未提交字段与显式 null，拒绝把现有值清为空。"""
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("保安室字段不能为 null")
        return self


class GuardBehaviorSiteResponse(GuardBehaviorSiteCreate, _TimestampsResponse):
    """保安室身份、基本属性及持久化时间的响应结构。"""
    id: PositiveId


class GuardBehaviorMemberCreate(_StrictSchema):
    """通过平台摄像头 ID 建立保安室成员关系。"""
    camera_id: PositiveId


class GuardBehaviorMemberEnabledUpdate(_StrictSchema):
    """只调整成员是否参与保安室检测。"""
    enabled: bool


class GuardBehaviorMemberOrder(_StrictSchema):
    """提交完整成员排列，顺序由 camera_ids 的位置表达。"""
    camera_ids: list[PositiveId] = Field(max_length=MAX_CAMERAS_PER_SITE)

    @field_validator("camera_ids")
    @classmethod
    def _unique(cls, values: list[int]) -> list[int]:
        """拒绝重复摄像头 ID，防止排序覆盖或歧义。"""
        if len(values) != len(set(values)):
            raise ValueError("camera_ids 不可重复")
        return values


class GuardBehaviorMemberResponse(_TimestampsResponse):
    """展开成员和物理摄像头信息，分别暴露两层启用状态。"""
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
    """校验车辆检测使用的归一化多边形区域。"""
    vehicle_roi_pos: NormalizedRoi


class GuardBehaviorCameraRoiResponse(GuardBehaviorCameraRoiUpdate):
    """返回车辆 ROI、摄像头身份与功能启用状态。"""
    camera_id: PositiveId
    enable: bool


class GuardBehaviorCameraValueSchema(_StrictSchema):
    """摄像头级可配置参数，仅保存车辆 ROI。"""
    vehicle_roi_pos: NormalizedRoi = Field(default_factory=list)


class GuardBehaviorCameraConfigSchema(_StrictSchema):
    """供公共功能配置入口使用的开关与摄像头参数结构。"""
    enable: bool = False
    value: GuardBehaviorCameraValueSchema = Field(default_factory=GuardBehaviorCameraValueSchema)


class GuardBehaviorSitePolicyUpdate(_StrictSchema):
    """检测策略字段及数值约束，服务层以已存配置补齐未提交值。"""
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
    """完整策略校验，保证车辆检查开关与选定摄像头一致。"""
    @model_validator(mode="after")
    def _vehicle_camera(self):
        """启用车辆检查必须选摄像头，关闭时必须清空该选择。"""
        if self.vehicle_inspection_enabled and self.vehicle_camera_id is None:
            raise ValueError("启用车辆检查必须提供 vehicle_camera_id")
        if not self.vehicle_inspection_enabled and self.vehicle_camera_id is not None:
            raise ValueError("关闭车辆检查时 vehicle_camera_id 必须为 None")
        return self


class GuardBehaviorSitePolicyResponse(GuardBehaviorSitePolicyUpdate, _TimestampsResponse):
    """读取保留物理 Camera 删除后 SET NULL 的事实；保存必须通过完整策略校验。"""

    id: PositiveId
    site_id: PositiveId


class GuardBehaviorRuntimePolicy(GuardBehaviorSitePolicyUpdate):
    """不可变的运行策略快照，避免运行线程持有可变 ORM 对象。"""
    model_config = ConfigDict(frozen=True)


class GuardBehaviorRuntimeCameraConfig(_StrictSchema):
    """脱离 Session 的只读运行快照；ROI 使用不可变坐标序列。"""

    model_config = ConfigDict(frozen=True)
    camera_id: PositiveId
    camera_name: str
    shm_name: str
    fps: PositiveSeconds
    department: str
    site_id: PositiveId
    site_name: str
    site_enabled: bool
    member_enabled: bool
    feature_enabled: bool
    vehicle_roi_pos: tuple[tuple[float, float], ...]
    policy: GuardBehaviorRuntimePolicy


class GuardBehaviorAlarmPolicyUpdate(_StrictSchema):
    """单类告警的冷却与通道参数，支持仅更新提交的字段。"""
    alarm_interval: PositiveSeconds | None = None
    sql_enable: bool = ALARM_POLICY_DEFAULTS["sql_enable"]
    horn_enable: bool = ALARM_POLICY_DEFAULTS["horn_enable"]
    horn_id: HornId | None = ALARM_POLICY_DEFAULTS["horn_id"]
    horn_event_id: HornId | None = ALARM_POLICY_DEFAULTS["horn_event_id"]
    wechat_enable: bool = ALARM_POLICY_DEFAULTS["wechat_enable"]
    wechat_user: str = Field(default=ALARM_POLICY_DEFAULTS["wechat_user"], max_length=255)

    @model_validator(mode="after")
    def _non_null_interval(self):
        """允许不提交冷却参数，但禁止将它显式置为 null。"""
        if "alarm_interval" in self.model_fields_set and self.alarm_interval is None:
            raise ValueError("alarm_interval 不能为 null")
        return self


class GuardBehaviorAlarmPolicyResponse(GuardBehaviorAlarmPolicyUpdate, _TimestampsResponse):
    """含数据库身份与正式告警类型的策略响应。"""
    id: PositiveId
    site_id: PositiveId
    violation_type: int
    alarm_interval: PositiveSeconds

    @field_validator("violation_type")
    @classmethod
    def _alarm_type(cls, value: int) -> int:
        """确保响应策略属于保安室正式告警类型。"""
        return require_alarm_type(value)


class GuardBehaviorRuntimeAlarmPolicy(GuardBehaviorAlarmPolicyUpdate):
    """运行线程使用的不可变告警通道与冷却快照。"""
    model_config = ConfigDict(frozen=True)
    violation_type: int
    alarm_interval: PositiveSeconds

    @field_validator("violation_type")
    @classmethod
    def _alarm_type(cls, value: int) -> int:
        """拒绝混入其他功能的告警策略。"""
        return require_alarm_type(value)


class GuardBehaviorRuntimeMember(_StrictSchema):
    """运行时成员快照，保留物理、成员及功能三层开关。"""
    model_config = ConfigDict(frozen=True)
    camera_id: PositiveId
    camera_name: str
    shm_name: str
    member_enabled: bool
    physical_enabled: bool
    feature_enabled: bool
    sort_order: int


class GuardBehaviorRuntimeSiteConfig(_StrictSchema):
    """同一次数据库读取形成的配置快照，运行线程不保留 Session 或 ORM。"""

    model_config = ConfigDict(frozen=True)
    site_id: PositiveId
    site_name: str
    department: str
    enabled: bool
    members: tuple[GuardBehaviorRuntimeMember, ...]
    policy: GuardBehaviorRuntimePolicy
    alarm_policies: tuple[GuardBehaviorRuntimeAlarmPolicy, ...]

    @field_validator("department")
    @classmethod
    def _department(cls, value: str) -> str:
        """校验站点快照的事业部身份。"""
        return require_department(value)

    @model_validator(mode="after")
    def _complete(self):
        """要求四类告警策略完整唯一，且摄像头成员无重复并未超限。"""
        if sorted(item.violation_type for item in self.alarm_policies) != list(GUARD_ALARM_TYPES):
            raise ValueError("Site 运行配置必须包含完整且唯一的四类报警策略")
        camera_ids = [member.camera_id for member in self.members]
        if len(camera_ids) != len(set(camera_ids)) or len(camera_ids) > MAX_CAMERAS_PER_SITE:
            raise ValueError("Site 运行配置的 Camera 成员重复或超限")
        return self
