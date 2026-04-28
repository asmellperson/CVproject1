# consensus.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .behavior import RuleDecision


@dataclass
class CameraDecisionBundle:
    camera_id: str
    camera_online: bool
    guard_present: bool
    phone: RuleDecision
    prone_sleep: RuleDecision


class MultiCameraConsensus:
    def __init__(
        self,
        guard_hold_seconds: float = 1.3,
        absent_alarm_seconds: float = 60.0,
        behavior_sync_seconds: float = 1.5,
    ):
        self.guard_hold_seconds = guard_hold_seconds
        self.absent_alarm_seconds = absent_alarm_seconds
        self.behavior_sync_seconds = behavior_sync_seconds

        self.last_guard_seen_ts: Dict[str, float] = {}
        self.last_phone_seen_ts: Dict[str, float] = {}
        self.last_prone_seen_ts: Dict[str, float] = {}

        self.no_guard_started_at: float | None = None

    def update(
        self,
        timestamp_s: float,
        cameras: Dict[str, CameraDecisionBundle],
    ) -> Dict[str, RuleDecision]:
        results = {
            "absent": RuleDecision(),
            "phone": RuleDecision(),
            "prone_sleep": RuleDecision(),
        }

        # 只看在线摄像头
        online_cameras = {k: v for k, v in cameras.items() if v.camera_online}

        # 没有任何在线摄像头,什么都不判
        if not online_cameras:
            self.no_guard_started_at = None
            return results

        # 更新各类"最近一次看到"时间戳
        for cam_id, bundle in online_cameras.items():
            if bundle.guard_present:
                self.last_guard_seen_ts[cam_id] = timestamp_s
            if bundle.phone.active:
                self.last_phone_seen_ts[cam_id] = timestamp_s
            if bundle.prone_sleep.active:
                self.last_prone_seen_ts[cam_id] = timestamp_s

        # ============== 离岗判定 ==============
        # 任意一路摄像头最近还看到过保安,就认为没离岗
        recent_guard = {
            cam_id: (timestamp_s - self.last_guard_seen_ts.get(cam_id, -1e9)) <= self.guard_hold_seconds
            for cam_id in online_cameras.keys()
        }
        any_guard_present_recently = any(recent_guard.values())

        if any_guard_present_recently:
            self.no_guard_started_at = None
        else:
            if self.no_guard_started_at is None:
                seen_times = [
                    self.last_guard_seen_ts[cam_id]
                    for cam_id in online_cameras.keys()
                    if cam_id in self.last_guard_seen_ts
                ]
                if seen_times:
                    self.no_guard_started_at = max(seen_times)
                else:
                    self.no_guard_started_at = timestamp_s

            missing_for = timestamp_s - self.no_guard_started_at
            if missing_for >= self.absent_alarm_seconds:
                results["absent"] = RuleDecision(
                    active=True,
                    reason=f"连续 {missing_for:.0f}s 未见到保安",
                    confidence=0.90,
                    track_id=None,
                )

        # ============== 玩手机判定:任一摄像头命中即报警 ==============
        active_phone_cams = [
            cam_id for cam_id, bundle in online_cameras.items()
            if bundle.phone.active
        ]
        if active_phone_cams:
            # 取所有命中摄像头中置信度最高的
            best_conf = max(
                online_cameras[cam_id].phone.confidence
                for cam_id in active_phone_cams
            )
            cam_label = "/".join(active_phone_cams)
            results["phone"] = RuleDecision(
                active=True,
                reason=f"{cam_label} 检测到玩手机",
                confidence=best_conf,
                track_id=None,
            )

        # ============== 趴睡判定:任一摄像头命中即报警 ==============
        active_prone_cams = [
            cam_id for cam_id, bundle in online_cameras.items()
            if bundle.prone_sleep.active
        ]
        if active_prone_cams:
            best_conf = max(
                online_cameras[cam_id].prone_sleep.confidence
                for cam_id in active_prone_cams
            )
            cam_label = "/".join(active_prone_cams)
            results["prone_sleep"] = RuleDecision(
                active=True,
                reason=f"{cam_label} 检测到趴睡",
                confidence=best_conf,
                track_id=None,
            )

        return results