"""沿用正式 Consumer 生命周期；HTTP 推理不占用共享帧处理线程。"""

from AiVision.features._shared.consumer import BaseFunctionConsumer
from .runtime import VideoUnavailable, VisualLanguageRuntime


class VisualLanguageConsumer(BaseFunctionConsumer):
    """连接公共摄像头生命周期与独立的视频理解 HTTP 运行时。"""
    def __init__(self, *, frame_info_provider, **kwargs):
        """注入最新帧来源、ROI 准备和观察告警回调。"""
        super().__init__(**kwargs)
        self._frame_info_provider = frame_info_provider
        self.visual_runtime = VisualLanguageRuntime(
            frame_info_provider, self._prepare_frame, self._dispatch_observation,
        )

    def start(self):
        """启动 HTTP 执行器后启动公共消费循环，失败时回收执行器。"""
        self.visual_runtime.start()
        try:
            super().start()
        except Exception:
            self.visual_runtime.stop()
            raise

    def stop(self):
        """确保公共消费停止异常时也关闭视觉理解运行时。"""
        try:
            super().stop()
        finally:
            self.visual_runtime.stop()

    def update_config(self, camera_id: int):
        """先使旧视频会话和提问失效，再替换摄像头配置。"""
        with self._camera_state_lock:
            self.visual_runtime.invalidate(camera_id)
            super().update_config(camera_id)

    def update_status(self, camera_id: int, enabled: bool):
        """启用状态变化时清除旧会话，避免状态恢复后沿用旧上下文。"""
        with self._camera_state_lock:
            self.visual_runtime.invalidate(camera_id)
            super().update_status(camera_id, enabled)

    def ask(self, camera_id: int, department: str, question: str):
        """核对事业部、功能状态及新鲜画面，登记等待下一张新帧回答的问题。"""
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
        """仅在物理配置启用且运行时允许发送时进入处理。"""
        return bool(cfg["camera_enable"] and self.visual_runtime.ready(camera_id, cfg))

    def _get_roi(self, camera_id, frame):
        # HTTP 任务实际发送前再取最新帧并裁剪，避免使用排队前的画面。
        """保留原帧，真正发起 HTTP 任务前再取最新画面并裁剪。"""
        return frame

    def _prepare_frame(self, camera_id, cfg, frame):
        """确认任务仍属于当前配置后执行公共 ROI 裁剪。"""
        with self._camera_state_lock:
            if not self.running or self.config_cache.get(camera_id) is not cfg:
                raise VideoUnavailable("摄像头或检测配置已变更")
            return super()._get_roi(camera_id, frame)

    def _dispatch_observation(self, camera_id, cfg, frame, text):
        """仅将当前配置产生的非空观察结果交给统一告警处理。"""
        with self._camera_state_lock:
            if self.running and self.config_cache.get(camera_id) is cfg:
                self._handle_alarm(camera_id, (True, text), frame, config=cfg)

    def _alarm_context(self, camera_id, result):
        """将视觉理解文本作为告警原因保存。"""
        return {"reason": result[1]}

    def _frame_changed(self, camera_id, roi):
        # 由运行时按采集时间去重，持续理解同一场景也需要按间隔发送新帧。
        """由运行时按采集时间去重，画面静止不阻止持续理解。"""
        return True

    def _process(self, frame, camera_id):
        """读取最新帧与采集时间，构造供后处理调度的配置快照。"""
        cfg = self.config_cache[camera_id]
        frame, captured_at = self._frame_info_provider(cfg["shm_name"])
        return False, (cfg, frame, captured_at)

    def _after_process(self, camera_id, result):
        """在摄像头状态锁内确认配置仍有效，再把任务交给 HTTP 运行时。"""
        cfg, frame, captured_at = result[1]
        with self._camera_state_lock:
            if self.running and self.config_cache.get(camera_id) is cfg:
                self.visual_runtime.offer(camera_id, cfg, frame, captured_at)

    def post_process(self, camera_id, result):
        """保留原始监控画面，文本理解结果通过独立状态接口展示。"""
        return self.frame_cache[camera_id]

    def _preview_background(self, frame, cfg):
        """视频理解预览直接使用最新原图，文本结果不限制视频更新。"""
        return frame
