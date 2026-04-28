# guard_gate.py
from __future__ import annotations

from typing import Dict


class GuardGate:
    def __init__(self, hold_seconds: float = 1.0):
        self.hold_seconds = hold_seconds
        self.last_positive_ts: Dict[int, float] = {}

    def keep(self, track_id: int | None, timestamp_s: float, is_guard_now: bool) -> bool:
        if track_id is None:
            return is_guard_now

        if is_guard_now:
            self.last_positive_ts[track_id] = timestamp_s
            return True

        last_ts = self.last_positive_ts.get(track_id, -1e9)
        return (timestamp_s - last_ts) <= self.hold_seconds