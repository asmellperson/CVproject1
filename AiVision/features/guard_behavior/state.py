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
    bbox: BBox
    confidence: float
    track_id: int | None

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return (x1 + x2) / 2, (y1 + y2) / 2


@dataclass(frozen=True)
class PhoneDetection:
    bbox: BBox
    confidence: float

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return (x1 + x2) / 2, (y1 + y2) / 2


@dataclass(frozen=True)
class LocalRuleDecision:
    state: RuleState = "normal"
    reason: str = "无目标"
    confidence: float = 0.0
    track_id: int | None = None
    duration_seconds: float = 0.0

    def __post_init__(self):
        if self.state not in ("normal", "pending", "alarm", "unknown"):
            raise ValueError("无效的局部行为状态")


@dataclass(frozen=True)
class VehicleDetection:
    bbox: BBox
    confidence: float
    class_id: int


@dataclass(frozen=True)
class VehicleObservation:
    available: bool
    detections: tuple[VehicleDetection, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class GuardCameraSnapshot:
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
    last_seen: float
    probability: float | None = None
    classified_at: float | None = None
    last_positive_ts: float | None = None


class GuardTrackMemory:
    """每路 Camera 独享；缓存概率和正识别时间，不缓存业务结论。"""

    def __init__(self):
        self.tracks: dict[int, _UniformTrack] = {}

    def observe(self, persons: list[TrackedPerson], now: float, ttl: float) -> None:
        for track_id in list(self.tracks):
            if now - self.tracks[track_id].last_seen > ttl:
                del self.tracks[track_id]
        for person in persons:
            if person.track_id is not None:
                self.tracks.setdefault(person.track_id, _UniformTrack(now)).last_seen = now

    def cached_probability(self, track_id: int | None, now: float) -> float | None:
        track = self.tracks.get(track_id)
        if track is not None and track.classified_at is not None:
            if now - track.classified_at <= UNIFORM_CACHE_TTL_SECONDS:
                return track.probability
        return None

    def remember(self, track_id: int | None, probability: float, now: float) -> None:
        if track_id is not None:
            track = self.tracks[track_id]
            track.probability, track.classified_at = probability, now

    def keep(self, track_id: int | None, is_guard_now: bool, now: float, hold: float) -> bool:
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
    READY = "READY"
    OFFLINE = "OFFLINE"
    STALE = "STALE"
    PHYSICAL_DISABLED = "PHYSICAL_DISABLED"
    INFERENCE_ERROR = "INFERENCE_ERROR"


@dataclass(frozen=True)
class SiteRuleDecision:
    availability: Literal["available", "degraded", "unavailable"]
    state: Literal["normal", "pending", "alarm", "unknown", "idle", "monitoring"]
    reason: str
    primary_camera_id: int | None = None
    offending_camera_ids: tuple[int, ...] = ()
    confidence: float = 0.
    duration_seconds: float = 0.


@dataclass(frozen=True)
class SiteEvaluation:
    status: Literal["disabled", "unconfigured", "healthy", "degraded", "unavailable"]
    camera_states: dict[int, CameraAvailability]
    absence: SiteRuleDecision
    phone: SiteRuleDecision
    prone: SiteRuleDecision
    vehicle: SiteRuleDecision
    updated_at: float
