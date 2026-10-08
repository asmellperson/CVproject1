"""轻量多目标跟踪：综合 IoU、中心距离和面积相似度进行贪心一对一匹配。

只有达到配置的 match_score_thr 才参与匹配；丢失轨迹按上一位移预测位置，
超过 max_lost 次跟踪更新后移除。时间轴可由调用方注入，逗留检测可据此
排除观测故障期间的时间，避免把无有效画面的间隔算入停留时长。
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
        # 按配置权重在历史框与新检测框之间平滑，降低框位置的单帧抖动。
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
        """返回轨迹首次出现到最近一次更新之间的观测时长。"""
        return self.last_seen - self.first_seen

class IouTracker:
    """基于框重叠、归一化中心距离与尺度一致性的多目标跟踪器。

    面积相似度使用较小框面积与较大框面积之比。匹配得分由 IoU、中心距离
    和面积相似度加权，配置阈值决定候选是否可参与贪心匹配。

    Example:
        tracker = IouTracker(iou_thr=0.3, max_lost=5)
        tracks = tracker.update([{'bbox': [10, 20, 40, 80]}])
        visible = {key: track for key, track in tracks.items() if track.lost == 0}
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
        """设置匹配、丢失容忍和位置平滑参数，初始化独立的轨迹编号空间。"""
        self.iou_thr = iou_thr
        self.max_lost = max_lost
        self.center_dist_thr = center_dist_thr
        self.area_ratio_thr = area_ratio_thr
        self.match_score_thr = match_score_thr
        self.smooth_alpha = smooth_alpha
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, detections: list[dict], *, now: float | None = None) -> dict[int, Track]:
        """用当前检测刷新轨迹，未匹配检测创建新轨迹，长期丢失轨迹被移除。

        Args:
            detections: 含 bbox=[x1, y1, x2, y2] 的检测列表。
            now: 调用方时间轴上的秒数；省略时使用 time.time()。

        Returns:
            内部 track_id 到 Track 的映射，包含尚处丢失容忍期的轨迹。
            调用方统计当前可见目标时应过滤 lost != 0 的轨迹。
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
        """综合重叠、中心距离与面积相似度匹配，先排除明显不相容的候选框。"""
        iou_score = iou(track_box, det_box)
        # 如果 IoU 低于配置的跟踪阈值，那么至少要求“中心还比较近，而且面积还比较像”。
        center_score = 1.0 - min(1.0, center_distance_ratio(track_box, det_box) / max(self.center_dist_thr, 1e-6))
        area_score = area_similarity(track_box, det_box)
        if iou_score < self.iou_thr and (center_score <= 0 or area_score < self.area_ratio_thr):
            return 0.0
        return 0.55 * iou_score + 0.30 * center_score + 0.15 * area_score

    @property
    def tracks(self) -> dict[int, Track]:
        """返回内部轨迹映射，调用方应避免直接修改跟踪状态。"""
        return self._tracks

    def reset(self):
        """清空轨迹并重置编号，用于配置变更后重新开始跟踪。"""
        self._tracks.clear()
        self._next_id = 1

def box_center(box: list[float]) -> tuple[float, float]:
    """计算框中心，供空间距离匹配使用。"""
    return ((float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0)

def box_area(box: list[float]) -> float:
    """计算有效框面积，将倒置边界视为零面积。"""
    return max(0.0, float(box[2]) - float(box[0])) * max(0.0, float(box[3]) - float(box[1]))

def center_distance_ratio(box_a: list[float], box_b: list[float]) -> float:
    """按第一个框的最大边长归一化中心距离，降低目标尺度变化的影响。"""
    ax, ay = box_center(box_a)
    bx, by = box_center(box_b)
    aw = max(1.0, float(box_a[2]) - float(box_a[0]))
    ah = max(1.0, float(box_a[3]) - float(box_a[1]))
    scale = max(aw, ah, 1.0)
    return (((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5) / scale

def area_similarity(box_a: list[float], box_b: list[float]) -> float:
    """用较小面积与较大面积之比评估尺度一致性，退化框返回零。"""
    area_a = box_area(box_a)
    area_b = box_area(box_b)
    if area_a <= 0 or area_b <= 0:
        return 0.0
    return min(area_a, area_b) / max(area_a, area_b)

def smooth_box(old_box: list[float], new_box: list[float], alpha: float) -> list[float]:
    """限制平滑权重到零至一，在历史框与新框之间进行线性平滑。"""
    alpha = max(0.0, min(1.0, float(alpha)))
    return [
        float(old_value) * (1.0 - alpha) + float(new_value) * alpha
        for old_value, new_value in zip(old_box, new_box)
    ]
