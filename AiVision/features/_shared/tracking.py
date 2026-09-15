"""
features/_shared/tracking.py
通用 IOU 多目标跟踪器

上一帧Tracking + 当前检测框，每一对计算IOU 、Center Distance、Area Similarity得到综合分数
综合分数大于等于0.35按分数从高到底贪心匹配，匹配成功，更新bbox/ velocity / last_seen
旧 Track 未匹配：lost 按跟踪更新次数加 1，velocity 预测 bbox，超过 MAX_LOST 时删除（默认允许 5 次）
新Detection未匹配，新建Track，first_seen=当前时间

"""
from __future__ import annotations
import time
from dataclasses import dataclass
from AiVision.features._shared import defaults

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
    first_seen: float               # 首次匹配时间；时间轴由 update(now=...) 的调用方决定
    last_seen: float                # 同一时间轴上的最后一次匹配时间
    velocity: tuple[float, float] = (0.0, 0.0)     # 描述上一帧到这一帧目标中心移动了多少像素
    lost: int = 0                   # 连续丢失的跟踪更新次数
    alarmed: bool = False           # 当前这个人是否已经进入告警状态

    @classmethod
    def new(cls, bbox: list[float], *, now: float | None = None) -> "Track":
        """新目标出现"""
        now = time.time() if now is None else now
        return cls(bbox=list(bbox), first_seen=now, last_seen=now)

    def update(self, bbox: list[float], smooth_alpha: float = defaults.TRACK_SMOOTH_ALPHA, *, now: float | None = None):
        """已有目标再次检测到"""
        # 计算旧框与新框的中心
        old_cx, old_cy = box_center(self.bbox)
        new_cx, new_cy = box_center(bbox)
        # 得到位移
        self.velocity = (new_cx - old_cx, new_cy - old_cy)
        # 检测框平滑Bt​=(1−α)Bt−1​+αBdet​，当前α = 0.7，旧框占 30%，新检测框占 70%(检测框中心会按这个去走)
        self.bbox = smooth_box(self.bbox, list(bbox), smooth_alpha)
        self.last_seen = time.time() if now is None else now
        self.lost = 0

    def step_lost(self):
        """如果当前帧没有检测到，lost+1"""
        self.lost += 1
        # 通过上一帧的bbox中心和velocity预测下一位置的中心
        if self.lost > 0:
            vx, vy = self.velocity
            self.bbox = [self.bbox[0] + vx, self.bbox[1] + vy, self.bbox[2] + vx, self.bbox[3] + vy]

    @property
    def dwell_time(self) -> float:
        # 逗留时间
        return self.last_seen - self.first_seen

class IouTracker:
    """基于 IoU + 中心点距离 + 面积变化的轻量多目标跟踪器
    
    中心点距离：框尺度归一化后采用欧式距离计算（中心位置分数0~1）
    面积相似度：使用这一帧的面积/上一帧的面积
    最终匹配分数：0.55*IOU分数 + 0.30* 中心距离分数 + 0.15*面积相似度分数

    用法:
        tracker = IouTracker(iou_thr=0.3, max_lost=5)
        for frame in stream:
            detections = [{"bbox": [...]}, ...]
            tracks = tracker.update(detections)
            for tid, track in tracks.items():
                if track.lost == 0 and track.dwell_time >= 10:
                    track.alarmed = True
                # 仅当前可见且 alarmed 的轨迹参与本次告警，通知由分发器控制冷却。
    """

    def __init__(
        self,
        iou_thr: float = defaults.TRACK_IOU_THR,
        max_lost: int = defaults.MAX_LOST,
        center_dist_thr: float = defaults.CENTER_DIST_THR,
        area_ratio_thr: float = defaults.AREA_RATIO_THR,
        match_score_thr: float = defaults.MATCH_SCORE_THR,
        smooth_alpha: float = defaults.TRACK_SMOOTH_ALPHA,
    ):
        self.iou_thr = iou_thr
        self.max_lost = max_lost
        self.center_dist_thr = center_dist_thr
        self.area_ratio_thr = area_ratio_thr
        self.match_score_thr = match_score_thr
        self.smooth_alpha = smooth_alpha
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, detections: list[dict], *, now: float | None = None) -> dict[int, Track]:
        """
        用当前帧检测结果刷新所有轨迹。

        当前是贪心匹配：
            会对每一个轨迹，以及当前检测到的每一个框做匹配，达到>=0.35的放进candidates
            然后按分数从高到低排序，匹配分数最高的（一对一匹配）
        
        detections: [{"bbox": [x1,y1,x2,y2], ...}, ...]
        返回更新后的 {track_id: Track}
        now：调用方提供的计时秒数；逗留检测使用扣除推理故障间隔的观测时间轴。
        """
        now = time.time() if now is None else now
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
            self._tracks[tid].update(detections[det_idx]["bbox"], smooth_alpha=self.smooth_alpha, now=now)
            used_tracks.add(tid)
            used_detections.add(det_idx)

        # 1）没匹配到的旧track就调用step_lost记录丢失一帧
        for tid, trk in list(self._tracks.items()):
            if tid in used_tracks:
                continue
            trk.step_lost()
            if trk.lost > self.max_lost:
                del self._tracks[tid]

        # 2) 未匹配的检测开新轨迹
        for i, det in enumerate(detections):
            if i not in used_detections:
                self._tracks[self._next_id] = Track.new(det["bbox"], now=now)
                self._next_id += 1

        return self._tracks

    def _match_score(self, track_box: list[float], det_box: list[float]) -> float:
        iou_score = iou(track_box, det_box)
        # 如果 IoU 低于配置的跟踪阈值，那么至少要求“中心还比较近，而且面积还比较像”。
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
