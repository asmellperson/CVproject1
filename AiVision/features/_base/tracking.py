"""
features/_base/tracking.py
通用 IOU 多目标跟踪器 — 消除 detect_face / detect_human 里完全相同的 Track / Tracker 重复实现。

旧代码: face 和 human 各有一套 FaceTrack/FaceTracker、HumanTrack/HumanTracker,
        除了类名什么都一样。
新代码: 一份 IouTracker 通用实现,两个 feature 直接复用。
"""
from __future__ import annotations
import time
from dataclasses import dataclass


def iou(box_a: list[float], box_b: list[float]) -> float:
    """计算两个 bbox 的 IoU,bbox 格式 [x1, y1, x2, y2]"""
    x1, y1, x2, y2 = box_a
    x1p, y1p, x2p, y2p = box_b
    xi1, yi1 = max(x1, x1p), max(y1, y1p)
    xi2, yi2 = min(x2, x2p), min(y2, y2p)
    inter = max(0.0, xi2 - xi1) * max(0.0, yi2 - yi1)
    area_a = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_b = max(0.0, x2p - x1p) * max(0.0, y2p - y1p)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Track:
    """单个跟踪轨迹"""
    bbox: list[float]
    first_seen: float
    last_seen: float
    velocity: tuple[float, float] = (0.0, 0.0)
    lost: int = 0
    alarmed: bool = False

    @classmethod
    def new(cls, bbox: list[float]) -> "Track":
        now = time.time()
        return cls(bbox=list(bbox), first_seen=now, last_seen=now)

    def update(self, bbox: list[float], smooth_alpha: float = 0.7):
        old_cx, old_cy = box_center(self.bbox)
        new_cx, new_cy = box_center(bbox)
        self.velocity = (new_cx - old_cx, new_cy - old_cy)
        self.bbox = smooth_box(self.bbox, list(bbox), smooth_alpha)
        self.last_seen = time.time()
        self.lost = 0

    def step_lost(self):
        self.lost += 1
        if self.lost > 0:
            vx, vy = self.velocity
            self.bbox = [self.bbox[0] + vx, self.bbox[1] + vy, self.bbox[2] + vx, self.bbox[3] + vy]

    @property
    def dwell_time(self) -> float:
        return self.last_seen - self.first_seen


class IouTracker:
    """基于 IoU + 中心点距离 + 面积变化的轻量多目标跟踪器
    
    用法:
        tracker = IouTracker(iou_thr=0.3, max_lost=5)
        for frame in stream:
            detections = [{"bbox": [...]}, ...]
            tracks = tracker.update(detections)
            for tid, track in tracks.items():
                if track.dwell_time > 10 and not track.alarmed:
                    ...告警...
                    track.alarmed = True
    """

    def __init__(
        self,
        iou_thr: float = 0.3,
        max_lost: int = 5,
        center_dist_thr: float = 0.65,
        area_ratio_thr: float = 0.55,
        match_score_thr: float = 0.35,
        smooth_alpha: float = 0.7,
    ):
        self.iou_thr = iou_thr
        self.max_lost = max_lost
        self.center_dist_thr = center_dist_thr
        self.area_ratio_thr = area_ratio_thr
        self.match_score_thr = match_score_thr
        self.smooth_alpha = smooth_alpha
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, detections: list[dict]) -> dict[int, Track]:
        """用当前帧检测结果刷新所有轨迹。
        
        detections: [{"bbox": [x1,y1,x2,y2], ...}, ...]
        返回更新后的 {track_id: Track}
        """
        used_tracks: set[int] = set()
        used_detections: set[int] = set()
        candidates = []

        for tid, trk in self._tracks.items():
            for det_idx, det in enumerate(detections):
                score = self._match_score(trk.bbox, det["bbox"])
                if score >= self.match_score_thr:
                    candidates.append((score, tid, det_idx))

        for _score, tid, det_idx in sorted(candidates, key=lambda item: item[0], reverse=True):
            if tid in used_tracks or det_idx in used_detections or tid not in self._tracks:
                continue
            self._tracks[tid].update(detections[det_idx]["bbox"], smooth_alpha=self.smooth_alpha)
            used_tracks.add(tid)
            used_detections.add(det_idx)

        for tid, trk in list(self._tracks.items()):
            if tid in used_tracks:
                continue
            trk.step_lost()
            if trk.lost > self.max_lost:
                del self._tracks[tid]

        # 2) 未匹配的检测开新轨迹
        for i, det in enumerate(detections):
            if i not in used_detections:
                self._tracks[self._next_id] = Track.new(det["bbox"])
                self._next_id += 1

        return self._tracks

    def _match_score(self, track_box: list[float], det_box: list[float]) -> float:
        iou_score = iou(track_box, det_box)
        center_score = 1.0 - min(1.0, center_distance_ratio(track_box, det_box) / max(self.center_dist_thr, 1e-6))
        area_score = area_similarity(track_box, det_box)
        if iou_score < self.iou_thr and (center_score <= 0 or area_score < self.area_ratio_thr):
            return 0.0
        return 0.55 * iou_score + 0.30 * center_score + 0.15 * area_score

    @property
    def tracks(self) -> dict[int, Track]:
        return self._tracks

    def reset(self):
        self._tracks.clear()
        self._next_id = 1


def box_center(box: list[float]) -> tuple[float, float]:
    return ((float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0)


def box_area(box: list[float]) -> float:
    return max(0.0, float(box[2]) - float(box[0])) * max(0.0, float(box[3]) - float(box[1]))


def center_distance_ratio(box_a: list[float], box_b: list[float]) -> float:
    ax, ay = box_center(box_a)
    bx, by = box_center(box_b)
    aw = max(1.0, float(box_a[2]) - float(box_a[0]))
    ah = max(1.0, float(box_a[3]) - float(box_a[1]))
    scale = max(aw, ah, 1.0)
    return (((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5) / scale


def area_similarity(box_a: list[float], box_b: list[float]) -> float:
    area_a = box_area(box_a)
    area_b = box_area(box_b)
    if area_a <= 0 or area_b <= 0:
        return 0.0
    return min(area_a, area_b) / max(area_a, area_b)


def smooth_box(old_box: list[float], new_box: list[float], alpha: float) -> list[float]:
    alpha = max(0.0, min(1.0, float(alpha)))
    return [
        float(old_value) * (1.0 - alpha) + float(new_value) * alpha
        for old_value, new_value in zip(old_box, new_box)
    ]
