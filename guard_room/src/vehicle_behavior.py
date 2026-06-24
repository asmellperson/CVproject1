"""车辆无人值守报警规则。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .behavior import RuleDecision
from .config import AppConfig
from .types import Detection


@dataclass
class VehicleEpisodeState:
    """一次车辆出现在画面内的周期状态。"""

    active: bool = False
    started_at: float = 0.0
    last_vehicle_seen_ts: float = 0.0
    missing_started_at: float | None = None
    guard_seen_near_vehicle: bool = False
    best_vehicle_conf: float = 0.0


class VehicleBehaviorEngine:
    """车辆周期内未见保安靠近则报警。

    语义：
      - 车辆出现时开始一个周期；
      - 周期内只要有保安出现在车辆附近，周期判定为合格；
      - 车辆连续消失超过 vehicle_occlusion_seconds 后结束周期；
      - 若周期结束时从未见保安靠近，则触发报警。
    """

    def __init__(self, config: AppConfig):
        self.cfg = config
        self.episode = VehicleEpisodeState()

    def update(
        self,
        *,
        timestamp_s: float,
        frame_shape: tuple[int, int, int],
        guards: List[Detection],
        vehicles: List[Detection],
    ) -> RuleDecision:
        if vehicles:
            self._mark_vehicle_present(timestamp_s, guards, vehicles)
            return RuleDecision()

        if not self.episode.active:
            return RuleDecision()

        if self.episode.missing_started_at is None:
            self.episode.missing_started_at = timestamp_s
            return RuleDecision()

        missing_for = timestamp_s - self.episode.missing_started_at
        if missing_for < self.cfg.rules.vehicle_occlusion_seconds:
            return RuleDecision()

        duration_s = max(0.0, self.episode.last_vehicle_seen_ts - self.episode.started_at)
        guard_seen = self.episode.guard_seen_near_vehicle
        conf = max(0.72, min(0.95, self.episode.best_vehicle_conf or 0.72))
        self.episode = VehicleEpisodeState()

        if guard_seen:
            return RuleDecision()

        return RuleDecision(
            active=True,
            reason=f"车辆停留期间未见保安靠近，车辆出现约 {duration_s:.1f}s",
            confidence=conf,
            track_id=None,
        )

    def _mark_vehicle_present(
        self,
        timestamp_s: float,
        guards: List[Detection],
        vehicles: List[Detection],
    ) -> None:
        if not self.episode.active:
            self.episode = VehicleEpisodeState(
                active=True,
                started_at=timestamp_s,
                last_vehicle_seen_ts=timestamp_s,
            )

        self.episode.last_vehicle_seen_ts = timestamp_s
        self.episode.missing_started_at = None
        self.episode.best_vehicle_conf = max(self.episode.best_vehicle_conf, max((v.conf for v in vehicles), default=0.0))

        if any(self._guard_near_vehicle(guard, vehicle) for guard in guards for vehicle in vehicles):
            self.episode.guard_seen_near_vehicle = True

    def _guard_near_vehicle(self, guard: Detection, vehicle: Detection) -> bool:
        gx1, gy1, gx2, gy2 = guard.bbox
        foot = ((gx1 + gx2) / 2.0, gy2)
        vx1, vy1, vx2, vy2 = vehicle.bbox
        pad = float(self.cfg.rules.vehicle_near_px)
        expanded = (vx1 - pad, vy1 - pad, vx2 + pad, vy2 + pad)

        if expanded[0] <= foot[0] <= expanded[2] and expanded[1] <= foot[1] <= expanded[3]:
            return True

        return not (
            gx2 < expanded[0]
            or gx1 > expanded[2]
            or gy2 < expanded[1]
            or gy1 > expanded[3]
        )
