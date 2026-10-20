"""纯轨迹判定：共同出现与同向过线必须属于同一次通行。"""
from dataclasses import dataclass
from itertools import combinations
from math import ceil, hypot
from uuid import uuid4

import cv2

from AiVision.features._shared.roi import roi_to_pixels
from AiVision.features._shared.tracking import IouTracker
from .schema import LINE_MARGIN_RATIO, TailgatingValue


@dataclass
class Passage:
    token: int
    point: tuple[float, float] | None = None
    side: int = 0
    inside: bool = False
    direction: int | None = None


@dataclass
class Pair:
    tokens: tuple[int, int]
    started_at: float
    last_shared_at: float
    overlap_seconds: float = 0.0
    event_id: str | None = None
    dispatched: bool = False


def crossing_direction(a, b, previous, current) -> int:
    """只计算有限线段的真实跨越，线的延长线不参与计数。"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    before = dx * (previous[1] - a[1]) - dy * (previous[0] - a[0])
    after = dx * (current[1] - a[1]) - dy * (current[0] - a[0])
    if before * after >= 0:
        return 0
    fraction = before / (before - after)
    x = previous[0] + fraction * (current[0] - previous[0])
    y = previous[1] + fraction * (current[1] - previous[1])
    along = ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)
    return (1 if after > 0 else -1) if 0 <= along <= 1 else 0


class TailgatingRuntime:
    def __init__(self, config: TailgatingValue):
        self.config = config
        self.tracker = IouTracker(max_lost=ceil(config.max_frame_gap_seconds / config.cap_interval), smooth_alpha=1.0)
        self.passages: dict[int, Passage] = {}
        self.pairs: dict[tuple[int, int], Pair] = {}
        self.last_frame_at: float | None = None
        self.shape: tuple[int, ...] | None = None
        self._next_token = 0

    def clear(self):
        self.tracker.reset()
        self.passages.clear()
        self.pairs.clear()
        self.last_frame_at = None

    def update(self, detections: list[dict], shape: tuple[int, ...], *, now: float) -> dict:
        previous_frame_at = self.last_frame_at
        interval = now - previous_frame_at if previous_frame_at is not None else None
        interrupted = interval is not None and (interval <= 0 or interval > self.config.max_frame_gap_seconds)
        if self.shape != shape or interrupted:
            self.clear()
            previous_frame_at = None
        self.shape, self.last_frame_at = shape, now
        # 单个人员长时间丢失也不能接回旧的通行身份。
        for tid, track in list(self.tracker.tracks.items()):
            if now - track.last_seen > self.config.max_frame_gap_seconds:
                del self.tracker.tracks[tid]
        tracks = self.tracker.update(detections, now=now)
        self.passages = {tid: state for tid, state in self.passages.items() if tid in tracks}
        polygon = roi_to_pixels(self.config.roi_pos, shape)
        people = []
        inside = set()
        for tid, track in tracks.items():
            if track.lost:
                continue
            x1, y1, x2, y2 = track.bbox
            point = ((x1 + x2) / 2 / shape[1], (y1 + (y2 - y1) * self.config.foot_ratio) / shape[0])
            in_roi = cv2.pointPolygonTest(polygon, (point[0] * shape[1], point[1] * shape[0]), False) >= 0
            passage = self.passages.setdefault(tid, Passage(0))
            if in_roi and not passage.inside:
                self._next_token += 1
                passage.token = self._next_token
                passage.direction = None
            self._update_crossing(passage, point, in_roi)
            passage.inside = in_roi
            if in_roi:
                inside.add(tid)
            people.append({"track_id": tid, "bbox": list(track.bbox), "in_roi": in_roi, "direction": passage.direction})

        for key, pair in list(self.pairs.items()):
            current_tokens = tuple(self.passages[tid].token if tid in self.passages else None for tid in key)
            if pair.tokens != current_tokens or now - pair.last_shared_at > self.config.crossing_window_seconds:
                del self.pairs[key]
        for key in combinations(sorted(inside), 2):
            tokens = tuple(self.passages[tid].token for tid in key)
            pair = self.pairs.setdefault(key, Pair(tokens, now, now))
            if pair.last_shared_at != previous_frame_at:
                pair.started_at = now
            pair.last_shared_at = now
            pair.overlap_seconds = max(pair.overlap_seconds, now - pair.started_at)
        eligible = []
        for key, pair in self.pairs.items():
            first, second = (self.passages[tid] for tid in key)
            direction = first.direction
            if (pair.overlap_seconds < self.config.overlap_seconds or direction is None
                    or direction != second.direction or self.config.direction not in (0, direction)):
                continue
            eligible.append((set(key), [pair]))
        events = self._group_events(eligible)
        return {"persons": people, "events": events, "count": len(inside), "alarm": bool(events),
                "sample_interval_seconds": interval, "reason": "sampling_gap" if interrupted else "tailgating" if events else "clear"}

    def _group_events(self, candidates):
        """共享通行人员的异常合为一件事件，三人同行不会生成三条两两报警。"""
        groups = []
        for members, pairs in candidates:
            separate = []
            for existing_members, existing_pairs in groups:
                if members & existing_members:
                    members |= existing_members
                    pairs.extend(existing_pairs)
                else:
                    separate.append((existing_members, existing_pairs))
            groups = [*separate, (members, pairs)]
        events = []
        for members, pairs in groups:
            sent = any(pair.dispatched for pair in pairs)
            event_id = next((pair.event_id for pair in pairs if pair.dispatched), None)
            event_id = event_id or next((pair.event_id for pair in pairs if pair.event_id), None) or uuid4().hex
            for pair in pairs:
                pair.event_id, pair.dispatched = event_id, sent
            first = min(members)
            events.append({"id": event_id, "track_ids": sorted(members), "direction": self.passages[first].direction,
                           "overlap_seconds": round(min(pair.overlap_seconds for pair in pairs), 3)})
        return events

    def _update_crossing(self, passage: Passage, point, in_roi: bool):
        a, b = self.config.line_points
        distance = ((b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])) / hypot(b[0] - a[0], b[1] - a[1])
        if abs(distance) <= LINE_MARGIN_RATIO:
            return
        side = 1 if distance > 0 else -1
        if passage.point is not None and side != passage.side and (in_roi or passage.inside):
            direction = crossing_direction(a, b, passage.point, point)
            if direction:
                if passage.direction is not None:
                    # 折返开始新通行，旧的共同出现证据不得用于另一次过线。
                    self._next_token += 1
                    passage.token = self._next_token
                passage.direction = direction
        passage.point, passage.side = point, side
