"""多摄证据聚合；负证据要求完整，正证据允许其他 Camera 降级。"""
from dataclasses import dataclass
from typing import Literal

from .schema import GuardBehaviorRuntimeMember, GuardBehaviorRuntimeSiteConfig
from .state import CameraAvailability, GuardCameraSnapshot, SiteRuleDecision


MIN_STALE_SECONDS = 5.
STALE_INTERVAL_MULTIPLIER = 3.


def expected_members(config: GuardBehaviorRuntimeSiteConfig) -> tuple[GuardBehaviorRuntimeMember, ...]:
    if not config.enabled:
        return ()
    return tuple(sorted((member for member in config.members if member.member_enabled and member.feature_enabled),
                        key=lambda member: (member.sort_order, member.camera_id)))


def stale_seconds(config: GuardBehaviorRuntimeSiteConfig) -> float:
    return max(MIN_STALE_SECONDS, config.policy.cap_interval * STALE_INTERVAL_MULTIPLIER)


def camera_availability(member: GuardBehaviorRuntimeMember, snapshot: GuardCameraSnapshot | None,
                        now: float, stale_after: float) -> CameraAvailability:
    if not member.physical_enabled:
        return CameraAvailability.PHYSICAL_DISABLED
    if snapshot is None or not snapshot.online:
        return CameraAvailability.OFFLINE
    if now - snapshot.updated_at > stale_after:
        return CameraAvailability.STALE
    # 同一模型还承担手机裁图推理；子规则失败不能覆盖已确定的核心在岗事实。
    if snapshot.guard_present is None:
        return CameraAvailability.INFERENCE_ERROR
    return CameraAvailability.READY


@dataclass
class AbsenceState:
    since: float | None = None
    valid_until: float | None = None

    def clear(self) -> None:
        self.since = self.valid_until = None

    def evaluate(self, config: GuardBehaviorRuntimeSiteConfig, snapshots: dict[int, GuardCameraSnapshot],
                 states: dict[int, CameraAvailability], now: float) -> SiteRuleDecision:
        if not states or any(status != CameraAvailability.READY for status in states.values()):
            # 未知时段打断连续负证据，恢复后不能接着之前的离岗时间报警。
            self.clear()
            return SiteRuleDecision("unavailable", "unknown", "离岗判断需要全部预期 Camera 可用")
        if any(snapshots[camera_id].guard_present for camera_id in states):
            self.clear()
            return SiteRuleDecision("available", "normal", "已观察到保安")
        if self.since is None or self.valid_until is None or now > self.valid_until or now < self.since:
            self.since = now
        # 即使调用方漏掉了中间巡检，也不能跨越已失效的快照累计离岗时间。
        self.valid_until = min(snapshots[camera_id].updated_at for camera_id in states) + stale_seconds(config)
        duration = now - self.since
        alarm = duration >= config.policy.absent_alarm_seconds
        members = expected_members(config)
        return SiteRuleDecision("available", "alarm" if alarm else "pending",
                                "全部预期 Camera 持续未观察到保安", members[0].camera_id,
                                tuple(member.camera_id for member in members), 1., duration)


def aggregate_positive(rule: Literal["phone", "prone"], snapshots: dict[int, GuardCameraSnapshot],
                       states: dict[int, CameraAvailability]) -> SiteRuleDecision:
    known = [camera_id for camera_id, state in states.items()
             if state == CameraAvailability.READY and getattr(snapshots[camera_id], rule).state != "unknown"]
    offending = [camera_id for camera_id in known if getattr(snapshots[camera_id], rule).state == "alarm"]
    availability = "available" if known and len(known) == len(states) else ("degraded" if known else "unavailable")
    if offending:
        primary = max(offending, key=lambda camera_id: getattr(snapshots[camera_id], rule).confidence)
        decision = getattr(snapshots[primary], rule)
        return SiteRuleDecision(availability, "alarm", decision.reason, primary, tuple(offending),
                                decision.confidence, decision.duration_seconds)
    state = "normal" if availability == "available" else "unknown"
    return SiteRuleDecision(availability, state, "无明确异常" if state == "normal" else "部分 Camera 缺少有效规则证据")
