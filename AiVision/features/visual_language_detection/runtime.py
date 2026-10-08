"""逐摄像头串行发送共享帧，隔离视频会话并调度视频提问。"""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
import threading
import time

import cv2

from AiVision.connectors.joyai.client import JoyAIClient, JoyAIError
from AiVision.core.logger import logger
from AiVision.core.settings import settings
from .schema import VideoAnswer, VisualLanguageStatus
from .service import VisualLanguageService


class VideoUnavailable(RuntimeError):
    """当前摄像头无法接收提问。"""


@dataclass
class _CameraState:
    """单摄像头的视频会话、帧去重信息、待答问题和监控状态。"""
    config: dict
    session_id: str
    initialized: bool = False
    first_frame_at: float | None = None
    last_frame_at: float = 0.0
    last_frame: object = None
    last_sent_at: float = 0.0
    question: tuple[str, Future] | None = None
    status: VisualLanguageStatus = field(default_factory=VisualLanguageStatus)


class VisualLanguageRuntime:
    """以线程池并行处理摄像头，同时保证每路会话最多一个在途请求。"""
    def __init__(self, frame_info_provider, prepare_frame, dispatch_observation):
        """绑定模型客户端、事件服务与帧回调，线程池在 start 时创建。"""
        self.client = JoyAIClient()
        self.service = VisualLanguageService()
        self._frame_info_provider = frame_info_provider
        self._prepare_frame = prepare_frame
        self._dispatch_observation = dispatch_observation
        self._lock = threading.RLock()
        self._states: dict[int, _CameraState] = {}
        self._inflight: set[int] = set()
        self._executor: ThreadPoolExecutor | None = None

    def start(self):
        """幂等创建固定容量的 HTTP 工作线程池。"""
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=settings.joyai.max_workers, thread_name_prefix="visual-language",
                )

    def stop(self):
        """使全部会话失效并等待在途任务和远端会话清理结束。"""
        with self._lock:
            for camera_id in list(self._states):
                self.invalidate(camera_id)
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=True)

    def _state(self, camera_id: int, config: dict) -> _CameraState:
        """按事业部与摄像头构造稳定会话标识，首次访问时创建本地状态。"""
        state = self._states.get(camera_id)
        if state is None:
            state = _CameraState(config=config, session_id=f"visual-language-{config['department']}-{camera_id}")
            self._states[camera_id] = state
        return state

    def invalidate(self, camera_id: int):
        """移除状态并结束待答问题，在途任务完成后再重置同名远端会话。"""
        with self._lock:
            state = self._states.pop(camera_id, None)
            if state is None:
                return
            if state.question is not None and not state.question[1].done():
                state.question[1].set_exception(VideoUnavailable("摄像头或检测配置已变更，请重新提问"))
            # 正在发送的旧任务在结束时清理，不能在它运行期间重置同名 session。
            if camera_id not in self._inflight and state.initialized and self._executor is not None:
                self._inflight.add(camera_id)
                self._executor.submit(self._retire, camera_id, state)

    def _retire(self, camera_id: int, state: _CameraState):
        """清理远端视频会话，无论清理是否成功都释放该摄像头的在途标志。"""
        try:
            self.client.reset(state.session_id)
        except JoyAIError as exc:
            logger.warning(f"[visual_language_detection] 会话清理失败 camera_id={camera_id}: {exc}")
        finally:
            with self._lock:
                self._inflight.discard(camera_id)

    def ready(self, camera_id: int, config: dict) -> bool:
        """检查执行器、单摄串行约束和发送周期是否允许下一次任务。"""
        with self._lock:
            state = self._states.get(camera_id)
            return bool(
                self._executor is not None and camera_id not in self._inflight
                and (state is None or time.monotonic() - state.last_sent_at >= config["cap_interval"])
            )

    def offer(self, camera_id: int, config: dict, frame, captured_at: float):
        """按帧对象和采集时间去重，提交摄像头任务并预占在途位置。"""
        with self._lock:
            if not self.ready(camera_id, config):
                return
            state = self._state(camera_id, config)
            # 以采集时间和帧对象去重，不因画面静止而跳过不同采集时刻的帧。
            if frame is None or captured_at <= state.last_frame_at or frame is state.last_frame:
                return
            state.last_sent_at = time.monotonic()
            question = state.question
            if question is not None and question[1].done():
                state.question = question = None
            self._inflight.add(camera_id)
            self._executor.submit(self._execute, camera_id, state, question)

    def ask(self, camera_id: int, config: dict, question: str) -> Future:
        """登记一个待答问题并返回 Future，每路只允许一个尚未完成的问题。"""
        with self._lock:
            if self._executor is None:
                raise VideoUnavailable("指令驱动智慧安防未运行")
            state = self._state(camera_id, config)
            if state.question is not None and not state.question[1].done():
                raise VideoUnavailable("当前摄像头已有问题正在处理，请稍后再试")
            future = Future()
            state.question = (question, future)
            return future

    def status(self, camera_id: int) -> VisualLanguageStatus:
        """复制当前监控状态，尚未建立会话时返回空初始状态。"""
        with self._lock:
            state = self._states.get(camera_id)
            return state.status.model_copy() if state is not None else VisualLanguageStatus()

    def _current(self, camera_id: int, state: _CameraState) -> bool:
        """检查状态对象仍属于当前运行时，用于丢弃失效任务结果。"""
        return self._executor is not None and self._states.get(camera_id) is state

    def _execute(self, camera_id: int, state: _CameraState, question):
        """发送前重新取最新帧，裁剪编码后更新远端视频上下文和本地事件。

        问题随新帧发送；配置失效后丢弃结果并清理旧会话。异常结束当前问题，
        重复相同错误不反复写入事件，最终路径保证释放摄像头在途占用。
        """
        timestamp = datetime.now()
        question_consumed = False
        try:
            with self._lock:
                if not self._current(camera_id, state):
                    return
                if question and question[1].done():
                    if state.question is question:
                        state.question = None
                    question = None
            if not state.initialized:
                self.client.reset(state.session_id)
                state.initialized = True
            cfg = state.config
            # 排队期间只保留摄像头任务，轮到实际发送时重新获取共享最新帧。
            frame, captured_at = self._frame_info_provider(cfg["shm_name"])
            with self._lock:
                if not self._current(camera_id, state):
                    return
                if frame is None:
                    state.status.error = "摄像头暂无新鲜画面，等待恢复"
                    return
                if captured_at <= state.last_frame_at or frame is state.last_frame:
                    return
                state.last_frame_at, state.last_frame = captured_at, frame
                state.last_sent_at = time.monotonic()
                if state.first_frame_at is None:
                    state.first_frame_at = captured_at - cfg["cap_interval"]
            timestamp = datetime.fromtimestamp(captured_at)
            question_consumed = True
            source_frame = frame
            frame = self._prepare_frame(camera_id, cfg, source_frame)
            height, width = frame.shape[:2]
            if width > cfg["max_image_width"]:
                frame = cv2.resize(frame, (cfg["max_image_width"], max(1, round(height * cfg["max_image_width"] / width))))
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, cfg["jpeg_quality"]])
            if not ok:
                raise JoyAIError("摄像头画面 JPEG 编码失败")
            with self._lock:
                if not self._current(camera_id, state):
                    return
            # 提问必须伴随下一张新帧；纯文本请求不会进入 Adapter 的视频记忆链路。
            elapsed = captured_at - state.first_frame_at
            result = self.client.observe(
                session_id=state.session_id, jpeg=encoded.tobytes(),
                prompt=question[0] if question else cfg["observation_prompt"],
                start_seconds=max(0, elapsed - cfg["cap_interval"]), end_seconds=elapsed,
                max_tokens=cfg["max_tokens"], temperature=cfg["temperature"], top_p=cfg["top_p"],
            )
            text, latency = result.text, result.latency_seconds
            with self._lock:
                if not self._current(camera_id, state):
                    return
                state.status.processed_frames += 1
                state.status.latency_seconds = latency
                state.status.error = None
                if text:
                    state.status.latest_result = text
                    state.status.latest_result_at = timestamp
            # 数据库写入不持调度锁，避免慢事务阻塞其他摄像头和配置热更新。
            if text or question:
                self.service.record(
                    camera_id=camera_id, department=cfg["department"],
                    kind="question" if question else "observation",
                    text=text or "本次未产生回答", question=question[0] if question else None,
                    captured_at=timestamp, latency_seconds=latency,
                )
            # 自动观察正文代表监控指令命中的事件；静默和视频提问不进入告警链路。
            if text and not question:
                self._dispatch_observation(camera_id, cfg, source_frame, text)
            with self._lock:
                if self._current(camera_id, state) and question and not question[1].done():
                    question[1].set_result(VideoAnswer(text=text, latency_seconds=latency, captured_at=timestamp))
        except Exception as exc:
            question_consumed = True
            detail = str(exc) if isinstance(exc, JoyAIError) else "指令驱动智慧安防处理失败，请检查后端日志"
            logger.exception(f"[visual_language_detection] 处理失败 camera_id={camera_id}: {detail}")
            record_error = False
            with self._lock:
                if self._current(camera_id, state):
                    previous_error = state.status.error
                    state.status.error = detail
                    if question and not question[1].done():
                        question[1].set_exception(VideoUnavailable(detail))
                    record_error = previous_error != detail
            if record_error:
                try:
                    self.service.record(
                        camera_id=camera_id, department=state.config["department"], kind="error",
                        text=detail, question=question[0] if question else None,
                        captured_at=timestamp, latency_seconds=None,
                    )
                except Exception:
                    logger.exception(f"[visual_language_detection] 错误事件保存失败 camera_id={camera_id}")
        finally:
            with self._lock:
                if question_consumed and question and state.question is question:
                    state.question = None
                retire = not self._current(camera_id, state) and state.initialized
                if not retire:
                    self._inflight.discard(camera_id)
            if retire:
                self._retire(camera_id, state)
