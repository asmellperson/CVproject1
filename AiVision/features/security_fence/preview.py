"""围栏检测框使用对应原图；无有效结果时显示实时底图与 ROI。"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

import cv2
import numpy as np

from AiVision.features._shared.roi import roi_to_pixels
from AiVision.features._shared.preview import DetectionPreviewFrame
from .runtime import current_mode
from .schema import STALE_SECONDS, FenceValue


def draw_fence_detections(frame, detail):
    """预览和完整画面录像复用相同的人体、人脸标注样式。"""
    for person in detail["persons"]:
        x1, y1, x2, y2 = map(int, person["bbox"])
        color = (0, 0, 255) if person["alarm"] else (0, 180, 255) if person["identity"] == "pending" else (60, 200, 80)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, f'#{person["track_id"]} {person["identity"]}', (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    for face in detail["faces"]:
        x1, y1, x2, y2 = map(int, face["bbox"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 200, 0), 2)
    return frame


@dataclass(frozen=True)
class _PreviewEntry:
    camera_key: str
    value: FenceValue
    detail: dict | None = None
    source: DetectionPreviewFrame | None = None


class FencePreview:
    """短锁只保护快照发布；取图、状态读取不等待模型推理锁。"""
    def __init__(self, roi_color):
        self._roi_color = roi_color
        self._lock = Lock()
        self._entries: dict[int, _PreviewEntry] = {}

    def configure(self, camera_id: int, config: dict | None):
        entry = None
        if config and config.get("enable") and config.get("camera_enable", True):
            value = FenceValue.model_validate({key: config[key] for key in FenceValue.model_fields})
            entry = _PreviewEntry(config["shm_name"], value)
        with self._lock:
            if entry is None:
                self._entries.pop(camera_id, None)
            else:
                # 配置更新后撤销旧标注，等待与新配置对应的检测结果。
                self._entries[camera_id] = entry

    def publish(self, camera_id: int, detail: dict, *, source: DetectionPreviewFrame):
        snapshot = deepcopy(detail)
        with self._lock:
            entry = self._entries.get(camera_id)
            if entry is not None:
                self._entries[camera_id] = _PreviewEntry(entry.camera_key, entry.value, snapshot, source)

    def _entry(self, camera_key: str):
        with self._lock:
            return next((entry for entry in self._entries.values() if entry.camera_key == camera_key), None)

    def status(self, camera_key: str):
        entry = self._entry(camera_key)
        return deepcopy(entry.detail) if entry is not None else None

    def render(self, camera_key: str, frame, *, now: float) -> np.ndarray | None:
        entry = self._entry(camera_key)
        if entry is None:
            return None
        detail = entry.detail
        updated_at = float(detail["updated_at_s"]) if detail else 0.0
        mode = current_mode(entry.value, datetime.fromtimestamp(now, timezone.utc))
        show_detections = (
            detail is not None and bool(detail["persons"] or detail["faces"])
            and 0 <= now - updated_at <= STALE_SECONDS and detail["mode"] == mode
            and (detail["frame_height"], detail["frame_width"]) == frame.shape[:2]
            and entry.source is not None and entry.source.usable(frame, now=now, max_age=STALE_SECONDS)
        )
        # 框坐标属于检测输入，不能画到人物已经移动的最新采集帧上。
        annotated = (entry.source.frame if show_detections else frame).copy()
        polygon = roi_to_pixels(entry.value.roi_pos, frame.shape)
        polygon = np.clip(polygon, [0, 0], [frame.shape[1] - 1, frame.shape[0] - 1])
        cv2.polylines(annotated, [polygon], True, self._roi_color, 2)
        if show_detections:
            draw_fence_detections(annotated, detail)
        # 渲染期间发生停用或配置替换时，不发布旧配置的画面。
        current = self._entry(camera_key)
        if current is None or current.value is not entry.value:
            return None
        return annotated
