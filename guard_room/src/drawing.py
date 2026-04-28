# drawing.py
from __future__ import annotations

from typing import Iterable, Optional, Sequence

import cv2
import numpy as np

from .geometry import polygon_to_np
from .types import AlarmEvent, Detection


def draw_polygon(frame: np.ndarray, polygon: Sequence[tuple[int, int]], label: str) -> None:
    if polygon is None or len(polygon) < 3:
        return
    pts = polygon_to_np(polygon).reshape((-1, 1, 2))
    cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 255), thickness=2)
    x, y = polygon[0]
    cv2.putText(frame, label, (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)


def draw_detection(frame: np.ndarray, det: Detection, label: str, color=(0, 255, 0)) -> None:
    x1, y1, x2, y2 = det.bbox
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.putText(frame, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_debug_text(frame: np.ndarray, lines: Iterable[str], origin=(20, 30)) -> None:
    x, y = origin
    for idx, line in enumerate(lines):
        cv2.putText(frame, line, (x, y + idx * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 180, 255), 2)


def draw_alarm_banner(frame: np.ndarray, event: Optional[AlarmEvent]) -> None:
    if event is None:
        return
    text = f"ALARM: {event.event_type} | track={event.track_id} | {event.reason}"
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 48), (0, 0, 255), -1)
    cv2.putText(frame, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
