"""features/detect_logistics_single_person/consumer.py — 物流通道单人检测"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass

import cv2
import numpy as np

from features._base.consumer import BaseFunctionConsumer


def _number_or_default(value, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class PresenceDecision:
    alarm: bool
    reason: str
    person_count: int | None
    elapsed: float


class SinglePersonPresenceState:
    """Tracks consecutive empty/multiple-person durations for one camera ROI."""

    def __init__(self, empty_grace_seconds: float, multi_grace_seconds: float):
        self.empty_grace_seconds = max(0.0, float(empty_grace_seconds))
        self.multi_grace_seconds = max(0.0, float(multi_grace_seconds))
        self.empty_since: float | None = None
        self.multi_since: float | None = None
        self.last_normal_at: float | None = None

    def update_thresholds(self, empty_grace_seconds: float, multi_grace_seconds: float):
        self.empty_grace_seconds = max(0.0, float(empty_grace_seconds))
        self.multi_grace_seconds = max(0.0, float(multi_grace_seconds))

    def evaluate(self, person_count: int | None, now: float | None = None) -> PresenceDecision:
        now = time.time() if now is None else now
        if person_count is None:
            self.empty_since = None
            self.multi_since = None
            return PresenceDecision(False, "unknown", None, 0.0)

        if person_count == 1:
            self.empty_since = None
            self.multi_since = None
            self.last_normal_at = now
            return PresenceDecision(False, "normal", person_count, 0.0)

        if person_count == 0:
            self.multi_since = None
            if self.empty_since is None:
                self.empty_since = now
            elapsed = now - self.empty_since
            return PresenceDecision(elapsed >= self.empty_grace_seconds, "empty", person_count, elapsed)

        self.empty_since = None
        if self.multi_since is None:
            self.multi_since = now
        elapsed = now - self.multi_since
        return PresenceDecision(elapsed >= self.multi_grace_seconds, "multiple", person_count, elapsed)


class LogisticsSinglePersonConsumer(BaseFunctionConsumer):
    """物流通道单人检测 — ROI 内必须且只能有一个人体框。"""

    DETECTION_START = dt.time(8, 0, 0)
    DETECTION_END = dt.time(20, 0, 0)

    BBOX_COLOR_NORMAL = (0, 180, 0)
    BBOX_COLOR_ALARM = (0, 0, 255)
    ROI_COLOR_NORMAL = (0, 180, 0)
    ROI_COLOR_ALARM = (0, 0, 255)
    ROI_COLOR_UNKNOWN = (0, 165, 255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._presence_states: dict[tuple[int, int], SinglePersonPresenceState] = {}

    def _process(self, roi_list, camera_id):
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        conf_thr = _number_or_default(cfg.get("CONF_THRESHOLD"), 0.3)
        iou_thr = _number_or_default(cfg.get("IOU_THR"), 0.3)
        min_box_area = _number_or_default(cfg.get("MIN_BOX_AREA"), 0)
        empty_grace = _number_or_default(cfg.get("empty_grace_seconds"), 2.0)
        multi_grace = _number_or_default(cfg.get("multi_grace_seconds"), 1.0)
        aspect_range = cfg.get("ASPECT_RATIO_RANGE") or []
        min_aspect, max_aspect = None, None
        if isinstance(aspect_range, (list, tuple)) and len(aspect_range) >= 2:
            min_aspect = _number_or_default(aspect_range[0], 0)
            max_aspect = _number_or_default(aspect_range[1], 10)

        if not self.spec.required_models:
            return [(False, {"reason": "unknown", "person_count": None, "detections": []}) for _ in roi_list]

        model_name = self.spec.required_models[0]
        det_results = self.dispatch_inference_sync(
            camera_id,
            model_name,
            roi_list,
            task_meta={"conf": conf_thr, "iou": iou_thr},
        )
        results_by_roi = {item.get("roi_id", 0): item for item in det_results}

        results = []
        now = time.time()
        for roi_index in range(len(roi_list)):
            state_key = (camera_id, roi_index)
            state = self._presence_states.get(state_key)
            if state is None:
                state = SinglePersonPresenceState(empty_grace, multi_grace)
                self._presence_states[state_key] = state
            else:
                state.update_thresholds(empty_grace, multi_grace)

            det_result = results_by_roi.get(roi_index)
            if det_result is None:
                person_detections = []
                decision = state.evaluate(None, now=now)
            else:
                person_detections = self._filter_person_detections(
                    det_result.get("detections", []) or [],
                    min_box_area=min_box_area,
                    min_aspect=min_aspect,
                    max_aspect=max_aspect,
                )
                decision = state.evaluate(len(person_detections), now=now)

            results.append((
                decision.alarm,
                {
                    "reason": decision.reason,
                    "person_count": decision.person_count,
                    "elapsed": round(decision.elapsed, 2),
                    "detections": person_detections,
                },
            ))
        return results

    def _filter_person_detections(self, detections, min_box_area: float, min_aspect, max_aspect) -> list[dict]:
        persons = []
        for det in detections:
            det_type = det.get("type")
            if det_type and det_type not in {"person", "human"}:
                continue
            bbox = det.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            width = max(0.0, float(bbox[2]) - float(bbox[0]))
            height = max(0.0, float(bbox[3]) - float(bbox[1]))
            area = width * height
            if area < min_box_area:
                continue
            if height > 0 and min_aspect is not None and max_aspect is not None:
                aspect = width / height
                if aspect < min_aspect or aspect > max_aspect:
                    continue
            persons.append(det)
        return persons

    def post_process(self, camera_id, result):
        frame = self.frame_cache.get(camera_id)
        if frame is None:
            return None
        frame_copy = frame.copy()
        roi_polygons = self._get_roi_polygons(camera_id)
        roi_offsets = self._get_roi_offsets(camera_id)

        for roi_index, (alarm, detail) in enumerate(result):
            detail = detail or {}
            reason = detail.get("reason", "unknown")
            count = detail.get("person_count")
            detections = detail.get("detections") or []
            roi_color = self.ROI_COLOR_ALARM if alarm else (
                self.ROI_COLOR_UNKNOWN if reason == "unknown" else self.ROI_COLOR_NORMAL
            )

            if roi_index < len(roi_polygons):
                poly = np.array(roi_polygons[roi_index], dtype=np.int32)
                cv2.polylines(frame_copy, [poly.reshape(-1, 1, 2)], True, roi_color, 2)
                label_x, label_y = int(poly[:, 0].min()), max(20, int(poly[:, 1].min()) - 8)
                cv2.putText(
                    frame_copy,
                    self._label_for(reason, count, detail.get("elapsed", 0)),
                    (label_x, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    roi_color,
                    2,
                )

            ox, oy = roi_offsets[roi_index] if roi_index < len(roi_offsets) else (0, 0)
            for det in detections:
                bbox = det.get("bbox", [])
                if len(bbox) < 4:
                    continue
                x1, y1, x2, y2 = (
                    int(bbox[0]) + ox,
                    int(bbox[1]) + oy,
                    int(bbox[2]) + ox,
                    int(bbox[3]) + oy,
                )
                color = self.BBOX_COLOR_ALARM if alarm else self.BBOX_COLOR_NORMAL
                conf = det.get("confidence", 0)
                cv2.rectangle(frame_copy, (x1, y1), (x2, y2), color, 2)
                cv2.putText(
                    frame_copy,
                    f"person {conf:.2f}",
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    color,
                    2,
                )
        return frame_copy

    @staticmethod
    def _label_for(reason: str, count, elapsed) -> str:
        if reason == "empty":
            return f"EMPTY count=0 {float(elapsed):.1f}s"
        if reason == "multiple":
            return f"MULTI count={count} {float(elapsed):.1f}s"
        if reason == "normal":
            return "OK count=1"
        return "UNKNOWN"

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True

    def _should_process_now(self, camera_id: int, cfg: dict) -> bool:
        if self._is_detection_time(dt.datetime.now().time()):
            return True

        self._reset_presence_state(camera_id)
        return False

    @classmethod
    def _is_detection_time(cls, current_time: dt.time) -> bool:
        return cls.DETECTION_START <= current_time < cls.DETECTION_END

    def _reset_presence_state(self, camera_id: int):
        for key in [key for key in self._presence_states if key[0] == camera_id]:
            self._presence_states.pop(key, None)

    def _get_roi_offsets(self, camera_id: int) -> list[tuple[int, int]]:
        offsets = []
        if camera_id in self._masks:
            for _mask, y_min, _y_max, x_min, _x_max in self._masks[camera_id]:
                offsets.append((x_min, y_min))
        return offsets
