"""每路 Camera 的手机与趴睡时序判断，只生成局部状态。"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import dist

from .schema import GuardBehaviorRuntimePolicy
from .state import LocalRuleDecision, PhoneDetection, TrackedPerson


@dataclass
class _PersonState:
    last_center: tuple[float, float]
    last_seen_ts: float
    motion_score: float = 0.
    phone_hit_ts: deque[float] = field(default_factory=deque)
    phone_active_seconds: float = 0.
    last_phone_eval_ts: float | None = None
    last_phone_positive_ts: float | None = None
    prone_frames: int = 0
    head_down_frames: int = 0

    def reset_phone(self) -> None:
        self.phone_hit_ts.clear()
        self.phone_active_seconds = 0.
        self.last_phone_eval_ts = self.last_phone_positive_ts = None

    def reset_prone(self) -> None:
        self.prone_frames = self.head_down_frames = 0


def strongest_decision(decisions: list[LocalRuleDecision]) -> LocalRuleDecision:
    # 已有明确阳性可以成立；其余目标未知时不能宣称全部正常。
    priority = {"normal": 0, "pending": 1, "unknown": 2, "alarm": 3}
    return max(decisions, key=lambda item: (priority[item.state], item.confidence, item.duration_seconds),
               default=LocalRuleDecision())


class LocalBehaviorState:
    def __init__(self):
        self.person_states: dict[int, _PersonState] = {}

    def cleanup(self, now: float, ttl: float) -> None:
        for track_id in list(self.person_states):
            if now - self.person_states[track_id].last_seen_ts > ttl:
                del self.person_states[track_id]

    def mark_unknown(self, now: float, ttl: float) -> None:
        self.cleanup(now, ttl)
        for state in self.person_states.values():
            state.reset_phone()
            state.reset_prone()

    def update(
        self, *, now: float, fps: float, frame_height: int, guards: list[TrackedPerson],
        phones: list[PhoneDetection], phone_failed_tracks: set[int | None],
        pose_features: dict[int, dict[str, float]], pose_available: bool,
        identity_unknown: bool, policy: GuardBehaviorRuntimePolicy,
    ) -> tuple[LocalRuleDecision, LocalRuleDecision]:
        self.cleanup(now, policy.state_ttl_seconds)
        present_ids = {person.track_id for person in guards}
        for track_id, state in self.person_states.items():
            if track_id not in present_ids:
                state.reset_phone()
                state.reset_prone()
        phone_decisions, prone_decisions = [], []
        if identity_unknown:
            unknown = LocalRuleDecision("unknown", "部分人体制服结果未知")
            phone_decisions.append(unknown)
            prone_decisions.append(unknown)
        if not pose_available:
            prone_decisions.append(LocalRuleDecision("unknown", "姿态模型不可用或推理失败"))
        for person in guards:
            if person.track_id is None:
                unknown = LocalRuleDecision("unknown", "目标尚未形成稳定轨迹")
                phone_decisions.append(unknown)
                prone_decisions.append(unknown)
                continue
            state = self.person_states.setdefault(person.track_id, _PersonState(person.center, now))
            state.motion_score = dist(person.center, state.last_center)
            state.last_center, state.last_seen_ts = person.center, now
            features = pose_features.get(person.track_id)
            if person.track_id in phone_failed_tracks:
                state.reset_phone()
                phone_decisions.append(LocalRuleDecision("unknown", "手机裁图推理失败", track_id=person.track_id))
            else:
                phone_decisions.append(self._phone_rule(state, person, phones, features, now, policy))
            if not pose_available or features is None:
                state.reset_prone()
                prone_decisions.append(LocalRuleDecision("unknown", "缺少有效姿态特征", track_id=person.track_id))
            else:
                prone_decisions.append(self._prone_rule(state, person, features, fps, frame_height, policy))
        return strongest_decision(phone_decisions), strongest_decision(prone_decisions)

    @staticmethod
    def _phone_rule(state, person, phones, features, now, policy) -> LocalRuleDecision:
        x1, y1, x2, y2 = person.bbox
        height = max(1., y2 - y1)
        # Pose 可选；无关键点时使用同一人体框的几何头部位置。
        head = ((x1 + x2) / 2, y1 + height * 0.18)
        if features is not None:
            head = (x1 + features["nose_x"] * (x2 - x1), y1 + features["nose_y"] * height)
        distances = []
        for phone in phones:
            px, py = phone.center
            close = (x1 - policy.phone_near_person_px <= px <= x2 + policy.phone_near_person_px
                     and y1 - height * 0.15 <= py <= y2 + height * 0.15)
            if close and (dist(phone.center, head) <= policy.phone_near_head_px or py <= y1 + height * 0.7):
                distances.append(min(dist(phone.center, head), dist(phone.center, person.center)))
        delta = 0. if state.last_phone_eval_ts is None else max(0., now - state.last_phone_eval_ts)
        state.last_phone_eval_ts = now
        if distances:
            state.phone_hit_ts.append(now)
        # 窗口命中充分后刷新正证据时间，短暂漏检在宽限期内继续累计。
        while state.phone_hit_ts and now - state.phone_hit_ts[0] > policy.phone_window_seconds:
            state.phone_hit_ts.popleft()
        enough_hits = len(state.phone_hit_ts) >= policy.phone_min_hits_in_window
        if enough_hits:
            state.last_phone_positive_ts = now
        active = (state.last_phone_positive_ts is not None
                  and now - state.last_phone_positive_ts <= policy.phone_grace_seconds)
        state.phone_active_seconds = state.phone_active_seconds + delta if active else 0.
        duration = state.phone_active_seconds
        confidence = max(.65, 1. - min(.45, min(distances, default=1e9) / max(1., policy.phone_near_person_px * 2)))
        if active and enough_hits and duration >= policy.phone_seconds:
            return LocalRuleDecision("alarm", "手机证据窗口和持续时间达标", confidence, person.track_id, duration)
        if active or state.phone_hit_ts:
            return LocalRuleDecision("pending", "手机证据累积中", confidence, person.track_id, duration)
        return LocalRuleDecision("normal", "无持续手机证据", track_id=person.track_id)

    @staticmethod
    def _prone_rule(state, person, features, fps, frame_height, policy) -> LocalRuleDecision:
        height_ratio = max(1., person.bbox[3] - person.bbox[1]) / max(1, frame_height)
        head_down_ratio = features["head_down_ratio"]
        head_down = head_down_ratio >= policy.prone_head_down_ratio_threshold
        # 保留帧计数软衰减：成立加一，不成立减二，避免单帧抖动清空证据。
        state.head_down_frames = state.head_down_frames + 1 if head_down else max(0, state.head_down_frames - 2)
        candidate = state.motion_score <= policy.static_motion_threshold and (
            state.head_down_frames >= policy.prone_consecutive_frames
            or height_ratio <= policy.prone_bbox_height_ratio_threshold)
        state.prone_frames = state.prone_frames + 1 if candidate else max(0, state.prone_frames - 2)
        duration = state.prone_frames / max(1., fps)
        confidence = min(.98, .68 + head_down_ratio * .8)
        if duration >= policy.prone_sleep_seconds:
            return LocalRuleDecision("alarm", "低头及低运动量持续时间达标", confidence, person.track_id, duration)
        if state.prone_frames or state.head_down_frames:
            return LocalRuleDecision("pending", "姿态证据累积中", confidence, person.track_id, duration)
        return LocalRuleDecision("normal", "无持续趴睡证据", track_id=person.track_id)
