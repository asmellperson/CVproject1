"""实时底图与最近的通行检测结果合成，告警证据共用绘制方式。"""
from dataclasses import dataclass

import cv2
import numpy as np

from AiVision.features._shared.roi import roi_to_pixels
from .schema import TailgatingValue


@dataclass(frozen=True)
class PreviewState:
    camera_key: str
    value: TailgatingValue
    detail: dict | None = None


def render_preview(frame, state: PreviewState, *, now: float):
    annotated = frame.copy()
    if state.value.roi_pos:
        polygon = roi_to_pixels(state.value.roi_pos, frame.shape)
        cv2.polylines(annotated, [polygon], True, (238, 211, 34), 2)
    if state.value.line_points:
        points = np.array(state.value.line_points) * [frame.shape[1], frame.shape[0]]
        a, b = points
        cv2.line(annotated, tuple(a.astype(int)), tuple(b.astype(int)), (0, 180, 255), 2)
        normal = np.array([-(b - a)[1], (b - a)[0]])
        normal = normal / np.linalg.norm(normal) * 50
        middle = (a + b) / 2
        for direction in ((-1, 1) if state.value.direction == 0 else (state.value.direction,)):
            cv2.arrowedLine(annotated, tuple(middle.astype(int)), tuple((middle + direction * normal).astype(int)), (0, 180, 255), 2)
    detail = state.detail
    if (detail is None or detail["reason"] in ("sampling_gap", "inference_error")
            or not 0 <= now - detail["updated_at_s"] <= state.value.max_frame_gap_seconds
            or (detail["frame_height"], detail["frame_width"]) != frame.shape[:2]):
        return annotated
    offenders = {tid for event in detail["events"] for tid in event["track_ids"]}
    for person in detail["persons"]:
        x1, y1, x2, y2 = map(int, person["bbox"])
        color = (0, 0, 255) if person["track_id"] in offenders else (60, 200, 80)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated, f'#{person["track_id"]}', (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return annotated
