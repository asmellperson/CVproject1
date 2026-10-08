"""从共享帧缓存取样，复用 ROI 和 yolo_human 推理队列。"""
import time

from AiVision.cameras.frame_reader import frame_reader_registry
from AiVision.core.logger import logger
from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.inference.contracts import INFERENCE_STATUS_OK

from .schema import PersonCheckResult
from .service import AgvPersonCheckService, CheckRequest, PersonCheckError


class AgvPersonCheckConsumer(BaseFunctionConsumer):
    """复用公共推理和告警能力，以外部请求触发有限窗口的人体检测。"""
    def __init__(self, **kwargs):
        """建立请求聚合服务，实际采样仍在消费者线程中执行。"""
        super().__init__(**kwargs)
        self.service = AgvPersonCheckService()

    def submit(self, camera_key: str) -> CheckRequest:
        """校验功能和摄像头可用性，按共享帧标识创建检测请求。"""
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
        """将消费者循环交给请求服务，仅为待判定请求调度采样。"""
        self.service.run(self._sample, lambda: self.running, self._on_result)

    def _on_result(self, request: CheckRequest, result: PersonCheckResult, frame):
        """对最终有人判定触发告警，通知失败不改变已完成的检测结果。"""
        if not result.person_present:
            return
        try:
            self._handle_alarm(request.camera_id, (True, result), frame, config=request.runtime_config)
        except Exception:  # noqa: BLE001 -- 推送异常单独记录，不改写已完成的人体判定。
            logger.exception(f"[agv_person_check] 有人告警失败 request_id={request.request_id}")

    def stop(self):
        """停止帧处理并结束尚未完成的检测请求。"""
        super().stop()
        self.service.stop()

    def update_config(self, camera_id: int):
        """先取消旧配置下的请求，再加载新配置，避免混合采样窗口。"""
        with self._camera_state_lock:
            self.service.cancel_camera(camera_id)
            super().update_config(camera_id)

    def update_status(self, camera_id: int, enabled: bool):
        """启用状态改变时取消当前请求，并同步公共消费者状态。"""
        with self._camera_state_lock:
            self.service.cancel_camera(camera_id)
            super().update_status(camera_id, enabled)

    def _sample(self, request: CheckRequest):
        """只接受请求创建后到达、尚未使用且未过期的帧。

        在摄像头锁内核对配置对象身份；配置更换或摄像头失效时结束请求，
        暂时没有新帧则返回 None，交由调度循环在请求截止前继续尝试。
        """
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
        """将成功的人体推理转为布尔结果；失败状态抛错，不能作为无人证据。"""
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
        """提供包含公共标注的监控画面，检测结果由请求服务独立聚合。"""
        return self._annotated_frame(camera_id)
