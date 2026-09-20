"""从共享帧缓存取样，复用 ROI 和 yolo_human 推理队列。"""
import time

from AiVision.cameras.frame_reader import frame_reader_registry
from AiVision.core.logger import logger
from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.inference.contracts import INFERENCE_STATUS_OK

from .schema import PersonCheckResult
from .service import AgvPersonCheckService, CheckRequest, PersonCheckError


class AgvPersonCheckConsumer(BaseFunctionConsumer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = AgvPersonCheckService()

    def submit(self, camera_key: str) -> CheckRequest:
        with self._camera_state_lock:
            if not self.running:
                raise PersonCheckError("unavailable", "AGV 检测功能未运行")
            for camera_id, cfg in self.config_cache.items():
                if cfg["shm_name"] == camera_key:
                    if not cfg["camera_enable"] or not self.is_camera_active(camera_key):
                        raise PersonCheckError("unavailable", "摄像头未运行")
                    return self.service.submit(camera_id, camera_key, cfg)
            raise PersonCheckError("not_found", "摄像头不存在或未启用 AGV 检测")

    def _run(self):
        # 保留统一生命周期和结果路由，只把连续检测改为 HTTP 请求驱动。
        self.service.run(self._sample, lambda: self.running, self._on_result)

    def _on_result(self, request: CheckRequest, result: PersonCheckResult, frame):
        if not result.person_present:
            return
        try:
            self._handle_alarm(request.camera_id, (True, result), frame, config=request.runtime_config)
        except Exception:  # noqa: BLE001 -- 推送异常单独记录，不改写已完成的人体判定。
            logger.exception(f"[agv_person_check] 有人告警失败 request_id={request.request_id}")

    def stop(self):
        super().stop()
        self.service.stop()

    def update_config(self, camera_id: int):
        with self._camera_state_lock:
            self.service.cancel_camera(camera_id)
            super().update_config(camera_id)

    def update_status(self, camera_id: int, enabled: bool):
        with self._camera_state_lock:
            self.service.cancel_camera(camera_id)
            super().update_status(camera_id, enabled)

    def _sample(self, request: CheckRequest):
        with self._camera_state_lock:
            if request.future.done():
                return None
            cfg = self.config_cache.get(request.camera_id)
            if (not self.running or cfg is not request.runtime_config
                    or not cfg["camera_enable"] or not self.is_camera_active(request.camera_key)):
                raise PersonCheckError("unavailable", "摄像头或检测配置已不可用")
            frame = self.latest_frames.get(request.camera_key)
            captured_at = frame_reader_registry.latest_frame_times.get(request.camera_key, 0.0)
            if (frame is None or frame is request.last_frame
                    or frame is not self.latest_frames.get(request.camera_key)
                    or captured_at < request.created_at
                    or time.time() - captured_at > request.config.frame_max_age_seconds):
                return None
            # 只计数请求发起后到达的不同帧，不使用帧差跳过静止画面。
            self.frame_cache[request.camera_id] = frame
            roi = self._get_roi(request.camera_id, frame)
            result = self._process(roi, request.camera_id)
            if not self.running:
                raise PersonCheckError("unavailable", "AGV 检测功能已停止")
            self.result_dict[request.camera_key] = self.post_process(request.camera_id, result)
            self.result_updated_at[request.camera_key] = time.time()
            return frame, result[1]

    def _process(self, roi, camera_id: int) -> tuple[bool, PersonCheckResult]:
        cfg = self.config_cache[camera_id]
        outcome = self.dispatch_inference_sync(
            camera_id, "yolo_human", roi,
            task_meta={"conf": cfg["confidence_threshold"], "iou": cfg["iou_threshold"]},
            timeout=cfg["inference_timeout_seconds"],
        )
        if outcome["status"] != INFERENCE_STATUS_OK:
            raise PersonCheckError("inference_failed", "人体推理未成功，不能判定无人")
        # yolo_human 已限制为人体类别；告警由最终判定统一触发。
        return False, PersonCheckResult(person_present=bool(outcome["detections"]))

    def post_process(self, camera_id: int, result: tuple):
        return self._annotated_frame(camera_id)
