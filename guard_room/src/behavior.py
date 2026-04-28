# behavior.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .config import AppConfig
from .types import Detection
from collections import deque
from typing import Deque


@dataclass
class RuleDecision:
    active: bool = False
    reason: str = ""
    confidence: float = 0.0
    track_id: int | None = None


@dataclass
class PersonRuntimeState:
    track_id: int
    last_bbox: tuple[int, int, int, int]
    last_center: tuple[float, float]
    last_seen_ts: float
    motion_score: float = 0.0

    # 旧的 phone_frames 不再用
    phone_hit_ts: Deque[float] = field(default_factory=deque)
    phone_active_seconds: float = 0.0
    last_phone_eval_ts: float = 0.0
    last_phone_positive_ts: float = -9999.0

    prone_frames: int = 0
    head_down_frames: int = 0


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _inside_expand(point: tuple[float, float], bbox: tuple[int, int, int, int], pad_x: float, pad_y: float) -> bool:
    x1, y1, x2, y2 = bbox
    return (x1 - pad_x) <= point[0] <= (x2 + pad_x) and (y1 - pad_y) <= point[1] <= (y2 + pad_y)


class BehaviorEngine:
    def __init__(self, config: AppConfig):
        self.cfg = config
        self.person_states: Dict[int, PersonRuntimeState] = {}
        self.absent_started_at: float | None = None

    def update(
        self,
        *,
        timestamp_s: float,
        fps: float,
        frame_shape: tuple[int, int, int],
        persons: List[Detection],
        phones: List[Detection],
        pose_features: Dict[int, Dict[str, float]],
    ) -> Dict[str, RuleDecision]:
        self._cleanup_states(timestamp_s)
        decisions: Dict[str, RuleDecision] = {
            "absent": RuleDecision(),
            "phone": RuleDecision(),
            "prone_sleep": RuleDecision(),
        }

        if not persons:
            if self.absent_started_at is None:
                self.absent_started_at = timestamp_s
            absent_for = timestamp_s - self.absent_started_at
            if absent_for >= self.cfg.rules.absent_seconds:
                decisions["absent"] = RuleDecision(
                    active=True,
                    reason=f"画面内持续无人 {absent_for:.1f}s",
                    confidence=min(0.99, absent_for / max(1, self.cfg.rules.absent_seconds)),
                )
            return decisions

        self.absent_started_at = None
        best_phone = RuleDecision()
        best_prone = RuleDecision()
        frame_h = frame_shape[0]

        for person in persons:
            track_id = int(person.track_id) if person.track_id is not None else -1
            center = person.center
            state = self.person_states.get(track_id)
            if state is None:
                state = PersonRuntimeState(track_id=track_id, last_bbox=person.bbox, last_center=center, last_seen_ts=timestamp_s)
                self.person_states[track_id] = state

            state.motion_score = _distance(center, state.last_center)
            state.last_center = center
            state.last_bbox = person.bbox
            state.last_seen_ts = timestamp_s

            pf = pose_features.get(track_id, {})
            phone_decision = self._phone_rule(state, person, phones, pf, fps, timestamp_s)
            prone_decision = self._prone_sleep_rule(state, person, pf, fps, frame_h)

            if phone_decision.active and phone_decision.confidence >= best_phone.confidence:
                best_phone = phone_decision
            if prone_decision.active and prone_decision.confidence >= best_prone.confidence:
                best_prone = prone_decision

        decisions["phone"] = best_phone
        decisions["prone_sleep"] = best_prone
        return decisions

    def _phone_rule(
        self,
        state: PersonRuntimeState,
        person: Detection,
        phones: List[Detection],
        pose_features: Dict[str, float],
        fps: float,
        timestamp_s: float,
    ) -> RuleDecision:
        x1, y1, x2, y2 = person.bbox
        person_w = max(1, x2 - x1)
        person_h = max(1, y2 - y1)
        person_center = person.center
        head_point = self._head_point(person, pose_features)

        matched_phone = None
        min_dist = 1e9

        for phone in phones:
            phone_center = phone.center
            close_to_person = _inside_expand(
                phone_center,
                person.bbox,
                self.cfg.rules.phone_near_person_px,
                person_h * 0.15,
            )
            close_to_head = _distance(phone_center, head_point) <= self.cfg.rules.phone_near_head_px
            in_upper_half = phone_center[1] <= y1 + person_h * 0.7

            if close_to_person and (close_to_head or in_upper_half):
                matched_phone = phone
                min_dist = min(
                    min_dist,
                    _distance(phone_center, head_point),
                    _distance(phone_center, person_center),
                )

        # 初始化时间基准
        if state.last_phone_eval_ts <= 0:
            state.last_phone_eval_ts = timestamp_s

        delta_t = max(0.0, timestamp_s - state.last_phone_eval_ts)
        state.last_phone_eval_ts = timestamp_s

        # 命中手机证据：加入时间窗
        if matched_phone is not None:
            state.phone_hit_ts.append(timestamp_s)

        # 清理窗口外旧命中
        while state.phone_hit_ts and (timestamp_s - state.phone_hit_ts[0] > self.cfg.rules.phone_window_seconds):
            state.phone_hit_ts.popleft()

        window_hits = len(state.phone_hit_ts)
        phone_present_now = window_hits >= self.cfg.rules.phone_min_hits_in_window

        # 只要短窗内命中足够，就认为当前“证据成立”
        if phone_present_now:
            state.last_phone_positive_ts = timestamp_s

        # 允许短时间漏检，不立即掉状态
        confirmed_active = (timestamp_s - state.last_phone_positive_ts) <= self.cfg.rules.phone_grace_seconds

        if confirmed_active:
            state.phone_active_seconds += delta_t
        else:
            state.phone_active_seconds = 0.0

        duration_s = state.phone_active_seconds

        if confirmed_active and window_hits >= self.cfg.rules.phone_min_hits_in_window and duration_s >= self.cfg.rules.phone_seconds:
            conf = max(
                0.65,
                1.0 - min(0.45, min_dist / max(1.0, self.cfg.rules.phone_near_person_px * 2)),
            )
            return RuleDecision(
                active=True,
                reason=(
                    f"疑似玩手机持续 {duration_s:.1f}s "
                    f"（{self.cfg.rules.phone_window_seconds}s内命中{window_hits}帧）"
                ),
                confidence=conf,
                track_id=state.track_id,
            )

        return RuleDecision()

    def _prone_sleep_rule(self, state: PersonRuntimeState, person: Detection, pose_features: Dict[str, float], fps: float, frame_h: int) -> RuleDecision:
        x1, y1, x2, y2 = person.bbox
        bbox_h = max(1, y2 - y1)
        bbox_height_ratio = bbox_h / max(1, frame_h)
        head_down_ratio = float(pose_features.get("head_down_ratio", 0.0))
        low_motion = state.motion_score <= self.cfg.rules.static_motion_threshold
        head_down = head_down_ratio >= self.cfg.rules.prone_head_down_ratio_threshold

        if head_down:
            state.head_down_frames += 1
        else:
            state.head_down_frames = max(0, state.head_down_frames - 2)

        prone_candidate = low_motion and (state.head_down_frames >= self.cfg.rules.prone_consecutive_frames or bbox_height_ratio <= self.cfg.rules.prone_bbox_height_ratio_threshold)
        if prone_candidate:
            state.prone_frames += 1
        else:
            state.prone_frames = max(0, state.prone_frames - 2)

        duration_s = state.prone_frames / max(1.0, fps)
        if duration_s >= self.cfg.rules.prone_sleep_seconds:
            conf = min(0.98, 0.68 + head_down_ratio * 0.8)
            return RuleDecision(active=True, reason=f"疑似趴睡持续 {duration_s:.1f}s（低头+低运动量）", confidence=conf, track_id=state.track_id)
        return RuleDecision()

    def _cleanup_states(self, timestamp_s: float) -> None:
        stale_ids = [track_id for track_id, state in self.person_states.items() if (timestamp_s - state.last_seen_ts) > self.cfg.rules.state_ttl_seconds]
        for track_id in stale_ids:
            self.person_states.pop(track_id, None)

    @staticmethod
    def _head_point(person: Detection, pose_features: Dict[str, float]) -> Tuple[float, float]:
        x1, y1, x2, y2 = person.bbox
        if "nose_x" in pose_features and "nose_y" in pose_features:
            return (x1 + pose_features["nose_x"] * (x2 - x1), y1 + pose_features["nose_y"] * (y2 - y1))
        return ((x1 + x2) / 2.0, y1 + (y2 - y1) * 0.18)
