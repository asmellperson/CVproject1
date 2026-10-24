"""通行检测框与检测原图成对展示，静态边界可在实时底图上独立显示。"""
from dataclasses import dataclass

import cv2
import numpy as np

from AiVision.features._shared.roi import roi_to_pixels
from AiVision.features._shared.line_overlay import BOUNDARY_COLOR, draw_direction_line
from AiVision.features._shared.preview import DetectionPreviewFrame
from .schema import TailgatingValue


@dataclass(frozen=True)
class PreviewState:
    camera_key: str
    value: TailgatingValue
    detail: dict | None = None
    source: DetectionPreviewFrame | None = None


def annotate_frame(frame, value: TailgatingValue, detail: dict | None = None):
    """预览和报警证据共用绘图；调用方负责选取与坐标匹配的原图。"""
    annotated = frame.copy()
    if value.roi_pos:
        polygon = roi_to_pixels(value.roi_pos, frame.shape)
        cv2.polylines(annotated, [polygon], True, BOUNDARY_COLOR, 1, lineType=cv2.LINE_AA)
    if value.line_points:
        points = np.array(value.line_points) * [frame.shape[1], frame.shape[0]]
        directions = (-1, 1) if value.direction == 0 else (value.direction,)
        draw_direction_line(annotated, points, directions)
    if detail is None:
        return annotated
    offenders = {tid for event in detail["events"] for tid in event["track_ids"]}
    for person in detail["persons"]:
        x1, y1, x2, y2 = map(int, person["bbox"])
        color = (0, 0, 255) if person["track_id"] in offenders else (60, 200, 80)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated, f'#{person["track_id"]}', (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return annotated


def render_preview(frame, state: PreviewState, *, now: float):
    detail = state.detail
    if (detail is None or not detail["persons"] or detail["reason"] in ("sampling_gap", "inference_error")
            or not 0 <= now - detail["updated_at_s"] <= state.value.max_frame_gap_seconds
            or (detail["frame_height"], detail["frame_width"]) != frame.shape[:2]
            or state.source is None or not state.source.usable(frame, now=now, max_age=state.value.max_frame_gap_seconds)):
        return annotate_frame(frame, state.value)
    return annotate_frame(state.source.frame, state.value, detail)
