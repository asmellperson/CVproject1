"""
================================================================================
session_worker.py —— 指纹锁定 + 交互检测版
================================================================================
核心改动：
  1. pair 锁定时记录"姿态指纹"（颜色直方图 + 几何特征），后续用指纹重识别
  2. 启动条件加入"交互特征"判断（距离稳定 + 至少一方移动）
  3. 结束条件改为"指纹丢失 N 秒" OR "交互停止 N 秒"
  4. 关键帧裁剪 padding 提到 100
  5. max_duration 改为"无新关键帧时长"而非"总时长"
================================================================================
"""
import argparse
import json
import pickle
import signal
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frame_hub import FrameHubReader, ResultStore, framehub_wait_timeout
from roi_geometry import (
    bbox_belongs_to_normalized_roi,
    normalize_roi_points,
    roi_bounds,
)


_STOP = threading.Event()


def _signal_handler(signum, frame):
    _STOP.set()


def _normalize_roi_mapping(
    rois,
    previous: Optional[Dict[str, List[List[float]]]] = None,
) -> Dict[str, List[List[float]]]:
    """逐项规范化 ROI；坏项保留同名旧值或忽略。"""
    if not isinstance(rois, dict):
        raise ValueError("staff_rois 必须是字典")
    last_known_good = previous or {}
    normalized = {}
    for name, values in rois.items():
        roi_name = str(name)
        try:
            normalized[roi_name] = normalize_roi_points(values)
        except (TypeError, ValueError, OverflowError) as exc:
            if roi_name in last_known_good:
                normalized[roi_name] = last_known_good[roi_name]
                action = "保留 last-known-good"
            else:
                action = "忽略新坏项"
            print(
                f"[session] ROI '{roi_name}' 无效，{action}: {exc}",
                flush=True,
            )
    return normalized


def reload_rois(
    roi_path: Path,
    roi_cache: Dict[str, List[List[float]]],
    roi_mtime: float,
) -> Tuple[Dict[str, List[List[float]]], float]:
    """按 mtime 热加载 ROI，并保留多边形的全部顶点。"""
    path = Path(roi_path)
    if not path.exists():
        return roi_cache, roi_mtime
    try:
        mtime = path.stat().st_mtime
        if mtime == roi_mtime:
            return roi_cache, roi_mtime
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("ROI 文件顶层必须是 JSON 对象")
        normalized = _normalize_roi_mapping(
            raw.get("staff_rois", {}),
            roi_cache,
        )
    except (
        OSError,
        ValueError,
        TypeError,
        OverflowError,
        json.JSONDecodeError,
    ) as exc:
        print(f"[session] 热加载失败: {exc}", flush=True)
        return roi_cache, roi_mtime
    print(f"[session] 热加载 ROI: {list(normalized.keys())}", flush=True)
    return normalized, mtime


# =====================================================================================
# 几何工具
# =====================================================================================

def bbox_center(box):
    x1, y1, x2, y2 = box
    return (x1 + x2) / 2, (y1 + y2) / 2


def bbox_distance(a, b):
    ax, ay = bbox_center(a)
    bx, by = bbox_center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def bbox_iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / max(ua, 1e-6)


def bbox_size(box):
    x1, y1, x2, y2 = box
    return (x2 - x1) * (y2 - y1)


# =====================================================================================
# 指纹：颜色直方图 + 几何特征
# =====================================================================================

def compute_fingerprint(frame, box):
    """
    截取 person bbox 的上半身 + 下半身各算一个 HSV 直方图,
    再加一个几何特征（高度、宽度）。轻量、无需额外模型。
    """
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in box]
    x1 = max(0, x1); y1 = max(0, y1)
    x2 = min(w, x2); y2 = min(h, y2)
    if x2 - x1 < 10 or y2 - y1 < 20:
        return None

    crop = frame[y1:y2, x1:x2]
    mid = (y2 - y1) // 2
    upper = crop[:mid]
    lower = crop[mid:]

    def hist(img):
        if img.size == 0:
            return np.zeros(48, dtype=np.float32)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        # H 16 bins + S 16 bins + V 16 bins
        h_hist = cv2.calcHist([hsv], [0], None, [16], [0, 180]).flatten()
        s_hist = cv2.calcHist([hsv], [1], None, [16], [0, 256]).flatten()
        v_hist = cv2.calcHist([hsv], [2], None, [16], [0, 256]).flatten()
        feat = np.concatenate([h_hist, s_hist, v_hist])
        n = np.linalg.norm(feat) + 1e-6
        return (feat / n).astype(np.float32)

    return {
        "upper": hist(upper),
        "lower": hist(lower),
        "height": float(y2 - y1),
        "width": float(x2 - x1),
    }


def fingerprint_similarity(fp1, fp2):
    """余弦相似度 + 几何相似度的加权"""
    if fp1 is None or fp2 is None:
        return 0.0
    color = 0.5 * float(fp1["upper"] @ fp2["upper"]) + \
            0.5 * float(fp1["lower"] @ fp2["lower"])
    h_ratio = min(fp1["height"], fp2["height"]) / max(fp1["height"], fp2["height"], 1e-6)
    geom = h_ratio
    return 0.7 * color + 0.3 * geom


# =====================================================================================
# 数据结构
# =====================================================================================

@dataclass
class TrackHist:
    """记录某个 track_id 最近的 bbox 序列,用于交互检测"""
    boxes: deque = field(default_factory=lambda: deque(maxlen=15))
    last_seen: float = 0.0


@dataclass
class PairSession:
    session_id: str
    roi_name: str
    roi_box: List[float]

    # 锁定时的 track id（仅作初始参考,后续靠指纹）
    init_track_a: int
    init_track_b: int

    # 指纹（核心身份）
    fp_a: Dict
    fp_b: Dict

    # 上次成功匹配时的 bbox（用于位置约束）
    last_box_a: List[float]
    last_box_b: List[float]

    start_ts: float
    last_match_ts: float = 0.0      # 最近一次两人都被找到
    last_interact_ts: float = 0.0   # 最近一次满足交互条件
    end_ts: float = -1

    keyframes: List[np.ndarray] = field(default_factory=list)
    last_kf_ts: float = 0.0


@dataclass
class RoiState:
    roi_name: str

    # track 历史（用于检测交互）
    track_hists: Dict[int, TrackHist] = field(default_factory=dict)

    # 候选 pair 累积
    candidate_pair: Optional[Tuple[int, int]] = None
    candidate_hold: int = 0

    # 活跃 session
    active: Optional[PairSession] = None


# =====================================================================================
# 主逻辑
# =====================================================================================

class PairSessionManager:

    def __init__(self, cfg, pending_dir):
        s = cfg["session"]
        data_cfg = cfg.get("data", {}) or {}
        self.camera_id = str(data_cfg.get("video_id", "stream") or "stream")
        self.camera_name = str(
            data_cfg.get("camera_name", self.camera_id) or self.camera_id
        )

        # 启动相关
        self.start_hold = int(s.get("pair_start_hold_frames", 8))

        # 结束相关（关键改动：分两类）
        self.fp_lost_seconds = float(s.get("fingerprint_lost_seconds", 3.0))
        self.no_interact_seconds = float(s.get("no_interact_seconds", 4.0))
        self.max_session_seconds = float(s.get("max_session_seconds", 90.0))

        # 关键帧
        self.kf_interval = float(s.get("keyframe_interval_sec", 0.6))
        self.max_kf = int(s.get("keyframes_per_session", 8))
        self.padding = int(s.get("roi_crop_padding", 100))

        # 指纹匹配阈值
        self.fp_match_threshold = float(s.get("fp_match_threshold", 0.55))

        # 交互检测参数
        self.interact_distance_max = float(s.get("interact_distance_max_ratio", 1.5))
        # ↑ 两人 bbox 中心距离 / 平均 bbox 高 < 此值 → 视为"贴近"
        self.interact_motion_min = float(s.get("interact_motion_min_pixels", 8.0))
        # ↑ 至少一方在最近 1 秒有 N 像素以上的位移 → 视为"有动作"

        # ROI 成员判定：进入严格、活动会话保持宽松，避免边缘抖动。
        self.roi_enter_overlap_ratio = min(
            1.0,
            max(0.0, float(s.get("roi_enter_overlap_ratio", 0.30))),
        )
        self.roi_hold_overlap_ratio = min(
            1.0,
            max(0.0, float(s.get("roi_hold_overlap_ratio", 0.10))),
        )
        if self.roi_hold_overlap_ratio > self.roi_enter_overlap_ratio:
            raise ValueError(
                "session.roi_hold_overlap_ratio 不能大于 "
                "session.roi_enter_overlap_ratio"
            )

        self.pending_dir = Path(pending_dir)
        self.pending_dir.mkdir(parents=True, exist_ok=True)

        self.roi_states: Dict[str, RoiState] = {}
        self.session_id = 0

    def _tracks_for_roi(self, tracks, roi, active: bool):
        """按进入/保持阈值返回当前 ROI 的人体轨迹。"""
        try:
            polygon = (
                roi
                if (
                    isinstance(roi, list)
                    and len(roi) >= 3
                    and all(isinstance(point, list) and len(point) == 2 for point in roi)
                )
                else normalize_roi_points(roi)
            )
        except (TypeError, ValueError, OverflowError):
            return []
        threshold = (
            self.roi_hold_overlap_ratio
            if active
            else self.roi_enter_overlap_ratio
        )
        return [
            track
            for track in tracks
            if bbox_belongs_to_normalized_roi(
                [track["x1"], track["y1"], track["x2"], track["y2"]],
                polygon,
                threshold,
            )
        ]

    def _reconcile_rois(self, rois) -> None:
        """移除已删除 ROI 的状态；活动会话直接取消且不进入 VLM 队列。"""
        removed_names = set(self.roi_states) - set(rois)
        for name in sorted(removed_names):
            state = self.roi_states.pop(name)
            if state.active is not None:
                print(
                    f"[session] ROI '{name}' 已删除，取消活动会话 "
                    f"{state.active.session_id}（不入 pending/VLM）",
                    flush=True,
                )
            else:
                print(f"[session] ROI '{name}' 已删除，清理状态", flush=True)

    # ---------------------------------------------------------------------------------
    # 1) 更新 track 历史（用于交互检测）
    # ---------------------------------------------------------------------------------
    def _update_track_hist(self, st: RoiState, tracks_in_roi):
        now = time.time()
        for t in tracks_in_roi:
            tid = t["track_id"]
            if tid not in st.track_hists:
                st.track_hists[tid] = TrackHist()
            box = [t["x1"], t["y1"], t["x2"], t["y2"]]
            st.track_hists[tid].boxes.append((now, box))
            st.track_hists[tid].last_seen = now

        # 清理超过 5 秒没出现的 track
        stale = [tid for tid, th in st.track_hists.items() if now - th.last_seen > 5.0]
        for tid in stale:
            del st.track_hists[tid]

    # ---------------------------------------------------------------------------------
    # 2) 计算单个 track 在最近 1 秒的位移量
    # ---------------------------------------------------------------------------------
    def _recent_motion(self, st: RoiState, tid):
        th = st.track_hists.get(tid)
        if th is None or len(th.boxes) < 2:
            return 0.0
        now = time.time()
        recent = [b for ts, b in th.boxes if now - ts <= 1.0]
        if len(recent) < 2:
            return 0.0
        cx0, cy0 = bbox_center(recent[0])
        cx1, cy1 = bbox_center(recent[-1])
        return ((cx1 - cx0) ** 2 + (cy1 - cy0) ** 2) ** 0.5

    # ---------------------------------------------------------------------------------
    # 3) 找最佳 pair：要求"贴近 + 至少一方有动作"
    # ---------------------------------------------------------------------------------
    def _find_interacting_pair(self, st: RoiState, tracks_in_roi):
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

                # 条件 1: 距离要"贴近但不重叠"
                dist = bbox_distance(box_a, box_b)
                avg_h = ((box_a[3] - box_a[1]) + (box_b[3] - box_b[1])) / 2.0
                if avg_h < 1:
                    continue
                dist_ratio = dist / avg_h
                if dist_ratio > self.interact_distance_max:
                    continue
                if dist_ratio < 0.2:
                    # 太重叠,可能是检测重复框
                    continue

                # 条件 2: 至少一方在动
                motion_a = self._recent_motion(st, a["track_id"])
                motion_b = self._recent_motion(st, b["track_id"])
                if max(motion_a, motion_b) < self.interact_motion_min:
                    continue

                # 评分：距离合适 + 一方动一方静（典型保安+受测者模式）
                # 鼓励"一方动一方相对静"的对
                motion_diff = abs(motion_a - motion_b)
                score = (1.0 / (1.0 + abs(dist_ratio - 0.8))) * \
                        (1.0 + motion_diff / max(motion_a + motion_b, 1.0))

                if score > best_score:
                    best_score = score
                    best = (a["track_id"], b["track_id"])

        return best

    # ---------------------------------------------------------------------------------
    # 4) 在当前帧的 ROI 内人群中,用指纹找回锁定的 pair
    # ---------------------------------------------------------------------------------
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
            return None, None, False, False

        # 加位置约束：和上次 box 的 IoU 加权
        def score(cand, last_box, sim):
            box = cand[0]
            iou = bbox_iou(box, last_box)
            return 0.7 * sim + 0.3 * iou

        # 选 a
        a_scores = [(score(c, sess.last_box_a, c[2]), c) for c in candidates]
        a_scores.sort(key=lambda x: x[0], reverse=True)
        best_a = a_scores[0] if a_scores and a_scores[0][0] > self.fp_match_threshold else None

        # 选 b（不能和 a 是同一个 box）
        b_scores = []
        for c in candidates:
            if best_a and c[0] == best_a[1][0]:
                continue
            b_scores.append((score(c, sess.last_box_b, c[3]), c))
        b_scores.sort(key=lambda x: x[0], reverse=True)
        best_b = b_scores[0] if b_scores and b_scores[0][0] > self.fp_match_threshold else None

        box_a = best_a[1][0] if best_a else None
        box_b = best_b[1][0] if best_b else None

        # 找到的话顺便更新指纹（指数滑动平均,适应衣服褶皱、光照变化）
        if best_a:
            new_fp = best_a[1][1]
            sess.fp_a = self._ema_fp(sess.fp_a, new_fp, alpha=0.1)
            sess.last_box_a = box_a
        if best_b:
            new_fp = best_b[1][1]
            sess.fp_b = self._ema_fp(sess.fp_b, new_fp, alpha=0.1)
            sess.last_box_b = box_b

        return box_a, box_b, best_a is not None, best_b is not None

    @staticmethod
    def _ema_fp(old, new, alpha=0.1):
        if old is None:
            return new
        return {
            "upper": (1 - alpha) * old["upper"] + alpha * new["upper"],
            "lower": (1 - alpha) * old["lower"] + alpha * new["lower"],
            "height": (1 - alpha) * old["height"] + alpha * new["height"],
            "width": (1 - alpha) * old["width"] + alpha * new["width"],
        }

    # ---------------------------------------------------------------------------------
    # 5) 判断当前 box_a / box_b 是否仍在交互
    # ---------------------------------------------------------------------------------
    def _still_interacting(self, st: RoiState, sess: PairSession, box_a, box_b):
        if box_a is None or box_b is None:
            return False
        dist = bbox_distance(box_a, box_b)
        avg_h = ((box_a[3] - box_a[1]) + (box_b[3] - box_b[1])) / 2.0
        if avg_h < 1:
            return False
        dist_ratio = dist / avg_h
        if dist_ratio > self.interact_distance_max * 1.3:
            # 比启动条件宽松 30%（允许保安蹲下时距离变化）
            return False
        # 不再强制要求位移,因为保安可能短暂静止讲解
        return True

    # ---------------------------------------------------------------------------------
    # 6) 裁剪关键帧
    # ---------------------------------------------------------------------------------
    def _crop_pair(self, frame, box_a, box_b):
        if box_a is None and box_b is None:
            return None
        boxes = [b for b in (box_a, box_b) if b is not None]
        x1 = min(b[0] for b in boxes)
        y1 = min(b[1] for b in boxes)
        x2 = max(b[2] for b in boxes)
        y2 = max(b[3] for b in boxes)

        h, w = frame.shape[:2]
        x1 = max(0, int(x1 - self.padding))
        y1 = max(0, int(y1 - self.padding))
        x2 = min(w, int(x2 + self.padding))
        y2 = min(h, int(y2 + self.padding))
        return frame[y1:y2, x1:x2].copy()

    # ---------------------------------------------------------------------------------
    # 7) 落盘
    # ---------------------------------------------------------------------------------
    def _finalize(self, sess: PairSession):
        if len(sess.keyframes) < 2:
            return  # 太少帧不送 VLM,直接丢
        path = self.pending_dir / f"{sess.session_id}.pkl"
        temp_path = path.with_suffix(".pkl.tmp")
        try:
            with open(temp_path, "wb") as f:
                pickle.dump({
                    "session_id": sess.session_id,
                    "camera_id": self.camera_id,
                    "camera_name": self.camera_name,
                    "roi_name": sess.roi_name,
                    "roi_box": sess.roi_box,
                    "start_ts": sess.start_ts,
                    "end_ts": sess.end_ts,
                    "enqueue_ts": time.time(),
                    "keyframes": sess.keyframes,
                }, f)
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)
        print(f"[session] 落盘 {sess.session_id}, {len(sess.keyframes)} 帧, "
              f"时长 {sess.end_ts - sess.start_ts:.1f}s", flush=True)

    # ---------------------------------------------------------------------------------
    # 8) 主更新
    # ---------------------------------------------------------------------------------
    def step(self, frame, tracks, rois):
        now = time.time()
        self._reconcile_rois(rois)

        for name, roi in rois.items():
            if name not in self.roi_states:
                self.roi_states[name] = RoiState(name)
            st = self.roi_states[name]

            # 8.1 新会话使用进入阈值，活动会话使用更宽松的保持阈值。
            tracks_in_roi = self._tracks_for_roi(
                tracks,
                roi,
                active=st.active is not None,
            )

            # 8.2 更新 track 历史
            self._update_track_hist(st, tracks_in_roi)

            # ============================================================
            # 8.3 没有 active session → 找候选 pair
            # ============================================================
            if st.active is None:
                pair = self._find_interacting_pair(st, tracks_in_roi)
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
                    # 启动 session,提取指纹
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

                    self.session_id += 1
                    sess = PairSession(
                        session_id=(
                            f"{self.camera_id}_{time.time_ns()}_{self.session_id}"
                        ),
                        roi_name=name,
                        roi_box=roi_bounds(roi),
                        init_track_a=pair[0],
                        init_track_b=pair[1],
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
                    print(f"[session] 启动 {sess.session_id} "
                          f"pair=({pair[0]},{pair[1]})", flush=True)
                continue

            # ============================================================
            # 8.4 已有 session → 用指纹找回 pair
            # ============================================================
            sess = st.active
            box_a, box_b, found_a, found_b = self._refind_by_fingerprint(
                frame, sess, tracks_in_roi)

            if found_a and found_b:
                sess.last_match_ts = now
                if self._still_interacting(st, sess, box_a, box_b):
                    sess.last_interact_ts = now

            # 8.5 结束条件
            fp_lost = (now - sess.last_match_ts) > self.fp_lost_seconds
            no_interact = (now - sess.last_interact_ts) > self.no_interact_seconds
            too_long = (now - sess.start_ts) > self.max_session_seconds

            if fp_lost or no_interact or too_long:
                reason = ("fp_lost" if fp_lost else
                          "no_interact" if no_interact else "too_long")
                sess.end_ts = now
                print(f"[session] 结束 {sess.session_id} reason={reason}", flush=True)
                self._finalize(sess)
                st.active = None
                continue

            # 8.6 采样关键帧（只在两人都被找到时）
            if found_a and found_b and len(sess.keyframes) < self.max_kf:
                if now - sess.last_kf_ts > self.kf_interval:
                    crop = self._crop_pair(frame, box_a, box_b)
                    if crop is not None and crop.size > 0:
                        sess.keyframes.append(crop)
                        sess.last_kf_ts = now


# =====================================================================================
# 主入口（基本同你原来的,加了心跳上报）
# =====================================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    cfg = yaml.safe_load(open(args.config))
    runtime_dir = Path(cfg["runtime"]["dir"])
    store = ResultStore(runtime_dir)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    hub = FrameHubReader(
        runtime_dir,
        wait_timeout_sec=framehub_wait_timeout(cfg),
    )
    manager = PairSessionManager(cfg, cfg["session"]["pending_queue_dir"])

    last_status_ts = 0.0
    last_frame_id = -1

    # 热加载 ROI（mtime 检测）
    roi_path = (
        Path(cfg["data"]["staff_identity_dir"])
        / f"{cfg['data']['video_id']}_staff_rois.json"
    )
    try:
        roi_cache = _normalize_roi_mapping(cfg.get("staff_rois") or {})
    except ValueError as exc:
        print(f"[session] 默认 ROI 配置无效: {exc}", flush=True)
        roi_cache = {}
    roi_mtime = 0.0

    while not _STOP.is_set():
        try:
            meta = hub.get_latest_meta()
            frame_id = int(meta.get("frame_id", -1))
            if frame_id < 0 or frame_id == last_frame_id:
                time.sleep(0.01)
                continue

            tracker_data = store.read("tracker_latest", {}) or {}
            if int(tracker_data.get("frame_id", -1)) != frame_id:
                # tracker 还没出当前帧的结果
                time.sleep(0.01)
                continue

            frame = hub.read_frame(meta)
            tracks = tracker_data.get("tracks", []) or []
            roi_cache, roi_mtime = reload_rois(
                roi_path,
                roi_cache,
                roi_mtime,
            )
            rois = roi_cache

            manager.step(frame, tracks, rois)
            last_frame_id = frame_id

            # 心跳 + 当前状态
            now = time.time()
            if now - last_status_ts > 1.0:
                per_roi = {}
                for name in rois:
                    st = manager.roi_states[name]
                    per_roi[name] = {
                        "active_session_id": st.active.session_id if st.active else None,
                        "persons_in_roi": len(manager._tracks_for_roi(
                            tracks,
                            rois.get(name, []),
                            active=False,
                        )),
                    }
                store.write("session_latest", {
                    "ok": True,
                    "ts": now,
                    "frame_id": frame_id,
                    "per_roi": per_roi,
                    "staff_rois": rois,
                })
                last_status_ts = now

        except Exception as e:
            print(f"[session] error: {e}", flush=True)
            time.sleep(0.1)


if __name__ == "__main__":
    main()
