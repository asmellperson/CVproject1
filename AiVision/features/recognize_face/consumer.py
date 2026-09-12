"""摄像头逐脸身份识别、监控结果与冷却记录。"""
from __future__ import annotations

import time

import cv2

from AiVision.features._base.consumer import BaseFunctionConsumer
from AiVision.platform.face_library.constants import (
    DEFAULT_CAPTURE_INTERVAL, DEFAULT_DETECTION_THRESHOLD, DEFAULT_RECORD_COOLDOWN_SECONDS,
    DEFAULT_SIMILARITY_THRESHOLD,
)
from .records import RecognitionRecorder


class FaceRecognitionConsumer(BaseFunctionConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.monitor_status: dict[str, dict] = {}
        self.recorder = RecognitionRecorder()

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        super()._clear_camera_state(camera_id, shm_name)
        self.recorder.clear_camera(camera_id)
        if shm_name:
            self.monitor_status.pop(shm_name, None)

    def _should_process_now(self, camera_id: int, cfg: dict) -> bool:
        interval = float(self._value_config(cfg).get("cap_interval", DEFAULT_CAPTURE_INTERVAL))
        return time.time() - self._last_process_at.get(camera_id, 0.0) >= interval

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True

    def _process(self, roi, camera_id):
        value = self._value_config(self.config_cache[camera_id])
        response = self.dispatch_inference_sync(
            camera_id, "insightface", roi,
            task_meta={
                "conf": value.get("detection_threshold", DEFAULT_DETECTION_THRESHOLD),
                "similarity_threshold": value.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD),
            },
        )
        # 身份识别结果永远不触发现有报警分发器。
        return False, response

    def post_process(self, camera_id, result):
        response = result[1]
        frame = self._annotated_frame(camera_id)
        if frame is None:
            return None
        offset_x, offset_y = self._get_roi_offset(camera_id)
        detections = []
        for detection in response["detections"] if response["status"] == "ok" else []:
            x1, y1, x2, y2 = detection["bbox"]
            bbox = [x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y]
            detections.append({**detection, "bbox": bbox})
            color = (80, 200, 60) if detection["matched"] else (0, 180, 255)
            cv2.rectangle(frame, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), color, 2)
        config = self.config_cache[camera_id]
        # 姓名由前端以中文字体绘制，坐标使用原始图像尺寸。
        self.monitor_status[config["shm_name"]] = {
            "detections": detections, "frame_width": frame.shape[1], "frame_height": frame.shape[0],
            "count": len(detections) if response["status"] == "ok" else None,
            "alarm": False, "reason": "normal" if response["status"] == "ok" else "unknown",
            "updated_at_s": time.time(),
        }
        value = self._value_config(config)
        if value.get("record_enabled", True):
            self.recorder.record(
                camera_id, detections, float(value.get("record_cooldown_seconds", DEFAULT_RECORD_COOLDOWN_SECONDS)),
            )
        return frame

    def get_monitor_status(self, camera_key: str) -> dict | None:
        with self._camera_state_lock:
            value = self.monitor_status.get(camera_key)
            return dict(value) if value else None
