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
    """将逐脸身份匹配与本地通行授权结合，输出监控、告警和识别记录。"""
    def __init__(self, *args, **kwargs):
        """初始化异步记录器、人员服务及定期刷新的授权 ID 集合。"""
        super().__init__(*args, **kwargs)
        self.monitor_status: dict[str, dict] = {}
        self.recorder = RecognitionRecorder()
        self.library = FaceLibraryService()
        self._allowed_person_ids: set[int] = set()
        self._authorization_refresh_at = 0.0

    def start(self):
        """先启动记录器，再启动检测；检测启动失败时同步释放记录线程。"""
        self.recorder.start()
        try:
            super().start()
        except Exception:
            self.recorder.stop()
            raise

    def stop(self):
        """停止产生检测结果后排空记录任务。"""
        super().stop()
        self.recorder.stop()

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        """清除摄像头监控结果与识别冷却，避免重启沿用旧状态。"""
        super()._clear_camera_state(camera_id, shm_name)
        self.recorder.clear_camera(camera_id)
        if shm_name:
            self.monitor_status.pop(shm_name, None)

    def _should_process_now(self, camera_id: int, cfg: dict) -> bool:
        """按摄像头配置的采样周期控制识别频率。"""
        interval = float(cfg.get("cap_interval", DEFAULT_CAPTURE_INTERVAL))
        return time.time() - self._last_process_at.get(camera_id, 0.0) >= interval

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        """允许静止画面继续识别，使授权变化和记录冷却能及时生效。"""
        return True

    def _process(self, roi, camera_id):
        """识别人脸后查询本地授权，未知或未授权人员均形成告警候选。

        推理失败返回原失败响应；授权缓存刷新失败交由上层处理，避免使用
        过期权限继续判定。身份匹配与通行授权是两个独立条件。
        """
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

    def _alarm_context(self, camera_id: int, result: tuple) -> dict:
        """从违规人脸中选择告警主体，优先已识别但未授权的人员并保留全部违规详情。"""
        offending = [detection.copy() for detection in result[1]["detections"] if not detection["is_allowed"]]
        # 主主体优先取检测顺序中的首个已识别未授权人员；全为未知人员时取首个。
        primary = next((detection for detection in offending if detection["matched"]), offending[0])
        matched = primary["matched"]
        metadata = {key: primary[key] for key in ("similarity", "matched", "is_allowed")}
        if matched:
            metadata.update({key: primary[key] for key in (
                "person_id", "person_name", "job_no", "person_code", "org_index_code",
            )})
        metadata["offending_detections"] = offending
        metadata["camera_name"] = self.config_cache[camera_id]["name"]
        return {
            "subject_type": "face_person" if matched else "unknown_face",
            "subject_id": str(primary["person_id"]) if matched else "",
            "subject_name": primary["person_name"] if matched else "未知人员",
            "reason": "unauthorized" if matched else "unknown",
            "metadata": metadata,
        }

    def post_process(self, camera_id, result):
        """还原人脸框坐标，更新结构化监控状态，并按配置异步保存识别记录。"""
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
        """在摄像头锁内返回监控状态的浅拷贝，未生成状态时返回 None。"""
        with self._camera_state_lock:
            value = self.monitor_status.get(camera_key)
            return dict(value) if value else None
