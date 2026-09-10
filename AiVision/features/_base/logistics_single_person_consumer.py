"""物流通道单人检测的单 ROI 逐摄像头消费者。"""
from __future__ import annotations

import time
from typing import Protocol

import cv2
import numpy as np

from AiVision.platform.logistics_channel.state import (
    CameraSnapshot,
    PersonDetection,
    deduplicate_person_detections,
    translate_person_detection,
)
from AiVision.features._base.consumer import BaseFunctionConsumer


DEFAULT_PERSON_DEDUP_IOU_THRESHOLD = 0.5

class LogisticsConsumerRuntime(Protocol):
    """Task 5 的最小运行时注入边界；通道聚合实现在后续任务中提供。"""
    def camera_should_run(self, feature_name: str, camera_id: int) -> bool: ...

    def person_confidence_threshold(self, feature_name: str, camera_id: int) -> float | None: ...

    def update_camera_snapshot(
        self,
        feature_name: str,
        snapshot: CameraSnapshot,
        annotated_frame: np.ndarray | None,
    ) -> None: ...

    def evaluate_after_camera_update(self, feature_name: str, camera_id: int) -> None: ...

def _number_or_default(value, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_monitor_snapshot(result: tuple, updated_at: float | None = None) -> dict:
    """当前摄像头唯一 ROI 的监控状态。"""
    alarm, detail = result
    return {
        "count": detail["person_count"],
        "alarm": bool(alarm),
        "reason": detail["reason"],
        "updated_at_s": time.time() if updated_at is None else float(updated_at),
    }


class LogisticsSinglePersonConsumerBase(BaseFunctionConsumer):
    """逐路推理、坐标还原和快照发布；人数告警统一交给通道运行时。"""

    BBOX_COLOR_NORMAL = (0, 180, 0)
    BBOX_COLOR_ABNORMAL = (0, 0, 255)
    ROI_COLOR_NORMAL = (0, 180, 0)
    ROI_COLOR_ABNORMAL = (0, 0, 255)
    ROI_COLOR_UNKNOWN = (0, 165, 255)

    def __init__(self, *args, logistics_runtime: LogisticsConsumerRuntime | None = None, **kwargs):
        if logistics_runtime is None:
            raise RuntimeError(
                f"{type(self).__name__} 缺少 LogisticsChannelRuntime 注入；"
                "物流单人检测不能在无通道聚合运行时的情况下启动"
            )
        super().__init__(*args, **kwargs)
        self.logistics_runtime = logistics_runtime
        self.monitor_status: dict[str, dict] = {}

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        super()._clear_camera_state(camera_id, shm_name)
        if shm_name:
            self.monitor_status.pop(shm_name, None)

    def _process(self, roi, camera_id):
        """
        对当前摄像头唯一 ROI 做人体检测，过滤无效框，计算当前人数和状态
        """
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        conf_thr = _number_or_default(cfg.get("CONF_THRESHOLD"), 0.3)
        threshold_provider = getattr(self.logistics_runtime, "person_confidence_threshold", None)
        if callable(threshold_provider):
            conf_thr = _number_or_default(
                threshold_provider(self.feature_name, camera_id),
                conf_thr,
            )
        iou_thr = _number_or_default(cfg.get("IOU_THR"), 0.3)
        min_box_area = _number_or_default(cfg.get("MIN_BOX_AREA"), 0)
        aspect_range = cfg.get("ASPECT_RATIO_RANGE") or []
        min_aspect, max_aspect = None, None
        if isinstance(aspect_range, (list, tuple)) and len(aspect_range) >= 2:
            min_aspect = _number_or_default(aspect_range[0], 0)
            max_aspect = _number_or_default(aspect_range[1], 10)

        if not self.spec.required_models:
            return self._unknown_roi_result()
        det_result = self.dispatch_inference_sync(
            camera_id,
            self.spec.required_models[0],
            roi,
            task_meta={"conf": conf_thr, "iou": iou_thr},
        )
        # 某条结果缺失或推理失败时，直接 unknown，不能误报为无人。
        if det_result.get("status", "ok") != "ok":
            return self._unknown_roi_result()
        detections = self._filter_person_detections(
            det_result.get("detections", []) or [],
            min_box_area=min_box_area,
            min_aspect=min_aspect,
            max_aspect=max_aspect,
        )
        count = len(detections)
        reason = "empty" if count == 0 else "normal" if count == 1 else "multiple"
        return False, {"reason": reason, "person_count": count, "elapsed": 0.0, "detections": detections}

    @staticmethod
    def _unknown_roi_result() -> tuple[bool, dict]:
        return False, {
            "reason": "unknown",
            "person_count": None,
            "elapsed": 0.0,
            "detections": [],
        }

    @staticmethod
    def _filter_person_detections(detections, min_box_area: float, min_aspect, max_aspect):
        persons = []
        for detection in detections:
            detection_type = detection.get("type")
            if detection_type and detection_type not in {"person", "human"}:
                continue
            bbox = detection.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            width = max(0.0, float(bbox[2]) - float(bbox[0]))
            height = max(0.0, float(bbox[3]) - float(bbox[1]))
            if width * height < min_box_area:
                continue
            if height > 0 and min_aspect is not None and max_aspect is not None:
                aspect = width / height
                if aspect < min_aspect or aspect > max_aspect:
                    continue
            persons.append(detection)
        return persons

    def post_process(self, camera_id, result):
        annotated = self._annotated_frame(camera_id)
        _alarm, detail = result
        reason = detail["reason"]
        x_offset, y_offset = self._get_roi_offset(camera_id)
        translated_detections: list[PersonDetection] = []
        for detection in detail["detections"]:
            bbox = detection["bbox"]
            translated_detections.append(translate_person_detection(
                PersonDetection(
                    bbox=tuple(float(value) for value in bbox[:4]),
                    confidence=float(detection.get("confidence", 0)),
                ),
                x_offset, y_offset,
            ))
        if annotated is not None:
            cv2.putText(
                annotated, self._label_for(reason, detail["person_count"]),
                (x_offset, max(20, y_offset - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, self._color_for_reason(reason), 2,
            )

        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        dedup_iou = _number_or_default(
            cfg.get("DEDUP_IOU_THRESHOLD"), DEFAULT_PERSON_DEDUP_IOU_THRESHOLD
        )
        if not 0 <= dedup_iou <= 1:
            dedup_iou = DEFAULT_PERSON_DEDUP_IOU_THRESHOLD
        unique_detections = deduplicate_person_detections(
            translated_detections,
            iou_threshold=dedup_iou,
        )
        count = len(unique_detections)
        snapshot_count = count if count >= 2 or reason != "unknown" else None
        updated_at = time.time()
        camera_cfg = self.config_cache.get(camera_id, {})
        camera_key = str(camera_cfg.get("shm_name") or "").strip()
        camera_name = str(camera_cfg.get("name") or camera_key)
        snapshot = CameraSnapshot(
            camera_id=camera_id,
            camera_name=camera_name,
            count=snapshot_count,
            updated_at=updated_at,
            online=self._camera_online(camera_key),
        )

        if annotated is not None:
            self._draw_unique_detections(annotated, unique_detections, snapshot_count)
        if camera_key:
            self.monitor_status[camera_key] = build_monitor_snapshot(
                (False, {"person_count": snapshot_count, "reason": self._snapshot_reason(snapshot_count)}),
                updated_at=updated_at,
            )
        self.logistics_runtime.update_camera_snapshot(self.feature_name, snapshot, annotated)
        return annotated

    def _camera_online(self, camera_key: str) -> bool:
        checker = getattr(self, "is_camera_active", None)
        if not camera_key or not callable(checker):
            return True
        return bool(checker(camera_key))

    def _draw_unique_detections(
        self,
        frame: np.ndarray,
        detections: tuple[PersonDetection, ...],
        count: int | None,
    ) -> None:
        color = self.BBOX_COLOR_ABNORMAL if count is not None and count >= 2 else self.BBOX_COLOR_NORMAL
        for detection in detections:
            x1, y1, x2, y2 = (int(value) for value in detection.bbox)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"person {detection.confidence:.2f}",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

    @classmethod
    def _color_for_reason(cls, reason: str) -> tuple[int, int, int]:
        if reason in {"empty", "multiple"}:
            return cls.ROI_COLOR_ABNORMAL
        if reason == "unknown":
            return cls.ROI_COLOR_UNKNOWN
        return cls.ROI_COLOR_NORMAL

    @staticmethod
    def _label_for(reason: str, count) -> str:
        if reason == "empty":
            return "EMPTY count=0"
        if reason == "multiple":
            return f"MULTI count={count}"
        if reason == "normal":
            return "OK count=1"
        return "UNKNOWN"

    @staticmethod
    def _snapshot_reason(count: int | None) -> str:
        if count is None:
            return "unknown"
        if count == 0:
            return "empty"
        if count == 1:
            return "normal"
        return "multiple"

    def get_monitor_status(self, camera_key: str) -> dict | None:
        value = self.monitor_status.get(camera_key)
        return dict(value) if value else None

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True

    def _should_process_now(self, camera_id: int, cfg: dict) -> bool:
        return bool(self.logistics_runtime.camera_should_run(self.feature_name, camera_id))

    def _handle_alarm(self, camera_id: int, result: tuple, frame: np.ndarray | None):
        self.logistics_runtime.evaluate_after_camera_update(self.feature_name, camera_id)
