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
    lost: int = 0
    alarmed: bool = False

    @classmethod
    def new(cls, bbox: list[float]) -> "Track":
        now = time.time()
        return cls(bbox=list(bbox), first_seen=now, last_seen=now)

    def update(self, bbox: list[float]):
        self.bbox = list(bbox)
        self.last_seen = time.time()
        self.lost = 0

    def step_lost(self):
        self.lost += 1

    @property
    def dwell_time(self) -> float:
        return self.last_seen - self.first_seen


class IouTracker:
    """基于贪心 IOU 匹配的多目标跟踪器
    
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

    def __init__(self, iou_thr: float = 0.3, max_lost: int = 5):
        self.iou_thr = iou_thr
        self.max_lost = max_lost
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, detections: list[dict]) -> dict[int, Track]:
        """用当前帧检测结果刷新所有轨迹。
        
        detections: [{"bbox": [x1,y1,x2,y2], ...}, ...]
        返回更新后的 {track_id: Track}
        """
        used = set()

        # 1) 现有轨迹尝试匹配
        for tid, trk in list(self._tracks.items()):
            best_iou, best_idx = 0.0, None
            for i, det in enumerate(detections):
                if i in used:
                    continue
                score = iou(trk.bbox, det["bbox"])
                if score > best_iou:
                    best_iou, best_idx = score, i
            if best_idx is not None and best_iou > self.iou_thr:
                trk.update(detections[best_idx]["bbox"])
                used.add(best_idx)
            else:
                trk.step_lost()
                if trk.lost > self.max_lost:
                    del self._tracks[tid]

        # 2) 未匹配的检测开新轨迹
        for i, det in enumerate(detections):
            if i not in used:
                self._tracks[self._next_id] = Track.new(det["bbox"])
                self._next_id += 1

        return self._tracks

    @property
    def tracks(self) -> dict[int, Track]:
        return self._tracks

    def reset(self):
        self._tracks.clear()
        self._next_id = 1
