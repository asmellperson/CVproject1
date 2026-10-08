"""单摄纯数据快照与制服识别状态，不持有模型、帧或数据库对象。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


BBox = tuple[float, float, float, float]
RuleState = Literal["normal", "pending", "alarm", "unknown"]
ModelState = Literal["ready", "unavailable", "error", "not_applicable"]
UNIFORM_CACHE_TTL_SECONDS = 0.1
UNIFORM_EXPAND_RATIO = 0.10


@dataclass(frozen=True)
class TrackedPerson:
    """原帧人体框及可选轨迹编号，尚未激活的轨迹保留 None。"""
    bbox: BBox
    confidence: float
    track_id: int | None

    @property
    def center(self) -> tuple[float, float]:
        """提供人体中心供局部运动及邻近关系计算。"""
        x1, y1, x2, y2 = self.bbox
        return (x1 + x2) / 2, (y1 + y2) / 2


@dataclass(frozen=True)
class PhoneDetection:
    """原帧坐标下的手机检测事实。"""
    bbox: BBox
    confidence: float

    @property
    def center(self) -> tuple[float, float]:
        """提供手机中心供人体与头部关联判断。"""
        x1, y1, x2, y2 = self.bbox
        return (x1 + x2) / 2, (y1 + y2) / 2


@dataclass(frozen=True)
class LocalRuleDecision:
    """单路行为规则的状态、理由和证据持续时间。"""
    state: RuleState = "normal"
    reason: str = "无目标"
    confidence: float = 0.0
    track_id: int | None = None
    duration_seconds: float = 0.0

    def __post_init__(self):
        """拒绝未定义的局部状态，保持聚合层状态契约稳定。"""
        if self.state not in ("normal", "pending", "alarm", "unknown"):
            raise ValueError("无效的局部行为状态")


@dataclass(frozen=True)
class VehicleDetection:
    """带模型类别的车辆检测事实，供同类车辆事件匹配。"""
    bbox: BBox
    confidence: float
    class_id: int


@dataclass(frozen=True)
class VehicleObservation:
    """区分有效的空车辆结果与车辆模型不可用。"""
    available: bool
    detections: tuple[VehicleDetection, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class GuardCameraSnapshot:
    """单摄像头感知快照，包含证据时间、模型状态和各局部规则结果。"""
    camera_id: int
    camera_name: str
    site_id: int
    site_name: str
    updated_at: float
    online: bool
    guard_present: bool | None
    guard_count: int | None
    guard_confidence: float | None
    phone: LocalRuleDecision
    prone: LocalRuleDecision
    vehicle: VehicleObservation
    model_states: dict[str, ModelState]
    guards: tuple[TrackedPerson, ...]
    frame_size: tuple[int, int]  # 原始像素宽、高，仅供同摄空间关系和方向比例计算。


@dataclass
class _UniformTrack:
    """缓存制服概率及最近正识别时间，业务阈值仍在每次判断时应用。"""
    last_seen: float
    probability: float | None = None
    classified_at: float | None = None
    last_positive_ts: float | None = None


class GuardTrackMemory:
    """每路 Camera 独享；缓存概率和正识别时间，不缓存业务结论。"""

    def __init__(self):
        """初始化当前摄像头的制服识别记忆。"""
        self.tracks: dict[int, _UniformTrack] = {}

    def observe(self, persons: list[TrackedPerson], now: float, ttl: float) -> None:
        """更新稳定轨迹最后出现时间，并回收过期身份缓存。"""
        for track_id in list(self.tracks):
            if now - self.tracks[track_id].last_seen > ttl:
                del self.tracks[track_id]
        for person in persons:
            if person.track_id is not None:
                self.tracks.setdefault(person.track_id, _UniformTrack(now)).last_seen = now

    def cached_probability(self, track_id: int | None, now: float) -> float | None:
        """仅返回缓存有效期内的制服概率，过期或无轨迹时返回 None。"""
        track = self.tracks.get(track_id)
        if track is not None and track.classified_at is not None:
            if now - track.classified_at <= UNIFORM_CACHE_TTL_SECONDS:
                return track.probability
        return None

    def remember(self, track_id: int | None, probability: float, now: float) -> None:
        """缓存已有稳定轨迹的分类结果，无编号目标不跨帧缓存。"""
        if track_id is not None:
            track = self.tracks[track_id]
            track.probability, track.classified_at = probability, now

    def keep(self, track_id: int | None, is_guard_now: bool, now: float, hold: float) -> bool:
        """允许最近的正识别在保持期内延续，缓解短时制服误判。"""
        if track_id is None:
            return is_guard_now
        track = self.tracks[track_id]
        if is_guard_now:
            track.last_positive_ts = now
            return True
        return track.last_positive_ts is not None and now - track.last_positive_ts <= hold


@dataclass(frozen=True)
class CameraPerception:
    """一帧处理的局部结果，标注帧通过独立缓存传递。"""

    persons: tuple[TrackedPerson, ...]
    guards: tuple[TrackedPerson, ...]
    phones: tuple[PhoneDetection, ...]
    guard_present: bool | None
    guard_count: int | None
    guard_confidence: float | None
    phone: LocalRuleDecision
    prone: LocalRuleDecision
    vehicle: VehicleObservation
    model_states: dict[str, ModelState] = field(default_factory=dict)


class CameraAvailability(str, Enum):
    """区分采集离线、物理禁用、结果过期和推理错误的可用性状态。"""
    READY = "READY"
    OFFLINE = "OFFLINE"
    STALE = "STALE"
    PHYSICAL_DISABLED = "PHYSICAL_DISABLED"
    INFERENCE_ERROR = "INFERENCE_ERROR"


@dataclass(frozen=True)
class SiteRuleDecision:
    """保安室级规则结论，同时描述证据可用性及主要取证摄像头。"""
    availability: Literal["available", "degraded", "unavailable"]
    state: Literal["normal", "pending", "alarm", "unknown", "idle", "monitoring"]
    reason: str
    primary_camera_id: int | None = None
    offending_camera_ids: tuple[int, ...] = ()
    confidence: float = 0.
    duration_seconds: float = 0.


@dataclass(frozen=True)
class GuardCameraMetrics:
    """监控展示用的保安计数、置信度与采样 FPS，可未知。"""
    guard_count: int | None
    guard_confidence: float | None
    fps: float | None


@dataclass(frozen=True)
class SiteEvaluation:
    """一次保安室汇总的总体健康状态、摄像头状态及四类规则结论。"""
    status: Literal["disabled", "unconfigured", "healthy", "degraded", "unavailable"]
    camera_states: dict[int, CameraAvailability]
    absence: SiteRuleDecision
    phone: SiteRuleDecision
    prone: SiteRuleDecision
    vehicle: SiteRuleDecision
    updated_at: float
    camera_metrics: dict[int, GuardCameraMetrics] = field(default_factory=dict)
