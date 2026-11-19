"""摄像头逐脸身份识别、监控结果与冷却记录。"""
from __future__ import annotations

import time

import cv2

from AiVision.features._shared.authorization_refresh import AUTHORIZATION_FAILURE_RETRY_SECONDS, AuthorizationRefresh
from AiVision.features._shared.pipelined_consumer import PipelinedConsumer
from AiVision.features.face_recognition.library.constants import (
    AUTHORIZATION_REFRESH_SECONDS, DEFAULT_DETECTION_THRESHOLD, DEFAULT_RECORD_COOLDOWN_SECONDS,
    DEFAULT_SIMILARITY_THRESHOLD,
)
from AiVision.features.face_recognition.library.service import FaceLibraryService
from AiVision.inference.contracts import INFERENCE_STATUS_UNAVAILABLE
from .records import RecognitionRecorder


_AUTHORIZATION_REFRESH_LEAD_SECONDS = 0.5


class FaceRecognitionConsumer(PipelinedConsumer):
    """将逐脸身份匹配与本地通行授权结合，输出监控、告警和识别记录。"""

    inference_model = "insightface"
    max_inflight = 2

    def __init__(self, *args, **kwargs):
        """初始化异步记录器、人员服务及定期刷新的授权 ID 集合。"""
        super().__init__(*args, **kwargs)
        self.monitor_status: dict[str, dict] = {}
        self.recorder = RecognitionRecorder()
        self.library = FaceLibraryService()
        self._authorizations: dict[str, tuple[float, set[int]]] = {}
        self._authorization_refresh = AuthorizationRefresh(
            self.feature_name, snapshot_seconds=AUTHORIZATION_REFRESH_SECONDS,
        )
        self._next_authorization_attempt = 0.0

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
        with self._camera_state_lock:
            self._authorization_refresh.invalidate()
            self._authorizations.clear()
            self.monitor_status.clear()
            self._next_authorization_attempt = 0.0
        self.recorder.stop()

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        """清除摄像头监控结果与识别冷却，避免重启沿用旧状态。"""
        super()._clear_camera_state(camera_id, shm_name)
        self.recorder.clear_camera(camera_id)
        if shm_name:
            self.monitor_status.pop(shm_name, None)

    def _invalidate_sample(self, camera_id: int) -> None:
        super()._invalidate_sample(camera_id)
        config = self.config_cache.get(camera_id)
        if config is not None:
            self.monitor_status.pop(config["shm_name"], None)

    def _inference_parameters(self, camera_id: int, config: dict) -> dict:
        return {
            "conf": config.get("detection_threshold", DEFAULT_DETECTION_THRESHOLD),
            "similarity_threshold": config.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD),
        }

    def _before_camera_round(self) -> None:
        with self._camera_state_lock:
            now = time.monotonic()
            result = self._authorization_refresh.poll()
            if result is not None:
                if result.value is None or result.sampled_at is None:
                    for department in result.context:
                        self._authorizations.pop(department, None)
                    self._next_authorization_attempt = now + AUTHORIZATION_FAILURE_RETRY_SECONDS
                else:
                    expires_at = result.sampled_at + AUTHORIZATION_REFRESH_SECONDS
                    self._authorizations.update({
                        department: (expires_at, ids) for department, ids in result.value.items()
                    })
            if now >= self._next_authorization_attempt and not self._authorization_refresh.in_progress:
                due = sorted({
                    cfg["department"] for cfg in self.config_cache.values()
                    if cfg.get("camera_enable", True) and cfg.get("department")
                    and self.is_camera_active(cfg["shm_name"])
                    and self._authorizations.get(cfg["department"], (0.0, ()))[0]
                    <= now + _AUTHORIZATION_REFRESH_LEAD_SECONDS
                })
                if due:
                    self._authorization_refresh.submit(
                        tuple(due), lambda mark: self.library.get_allowed_person_ids_by_department(due, on_sampled=mark),
                    )
        super()._before_camera_round()

    def _process(self, roi, camera_id):
        """识别人脸后查询本地授权，未知或未授权人员均形成告警候选。

        推理或授权暂不可用时撤销当前结论，避免使用过期授权或误发告警。
        """
        sample = self._samples.pop(camera_id)
        response = self.resolve_inference(sample.request)
        if response["status"] != "ok" or not response["detections"]:
            return False, response
        authorization = self._authorizations.get(sample.config.get("department"))
        if authorization is None or time.monotonic() >= authorization[0]:
            return False, {**response, "status": INFERENCE_STATUS_UNAVAILABLE, "detections": []}
        allowed_person_ids = authorization[1]
        for detection in response["detections"]:
            detection["is_allowed"] = bool(
                detection["matched"] and detection["person_id"] in allowed_person_ids
            )
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
            "updated_at_s": self._frame_sampled_at[camera_id],
        }
        value = config
        if value.get("record_enabled", True):
            self.recorder.record(
                camera_id, detections, float(value.get("record_cooldown_seconds", DEFAULT_RECORD_COOLDOWN_SECONDS)),
                frame=frame,
            )
        return frame

    def get_monitor_status(self, camera_key: str) -> dict | None:
        """读取原子替换的状态快照，避免状态接口排在摄像头处理之后。"""
        value = self.monitor_status.get(camera_key)
        return dict(value) if value else None
