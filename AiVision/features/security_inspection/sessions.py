"""人员交互配对、指纹跟随和关键帧采样；不管理进程、文件或模型。"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from uuid import uuid4
import cv2
import numpy as np
from .geometry import bbox_in_roi
from .schema import InspectionValue


def bbox_center(box):
    """返回人体框中心，供配对距离及运动量计算。"""
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def bbox_distance(a, b):
    """计算两个人体框中心间的欧氏距离。"""
    ax, ay = bbox_center(a)
    bx, by = bbox_center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def bbox_iou(a, b):
    """计算人体框重叠程度，用于外观匹配时的位置约束。"""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = (max(ax1, bx1), max(ay1, by1))
    ix2, iy2 = (min(ax2, bx2), min(ay2, by2))
    iw, ih = (max(0, ix2 - ix1), max(0, iy2 - iy1))
    inter = iw * ih
    if inter == 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / max(ua, 1e-06)


def compute_fingerprint(frame, box):
    """
    截取 person bbox 的上半身 + 下半身各算一个 HSV 直方图,
    再加高度几何特征。轻量、无需额外模型。
    """
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in box]
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)
    if x2 - x1 < 10 or y2 - y1 < 20:
        return None
    crop = frame[y1:y2, x1:x2]
    mid = (y2 - y1) // 2
    upper = crop[:mid]
    lower = crop[mid:]

    def hist(img):
        """分别归一化 HSV 直方图，空裁图返回固定维度零向量。"""
        if img.size == 0:
            return np.zeros(48, dtype=np.float32)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h_hist = cv2.calcHist([hsv], [0], None, [16], [0, 180]).flatten()
        s_hist = cv2.calcHist([hsv], [1], None, [16], [0, 256]).flatten()
        v_hist = cv2.calcHist([hsv], [2], None, [16], [0, 256]).flatten()
        feat = np.concatenate([h_hist, s_hist, v_hist])
        n = np.linalg.norm(feat) + 1e-06
        return (feat / n).astype(np.float32)

    return {"upper": hist(upper), "lower": hist(lower), "height": float(y2 - y1)}


def fingerprint_similarity(fp1, fp2):
    """余弦相似度 + 几何相似度的加权"""
    if fp1 is None or fp2 is None:
        return 0.0
    color = 0.5 * float(fp1["upper"] @ fp2["upper"]) + 0.5 * float(fp1["lower"] @ fp2["lower"])
    h_ratio = min(fp1["height"], fp2["height"]) / max(fp1["height"], fp2["height"], 1e-06)
    geom = h_ratio
    return 0.7 * color + 0.3 * geom


@dataclass
class TrackHist:
    """记录某个 track_id 最近的 bbox 序列,用于交互检测"""

    boxes: deque = field(default_factory=lambda: deque(maxlen=15))
    last_seen: float = 0.0


@dataclass
class PairSession:
    """保存一次人员交互的双人外观、位置、时间边界及关键帧。"""
    session_id: str
    roi_name: str
    fp_a: Dict
    fp_b: Dict
    last_box_a: List[float]
    last_box_b: List[float]
    start_ts: float
    last_match_ts: float = 0.0
    last_interact_ts: float = 0.0
    end_ts: float = -1
    keyframes: List[np.ndarray] = field(default_factory=list)
    last_kf_ts: float = 0.0


@dataclass
class RoiState:
    """隔离一个 ROI 的轨迹历史、候选配对与当前交互会话。"""
    track_hists: Dict[int, TrackHist] = field(default_factory=dict)
    candidate_pair: Optional[Tuple[int, int]] = None
    candidate_hold: int = 0
    active: Optional[PairSession] = None


class PairSessionManager:
    """从人体轨迹确认交互配对，用外观指纹跟随并采集判定关键帧。"""
    def __init__(self, config: InspectionValue):
        """固定当前配置的配对、丢失容忍和关键帧策略，建立独立 ROI 状态。"""
        self.start_hold = config.pair_start_hold_frames
        self.fp_lost_seconds = config.fingerprint_lost_seconds
        self.no_interact_seconds = config.no_interact_seconds
        self.max_session_seconds = config.max_session_seconds
        self.kf_interval = config.keyframe_interval_sec
        self.max_kf = config.keyframes_per_session
        self.padding = config.roi_crop_padding
        self.fp_match_threshold = config.fp_match_threshold
        self.interact_distance_max = config.interact_distance_max_ratio
        self.interact_motion_min = config.interact_motion_min_pixels
        self.roi_enter_overlap_ratio = config.roi_enter_overlap_ratio
        self.roi_hold_overlap_ratio = config.roi_hold_overlap_ratio
        self.roi_states: dict[str, RoiState] = {}

    def _tracks_for_roi(self, tracks, roi, active):
        """按会话是否已开始选择进入或保持阈值，减少边缘出入抖动。"""
        threshold = self.roi_hold_overlap_ratio if active else self.roi_enter_overlap_ratio
        return [
            track
            for track in tracks
            if bbox_in_roi([track["x1"], track["y1"], track["x2"], track["y2"]], roi, threshold)
        ]

    def _update_track_hist(self, st: RoiState, tracks_in_roi, now):
        """维护人体近期位置历史，并移除长期未出现的轨迹。"""
        for t in tracks_in_roi:
            tid = t["track_id"]
            if tid not in st.track_hists:
                st.track_hists[tid] = TrackHist()
            box = [t["x1"], t["y1"], t["x2"], t["y2"]]
            st.track_hists[tid].boxes.append((now, box))
            st.track_hists[tid].last_seen = now
        stale = [tid for tid, th in st.track_hists.items() if now - th.last_seen > 5.0]
        for tid in stale:
            del st.track_hists[tid]

    def _recent_motion(self, st: RoiState, tid, now):
        """使用最近一秒内的首末中心位移衡量运动量。"""
        th = st.track_hists.get(tid)
        if th is None or len(th.boxes) < 2:
            return 0.0
        recent = [b for ts, b in th.boxes if now - ts <= 1.0]
        if len(recent) < 2:
            return 0.0
        cx0, cy0 = bbox_center(recent[0])
        cx1, cy1 = bbox_center(recent[-1])
        return ((cx1 - cx0) ** 2 + (cy1 - cy0) ** 2) ** 0.5

    def _find_interacting_pair(self, st: RoiState, tracks_in_roi, now):
        """根据相对距离与运动差异选择最可信的双人交互候选。"""
        if len(tracks_in_roi) < 2:
            return None
        best = None
        best_score = -1.0
        for i in range(len(tracks_in_roi)):
            for j in range(i + 1, len(tracks_in_roi)):
                a = tracks_in_roi[i]
                b = tracks_in_roi[j]
                box_a = [a["x1"], a["y1"], a["x2"], a["y2"]]
                box_b = [b["x1"], b["y1"], b["x2"], b["y2"]]
                dist = bbox_distance(box_a, box_b)
                avg_h = (box_a[3] - box_a[1] + (box_b[3] - box_b[1])) / 2.0
                if avg_h < 1:
                    continue
                dist_ratio = dist / avg_h
                if dist_ratio > self.interact_distance_max:
                    continue
                if dist_ratio < 0.2:
                    continue
                motion_a = self._recent_motion(st, a["track_id"], now)
                motion_b = self._recent_motion(st, b["track_id"], now)
                if max(motion_a, motion_b) < self.interact_motion_min:
                    continue
                motion_diff = abs(motion_a - motion_b)
                score = 1.0 / (1.0 + abs(dist_ratio - 0.8)) * (1.0 + motion_diff / max(motion_a + motion_b, 1.0))
                if score > best_score:
                    best_score = score
                    best = (a["track_id"], b["track_id"])
        return best

    def _refind_by_fingerprint(self, frame, sess: PairSession, tracks_in_roi):
        """
        返回 (box_a, box_b, found_a, found_b),允许任一方暂时丢失。
        """
        candidates = []
        for t in tracks_in_roi:
            box = [t["x1"], t["y1"], t["x2"], t["y2"]]
            fp = compute_fingerprint(frame, box)
            if fp is None:
                continue
            sim_a = fingerprint_similarity(sess.fp_a, fp)
            sim_b = fingerprint_similarity(sess.fp_b, fp)
            candidates.append((box, fp, sim_a, sim_b))
        if not candidates:
            return (None, None, False, False)

        def score(cand, last_box, sim):
            """综合外观相似度与历史框重叠，为身份重关联候选排序。"""
            box = cand[0]
            iou = bbox_iou(box, last_box)
            return 0.7 * sim + 0.3 * iou

        a_scores = [(score(c, sess.last_box_a, c[2]), c) for c in candidates]
        a_scores.sort(key=lambda x: x[0], reverse=True)
        best_a = a_scores[0] if a_scores and a_scores[0][0] > self.fp_match_threshold else None
        b_scores = []
        for c in candidates:
            if best_a and c[0] == best_a[1][0]:
                continue
            b_scores.append((score(c, sess.last_box_b, c[3]), c))
        b_scores.sort(key=lambda x: x[0], reverse=True)
        best_b = b_scores[0] if b_scores and b_scores[0][0] > self.fp_match_threshold else None
        box_a = best_a[1][0] if best_a else None
        box_b = best_b[1][0] if best_b else None
        if best_a:
            new_fp = best_a[1][1]
            sess.fp_a = self._ema_fp(sess.fp_a, new_fp, alpha=0.1)
            sess.last_box_a = box_a
        if best_b:
            new_fp = best_b[1][1]
            sess.fp_b = self._ema_fp(sess.fp_b, new_fp, alpha=0.1)
            sess.last_box_b = box_b
        return (box_a, box_b, best_a is not None, best_b is not None)

    @staticmethod
    def _ema_fp(old, new, alpha=0.1):
        """缓慢更新上下身外观和高度特征，减轻单帧外观波动。"""
        return {
            "upper": (1 - alpha) * old["upper"] + alpha * new["upper"],
            "lower": (1 - alpha) * old["lower"] + alpha * new["lower"],
            "height": (1 - alpha) * old["height"] + alpha * new["height"],
        }

    def _still_interacting(self, box_a, box_b):
        """使用比启动更宽松的距离阈值维持已有交互。"""
        if box_a is None or box_b is None:
            return False
        dist = bbox_distance(box_a, box_b)
        avg_h = (box_a[3] - box_a[1] + (box_b[3] - box_b[1])) / 2.0
        if avg_h < 1:
            return False
        dist_ratio = dist / avg_h
        if dist_ratio > self.interact_distance_max * 1.3:
            return False
        return True

    def _crop_pair(self, frame, box_a, box_b):
        """截取双人联合范围并加入边距，复制图像以独立保存关键帧。"""
        if box_a is None and box_b is None:
            return None
        boxes = [b for b in (box_a, box_b) if b is not None]
        x1 = min((b[0] for b in boxes))
        y1 = min((b[1] for b in boxes))
        x2 = max((b[2] for b in boxes))
        y2 = max((b[3] for b in boxes))
        h, w = frame.shape[:2]
        x1 = max(0, int(x1 - self.padding))
        y1 = max(0, int(y1 - self.padding))
        x2 = min(w, int(x2 + self.padding))
        y2 = min(h, int(y2 + self.padding))
        return frame[y1:y2, x1:x2].copy()

    def step(self, frame, tracks, rois, now: float):
        """推进各 ROI 的配对会话，返回已结束且至少含两张关键帧的会话。

        候选需持续命中才启动；外观失配、交互中断或最大时长到达均结束会话。
        仅在两人同时找回时采样，并限制关键帧间隔和总数量。
        """
        completed = []
        for name, roi in rois.items():
            if name not in self.roi_states:
                self.roi_states[name] = RoiState()
            st = self.roi_states[name]
            tracks_in_roi = self._tracks_for_roi(tracks, roi, active=st.active is not None)
            self._update_track_hist(st, tracks_in_roi, now)
            if st.active is None:
                pair = self._find_interacting_pair(st, tracks_in_roi, now)
                if pair is None:
                    st.candidate_hold = 0
                    st.candidate_pair = None
                    continue
                if pair == st.candidate_pair:
                    st.candidate_hold += 1
                else:
                    st.candidate_pair = pair
                    st.candidate_hold = 1
                if st.candidate_hold >= self.start_hold:
                    box_a = box_b = None
                    for t in tracks_in_roi:
                        if t["track_id"] == pair[0]:
                            box_a = [t["x1"], t["y1"], t["x2"], t["y2"]]
                        elif t["track_id"] == pair[1]:
                            box_b = [t["x1"], t["y1"], t["x2"], t["y2"]]
                    if box_a is None or box_b is None:
                        continue
                    fp_a = compute_fingerprint(frame, box_a)
                    fp_b = compute_fingerprint(frame, box_b)
                    if fp_a is None or fp_b is None:
                        continue
                    sess = PairSession(
                        session_id=uuid4().hex,
                        roi_name=name,
                        fp_a=fp_a,
                        fp_b=fp_b,
                        last_box_a=box_a,
                        last_box_b=box_b,
                        start_ts=now,
                        last_match_ts=now,
                        last_interact_ts=now,
                    )
                    st.active = sess
                    st.candidate_hold = 0
                continue
            sess = st.active
            box_a, box_b, found_a, found_b = self._refind_by_fingerprint(frame, sess, tracks_in_roi)
            if found_a and found_b:
                sess.last_match_ts = now
                if self._still_interacting(box_a, box_b):
                    sess.last_interact_ts = now
            fp_lost = now - sess.last_match_ts > self.fp_lost_seconds
            no_interact = now - sess.last_interact_ts > self.no_interact_seconds
            too_long = now - sess.start_ts > self.max_session_seconds
            if fp_lost or no_interact or too_long:
                sess.end_ts = now
                if len(sess.keyframes) >= 2:
                    completed.append(sess)
                st.active = None
                continue
            if found_a and found_b and (len(sess.keyframes) < self.max_kf):
                if now - sess.last_kf_ts > self.kf_interval:
                    crop = self._crop_pair(frame, box_a, box_b)
                    if crop is not None and crop.size > 0:
                        sess.keyframes.append(crop)
                        sess.last_kf_ts = now
        return completed
