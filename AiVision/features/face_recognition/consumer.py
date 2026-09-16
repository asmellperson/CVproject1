"""摄像头逐脸身份识别、监控结果与冷却记录。"""
from __future__ import annotations

import time

import cv2

from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.features.face_recognition.library.constants import (
    AUTHORIZATION_REFRESH_SECONDS, DEFAULT_CAPTURE_INTERVAL, DEFAULT_DETECTION_THRESHOLD, DEFAULT_RECORD_COOLDOWN_SECONDS,
    DEFAULT_SIMILARITY_THRESHOLD,
)
from AiVision.features.face_recognition.library.service import FaceLibraryService
from .records import RecognitionRecorder


class FaceRecognitionConsumer(BaseFunctionConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.monitor_status: dict[str, dict] = {}
        self.recorder = RecognitionRecorder()
        self.library = FaceLibraryService()
        self._allowed_person_ids: set[int] = set()
        self._authorization_refresh_at = 0.0

    def start(self):
        self.recorder.start()
        try:
            super().start()
        except Exception:
            self.recorder.stop()
            raise

    def stop(self):
        super().stop()
        self.recorder.stop()

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        super()._clear_camera_state(camera_id, shm_name)
        self.recorder.clear_camera(camera_id)
        if shm_name:
            self.monitor_status.pop(shm_name, None)

    def _should_process_now(self, camera_id: int, cfg: dict) -> bool:
        interval = float(cfg.get("cap_interval", DEFAULT_CAPTURE_INTERVAL))
        return time.time() - self._last_process_at.get(camera_id, 0.0) >= interval

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True

    def _process(self, roi, camera_id):
        value = self.config_cache[camera_id]
        response = self.dispatch_inference_sync(
            camera_id, "insightface", roi,
            task_meta={
                "conf": value.get("detection_threshold", DEFAULT_DETECTION_THRESHOLD),
                "similarity_threshold": value.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD),
            },
        )
        if response["status"] != "ok":
            return False, response
        if time.monotonic() >= self._authorization_refresh_at:
            # 整个 Consumer 共用 ID 集合；刷新失败交给基类记录异常，不使用过期权限判定。
            self._allowed_person_ids = self.library.get_allowed_person_ids()
            self._authorization_refresh_at = time.monotonic() + AUTHORIZATION_REFRESH_SECONDS
        for detection in response["detections"]:
            detection["is_allowed"] = bool(detection["matched"] and detection["person_id"] in self._allowed_person_ids)
        return any(not detection["is_allowed"] for detection in response["detections"]), response

    def post_process(self, camera_id, result):
        alarm, response = result
        frame = self._annotated_frame(camera_id)
        if frame is None:
            return None
        offset_x, offset_y = self._get_roi_offset(camera_id)
        detections = []
        for detection in response["detections"] if response["status"] == "ok" else []:
            x1, y1, x2, y2 = detection["bbox"]
            bbox = [x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y]
            detections.append({**detection, "bbox": bbox})
            if detection["is_allowed"]:
                color = (80, 200, 60)
            elif detection["matched"]:
                color = (0, 0, 255)
            else:
                color = (0, 90, 255)
            cv2.rectangle(frame, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), color, 2)
        config = self.config_cache[camera_id]
        reason = "normal"
        if any(detection["matched"] and not detection["is_allowed"] for detection in detections):
            reason = "unauthorized"
        elif response["status"] != "ok" or any(not detection["matched"] for detection in detections):
            reason = "unknown"
        # 标注帧只画 ROI / bbox；姓名、工号与相似度由前端结构化展示。
        self.monitor_status[config["shm_name"]] = {
            "detections": detections, "frame_width": frame.shape[1], "frame_height": frame.shape[0],
            "count": len(detections) if response["status"] == "ok" else None,
            "alarm": alarm, "reason": reason,
            "updated_at_s": time.time(),
        }
        value = config
        if value.get("record_enabled", True):
            self.recorder.record(
                camera_id, detections, float(value.get("record_cooldown_seconds", DEFAULT_RECORD_COOLDOWN_SECONDS)),
                frame=frame,
            )
        return frame

    def get_monitor_status(self, camera_key: str) -> dict | None:
        with self._camera_state_lock:
            value = self.monitor_status.get(camera_key)
            return dict(value) if value else None
