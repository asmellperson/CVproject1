"""安检配置与内部千问返回值的唯一契约。"""

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared.roi import NormalizedRoi
from .geometry import validate_polygon


class StrictModel(BaseModel):
    """安检配置的严格基类，拒绝额外字段和非有限数值。"""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class InspectionValue(StrictModel):
    """安检工位、人体跟踪、交互配对及关键帧采样参数。"""
    staff_rois: dict[str, NormalizedRoi] = Field(default_factory=dict)
    cap_interval: float = Field(0.1, ge=0.05, le=5)
    alarm_interval: float = Field(30.0, ge=0, le=86400)
    conf: float = Field(0.35, gt=0, le=1)
    iou: float = Field(0.6, gt=0, le=1)
    imgsz: int = Field(640, ge=160, le=1920, multiple_of=32)
    pair_start_hold_frames: int = Field(8, ge=1, le=300)
    fingerprint_lost_seconds: float = Field(3.0, gt=0, le=60)
    no_interact_seconds: float = Field(4.0, gt=0, le=60)
    max_session_seconds: float = Field(90.0, ge=1, le=600)
    keyframe_interval_sec: float = Field(0.6, ge=0.1, le=30)
    keyframes_per_session: int = Field(8, ge=2, le=32)
    roi_crop_padding: int = Field(100, ge=0, le=1000)
    fp_match_threshold: float = Field(0.55, ge=0, le=1)
    interact_distance_max_ratio: float = Field(1.5, gt=0.2, le=10)
    interact_motion_min_pixels: float = Field(8.0, ge=0, le=1000)
    roi_enter_overlap_ratio: float = Field(0.3, ge=0, le=1)
    roi_hold_overlap_ratio: float = Field(0.1, ge=0, le=1)

    @field_validator("staff_rois")
    @classmethod
    def validate_rois(cls, value):
        """限制工位数量、名称与顶点数，并拒绝自交或重叠边的区域。"""
        if len(value) > 16:
            raise ValueError("每台摄像头最多设置 16 个工位")
        for name, points in value.items():
            if not name.strip() or name != name.strip() or len(name) > 100:
                raise ValueError("工位名称必须为 1 到 100 个字符且不含首尾空白")
            if not 3 <= len(points) <= 64:
                raise ValueError("每个工位必须有 3 到 64 个顶点")
            validate_polygon(name, points)
        return value

    @model_validator(mode="after")
    def validate_intervals(self):
        """保证区域保持阈值不高于进入阈值，采样间隔短于最长会话时间。"""
        if self.roi_hold_overlap_ratio > self.roi_enter_overlap_ratio:
            raise ValueError("保持区域的重叠阈值不能大于进入阈值")
        if self.keyframe_interval_sec >= self.max_session_seconds:
            raise ValueError("关键帧间隔必须小于会话最长时长")
        return self


class InspectionConfig(StrictModel):
    """组合安检开关、算法参数与统一告警通道。"""
    enable: bool = False
    value: InspectionValue = Field(default_factory=InspectionValue)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)

    @model_validator(mode="after")
    def validate_wechat(self):
        """启用企业微信时要求非空接收人，避免已启用但无法送达的配置。"""
        if self.alarm.wechat.enable and not self.alarm.wechat.parm.user.strip():
            raise ValueError("启用微信报警时必须填写接收人")
        return self


class VlmSettings(StrictModel):
    """内部判定服务的地址、模型、生成参数及有界任务队列设置。"""
    base_url: str = "http://127.0.0.1:18100/v1"
    model: str = "fuda-qwen36-27b"
    max_tokens: int = Field(2048, ge=128, le=16384)
    temperature: float = Field(0.1, ge=0, le=2)
    api_timeout_sec: float = Field(45.0, ge=1, le=180)
    queue_timeout_sec: float = Field(60.0, ge=1, le=600)
    max_concurrent: int = Field(3, ge=1, le=16)
    queue_capacity: int = Field(32, ge=1, le=256)
    image_max_side: int = Field(960, ge=160, le=1920)
    image_jpeg_quality: int = Field(85, ge=30, le=100)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        """要求无内嵌凭据、查询和片段的 HTTP 地址，并统一去除尾部斜杠。"""
        url = urlsplit(value)
        if (
            value != value.strip()
            or url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("模型地址必须为不含认证信息的 HTTP(S) 地址")
        return value.rstrip("/")

    @field_validator("model")
    @classmethod
    def validate_model(cls, value):
        """拒绝空名称和首尾空白，保证健康检查与推理使用相同模型标识。"""
        if not value.strip() or value != value.strip():
            raise ValueError("模型名称不能为空或含首尾空白")
        return value


class VlmHealth(StrictModel):
    """表示接口可达性、真实请求成功时间及熔断恢复进度。"""
    reachable: bool | None = None
    checking: bool = False
    last_success: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    circuit_state: Literal["closed", "open", "half_open"] = "closed"
    retry_after_sec: int | None = None


class InspectionVerdict(StrictModel):
    """模型的最终结论；不通过辅助特征重新推导合规性。"""

    compliant: bool
    confidence: float = Field(ge=0, le=1)
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value):
        """规范化判定原因并要求实质内容，避免返回只有空白的解释。"""
        value = value.strip()
        if not value:
            raise ValueError("判定原因不能为空")
        return value


class InspectionStats(BaseModel):
    """查询范围内的全部会话统计，合规率只基于成功判定。"""
    total: int
    compliant: int
    non_compliant: int
    error: int
    cancelled: int
    rate: float


class SessionResponse(BaseModel):
    """平台和外部接口共用的会话历史契约。"""
    session_id: str
    camera_id: int | None
    camera_name: str
    roi_name: str
    started_at: str
    ended_at: str
    duration_sec: float
    status: Literal["compliant", "non_compliant", "error", "cancelled"]
    verdict: InspectionVerdict | None
    error: str | None
    latency_sec: float | None
    has_image: bool


class HistoryResponse(BaseModel):
    """统计独立于分页，items 只包含当前页。"""
    stats: InspectionStats
    items: list[SessionResponse]
    retention_days: int


class StatusResponse(BaseModel):
    """事业部任务数和全局模型健康状态。"""
    running: bool
    queue: int
    active: int
    error: str | None
    vlm: VlmHealth


class SettingsResponse(BaseModel):
    """仅供平台管理员维护的全局模型设置。"""
    settings: VlmSettings
    vlm: VlmHealth
