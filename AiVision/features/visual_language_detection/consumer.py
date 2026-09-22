"""沿用正式 Consumer 生命周期；HTTP 推理不占用共享帧处理线程。"""

from AiVision.features._shared.consumer import BaseFunctionConsumer
from .runtime import VideoUnavailable, VisualLanguageRuntime


class VisualLanguageConsumer(BaseFunctionConsumer):
    def __init__(self, *, frame_info_provider, **kwargs):
        super().__init__(**kwargs)
        self._frame_info_provider = frame_info_provider
        self.visual_runtime = VisualLanguageRuntime(
            frame_info_provider, self._prepare_frame, self._dispatch_alarm,
        )

    def start(self):
        self.visual_runtime.start()
        try:
            super().start()
        except Exception:
            self.visual_runtime.stop()
            raise

    def stop(self):
        try:
            super().stop()
        finally:
            self.visual_runtime.stop()

    def update_config(self, camera_id: int):
        with self._camera_state_lock:
            self.visual_runtime.invalidate(camera_id)
            super().update_config(camera_id)

    def update_status(self, camera_id: int, enabled: bool):
        with self._camera_state_lock:
            self.visual_runtime.invalidate(camera_id)
            super().update_status(camera_id, enabled)

    def ask(self, camera_id: int, department: str, question: str):
        with self._camera_state_lock:
            cfg = self.config_cache.get(camera_id)
            if (not self.running or cfg is None or cfg["department"] != department
                    or not cfg["camera_enable"] or not self.is_camera_active(cfg["shm_name"])):
                raise VideoUnavailable("摄像头未运行或未添加到指令驱动智慧安防")
            frame, _ = self._frame_info_provider(cfg["shm_name"])
            if frame is None:
                raise VideoUnavailable("摄像头暂无新鲜画面，请稍后重试")
            return self.visual_runtime.ask(camera_id, cfg, question)

    def _should_process_now(self, camera_id, cfg):
        return bool(cfg["camera_enable"] and self.visual_runtime.ready(camera_id, cfg))

    def _get_roi(self, camera_id, frame):
        # HTTP 任务实际发送前再取最新帧并裁剪，避免使用排队前的画面。
        return frame

    def _prepare_frame(self, camera_id, cfg, frame):
        with self._camera_state_lock:
            if not self.running or self.config_cache.get(camera_id) is not cfg:
                raise VideoUnavailable("摄像头或检测配置已变更")
            return super()._get_roi(camera_id, frame)

    def _dispatch_alarm(self, camera_id, cfg, frame, reason):
        with self._camera_state_lock:
            if self.running and self.config_cache.get(camera_id) is cfg:
                self._handle_alarm(camera_id, (True, reason), frame, config=cfg)

    def _alarm_context(self, camera_id, result):
        return {"reason": result[1]}

    def _frame_changed(self, camera_id, roi):
        # 由运行时按采集时间去重，持续理解同一场景也需要按间隔发送新帧。
        return True

    def _process(self, frame, camera_id):
        cfg = self.config_cache[camera_id]
        frame, captured_at = self._frame_info_provider(cfg["shm_name"])
        return False, (cfg, frame, captured_at)

    def _after_process(self, camera_id, result):
        cfg, frame, captured_at = result[1]
        with self._camera_state_lock:
            if self.running and self.config_cache.get(camera_id) is cfg:
                self.visual_runtime.offer(camera_id, cfg, frame, captured_at)

    def post_process(self, camera_id, result):
        return self.frame_cache[camera_id]
