"""车辆无人值守报警规则。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

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
    first_vehicle_center: Tuple[float, float] | None = None
    last_vehicle_center: Tuple[float, float] | None = None


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
        exit_direction_matched = self._matches_exit_direction(frame_shape)
        self.episode = VehicleEpisodeState()

        if guard_seen or not exit_direction_matched:
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
                first_vehicle_center=self._representative_vehicle_center(vehicles),
            )

        self.episode.last_vehicle_seen_ts = timestamp_s
        self.episode.missing_started_at = None
        self.episode.best_vehicle_conf = max(self.episode.best_vehicle_conf, max((v.conf for v in vehicles), default=0.0))
        self.episode.last_vehicle_center = self._representative_vehicle_center(vehicles)

        if any(self._guard_near_vehicle(guard, vehicle) for guard in guards for vehicle in vehicles):
            self.episode.guard_seen_near_vehicle = True

    def _matches_exit_direction(self, frame_shape: tuple[int, int, int]) -> bool:
        direction = str(getattr(self.cfg.rules, "vehicle_exit_direction", "any") or "any").strip().lower()
        if direction in {"", "any", "none", "off"}:
            return True

        first = self.episode.first_vehicle_center
        last = self.episode.last_vehicle_center
        if first is None or last is None:
            return False

        height, width = frame_shape[:2]
        min_ratio = float(getattr(self.cfg.rules, "vehicle_direction_min_delta_ratio", 0.03) or 0.03)
        dx = last[0] - first[0]
        dy = last[1] - first[1]
        min_x = max(1.0, width * min_ratio)
        min_y = max(1.0, height * min_ratio)

        if direction in {"right", "left_to_right", "east"}:
            return dx >= min_x
        if direction in {"left", "right_to_left", "west"}:
            return dx <= -min_x
        if direction in {"down", "top_to_bottom", "south"}:
            return dy >= min_y
        if direction in {"up", "bottom_to_top", "north"}:
            return dy <= -min_y

        return True

    @staticmethod
    def _representative_vehicle_center(vehicles: List[Detection]) -> Tuple[float, float] | None:
        if not vehicles:
            return None
        vehicle = max(vehicles, key=lambda det: (det.bbox[2] - det.bbox[0]) * (det.bbox[3] - det.bbox[1]) * max(det.conf, 0.01))
        return vehicle.center

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
