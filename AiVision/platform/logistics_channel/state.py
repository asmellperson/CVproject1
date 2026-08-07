"""物流通道的纯状态判定、检测框去重与快照存储。"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from threading import RLock
from typing import Iterable, Literal


ChannelReason = Literal["normal", "empty", "multiple", "unknown", "unconfigured", "inactive"]


@dataclass(frozen=True)
class CameraSnapshot:
    camera_id: int
    count: int | None
    updated_at: float
    online: bool = True
    camera_name: str = ""


@dataclass(frozen=True)
class ChannelDecision:
    reason: ChannelReason
    alarm: bool
    duration_seconds: float
    threshold_seconds: float | None
    offending_camera_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class PersonDetection:
    bbox: tuple[float, float, float, float]
    confidence: float
    source_roi: int | None = None


def classify_channel(
    snapshots: Iterable[CameraSnapshot], *, now: float, stale_seconds: float, active: bool = True
) -> ChannelDecision:
    """按全体摄像头人数作无副作用的通道基础判定。"""
    if not _is_finite_number(now) or not _is_finite_number(stale_seconds) or stale_seconds < 0:
        raise ValueError("stale_seconds 必须大于等于 0")
    snapshot_list = tuple(snapshots)
    if not active:
        return _decision("inactive")
    if not snapshot_list:
        return _decision("unconfigured")

    has_normal = False
    has_empty = False
    has_unknown = False
    offending_camera_ids: list[int] = []
    for snapshot in snapshot_list:
        count = snapshot.count
        if (
            not snapshot.online
            or not _is_finite_number(snapshot.updated_at)
            or snapshot.updated_at > now
            or now - snapshot.updated_at > stale_seconds
            or count is None
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            has_unknown = True
        elif count >= 2:
            offending_camera_ids.append(snapshot.camera_id)
        elif count == 1:
            has_normal = True
        else:
            has_empty = True

    if offending_camera_ids:
        return _decision("multiple", offending_camera_ids=tuple(offending_camera_ids))
    if has_normal:
        return _decision("normal")
    if has_unknown:
        return _decision("unknown")
    if has_empty:
        return _decision("empty")
    return _decision("unknown")


class ChannelPresenceState:
    """对连续空人/多人状态计时；实例由单个通道运行时持有。"""

    def __init__(self) -> None:
        self._reason: ChannelReason | None = None
        self._started_at: float | None = None
        self._last_evaluated_at: float | None = None

    def evaluate(
        self,
        decision_or_reason: ChannelDecision | ChannelReason,
        *,
        now: float,
        empty_grace_seconds: float,
        multi_grace_seconds: float,
    ) -> ChannelDecision:
        if (
            not _is_finite_number(now)
            or not _is_finite_number(empty_grace_seconds)
            or not _is_finite_number(multi_grace_seconds)
            or empty_grace_seconds < 0
            or multi_grace_seconds < 0
        ):
            raise ValueError("持续时间阈值必须大于等于 0")
        if isinstance(decision_or_reason, ChannelDecision):
            reason = decision_or_reason.reason
            offending_camera_ids = decision_or_reason.offending_camera_ids
        else:
            reason = decision_or_reason
            offending_camera_ids = ()
        if reason not in {"normal", "empty", "multiple", "unknown", "unconfigured", "inactive"}:
            raise ValueError(f"不支持的通道状态: {reason!r}")

        if reason not in {"empty", "multiple"}:
            self.reset()
            return _decision(reason, offending_camera_ids=offending_camera_ids)

        if (
            self._reason != reason
            or self._started_at is None
            or self._last_evaluated_at is None
            or now < self._last_evaluated_at
        ):
            self._reason = reason
            self._started_at = now
        duration = max(0.0, now - self._started_at)
        self._last_evaluated_at = now
        threshold = empty_grace_seconds if reason == "empty" else multi_grace_seconds
        return ChannelDecision(
            reason=reason,
            alarm=duration >= threshold,
            duration_seconds=duration,
            threshold_seconds=threshold,
            offending_camera_ids=offending_camera_ids,
        )

    def reset(self) -> None:
        """清空当前连续异常状态。"""
        self._reason = None
        self._started_at = None
        self._last_evaluated_at = None


def translate_person_detection(
    detection: PersonDetection, x_offset: float, y_offset: float
) -> PersonDetection:
    """将 ROI 内的检测框平移回原始画面坐标。"""
    x1, y1, x2, y2 = detection.bbox
    return PersonDetection(
        bbox=(x1 + x_offset, y1 + y_offset, x2 + x_offset, y2 + y_offset),
        confidence=detection.confidence,
        source_roi=detection.source_roi,
    )


def intersection_over_union(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    """计算两个正面积 bbox 的 IoU；无效或无重叠的框返回零。"""
    if not _is_valid_bbox(a) or not _is_valid_bbox(b):
        return 0.0
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    overlap_width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    overlap_height = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = overlap_width * overlap_height
    if intersection == 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union


def deduplicate_person_detections(
    detections: Iterable[PersonDetection], *, iou_threshold: float = 0.5
) -> tuple[PersonDetection, ...]:
    """以确定性置信度排序执行轻量 NMS，丢弃无效框。"""
    if not _is_finite_number(iou_threshold) or not 0 <= iou_threshold <= 1:
        raise ValueError("iou_threshold 必须在 0 到 1 之间")
    candidates = [
        detection
        for detection in detections
        if _is_valid_bbox(detection.bbox) and _is_valid_confidence(detection.confidence)
    ]
    candidates.sort(key=_detection_sort_key)
    selected: list[PersonDetection] = []
    for detection in candidates:
        if all(intersection_over_union(detection.bbox, kept.bbox) <= iou_threshold for kept in selected):
            selected.append(detection)
    return tuple(selected)


class CameraSnapshotStore:
    """按功能和摄像头编号隔离的线程安全不可变快照仓库。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshots: dict[tuple[str, int], CameraSnapshot] = {}

    def upsert(self, feature_name: str, snapshot: CameraSnapshot) -> CameraSnapshot:
        with self._lock:
            self._snapshots[(feature_name, snapshot.camera_id)] = snapshot
            return snapshot

    def get(self, feature_name: str, camera_id: int) -> CameraSnapshot | None:
        with self._lock:
            return self._snapshots.get((feature_name, camera_id))

    def remove(self, feature_name: str, camera_id: int) -> CameraSnapshot | None:
        with self._lock:
            return self._snapshots.pop((feature_name, camera_id), None)

    def clear_feature(self, feature_name: str) -> tuple[CameraSnapshot, ...]:
        with self._lock:
            keys = [key for key in self._snapshots if key[0] == feature_name]
            removed = tuple(self._snapshots.pop(key) for key in keys)
            return removed


def _decision(reason: ChannelReason, *, offending_camera_ids: tuple[int, ...] = ()) -> ChannelDecision:
    return ChannelDecision(
        reason=reason,
        alarm=False,
        duration_seconds=0.0,
        threshold_seconds=None,
        offending_camera_ids=offending_camera_ids,
    )


def _is_valid_bbox(bbox: tuple[float, float, float, float]) -> bool:
    if len(bbox) != 4 or not all(_is_finite_number(coordinate) for coordinate in bbox):
        return False
    x1, y1, x2, y2 = bbox
    return x2 > x1 and y2 > y1


def _is_valid_confidence(confidence: float) -> bool:
    return _is_finite_number(confidence) and 0 <= confidence <= 1


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _detection_sort_key(detection: PersonDetection) -> tuple[float, tuple[float, float, float, float], int]:
    return (-detection.confidence, detection.bbox, -1 if detection.source_roi is None else detection.source_roi)
