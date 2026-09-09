"""
正常一段报警视频大约是报警前10秒*5 FPS = 50帧 + 报警后10秒*5 FPS=50帧，合起来约20秒、100帧

orchestrator将frame_reader_registry.latest_frames交给EvidenceRecorder，让它持续从latest_frames 取每个摄像头的最新画面。

一个报警视频的完整过程：
    摄像头持续出画面 -> EvidenceRecorder按5 FPS采样 -> 每帧缩到最大宽度960 -> 压缩成JPEG bytes -> 放进摄像头自己的deque缓存 -> 始终只保留最近约10秒50帧图像
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Callable, Mapping

import cv2
import numpy as np

from AiVision.core.logger import logger
from AiVision.core.settings import settings
from AiVision.core.video_encoding import VideoEncodingError, ensure_browser_compatible_mp4

# 一次正在录制中的报警视频任务
@dataclass
class _ClipTask:
    source_key: str
    video_path: str
    end_time: float            # 当前时间+10秒
    frames: list[bytes]        # 前十秒已经缓存的帧（不是numpy，而是jpeg bytes）

class AlarmEvidenceRecorder:
    def __init__(
        self,
        output_dir: str | Path | None = None,
        *,
        enabled: bool | None = None,
        pre_seconds: float | None = None,
        post_seconds: float | None = None,
        fps: float | None = None,
        max_width: int | None = None,
        status_callback: Callable[[str, str], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        # Storage 配置
        storage = settings.storage
        self.enabled = storage.alarm_clip_enabled if enabled is None else bool(enabled)
        # 前后录的秒数，默认十秒
        self.pre_seconds = max(0.0, storage.alarm_clip_pre_seconds if pre_seconds is None else float(pre_seconds))
        self.post_seconds = max(0.0, storage.alarm_clip_post_seconds if post_seconds is None else float(post_seconds))
        # fps，默认5fps
        self.fps = max(0.1, storage.alarm_clip_fps if fps is None else float(fps))
        # 最大宽度
        self.max_width = max(160, storage.alarm_clip_max_width if max_width is None else int(max_width))
        # 视频路径
        root = Path(output_dir or storage.data_path).expanduser().resolve()
        self.output_dir = root / "alarm_clips"
        self._status_callback = status_callback
        self._clock = clock
        self._sample_interval = 1.0 / self.fps
        # 历史缓存
        self._buffers: dict[str, deque[tuple[float, bytes]]] = defaultdict(deque)
        # 记录每个source上一次真正采样的时间
        self._last_sample: dict[str, float] = {}
        # 当前正在等待报警后十秒结束录像任务
        self._tasks: list[_ClipTask] = []
        # RLock：可重入锁
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_count = storage.alarm_clip_workers
        self._task_slots = threading.BoundedSemaphore(storage.alarm_clip_max_tasks)
        self._write_queue: Queue[_ClipTask | None] = Queue(maxsize=storage.alarm_clip_max_tasks)
        self._writer_threads: list[threading.Thread] = []
        self._sampler_thread: threading.Thread | None = None
        self._frame_provider: Callable[[], Mapping[str, np.ndarray]] | None = None

    def set_status_callback(self, callback: Callable[[str, str], None] | None) -> None:
        """回调函数"""
        self._status_callback = callback

    def start(self, frame_provider: Callable[[], Mapping[str, np.ndarray]]) -> None:
        """
        frame_provider:需要帧的时候，调用这个函数就能得到所有Camera最新画面
        EvidenceRecorder
        ↓
        自己定时调用 frame_provider()
        ↓
        拿 latest_frames
        """
        with self._lifecycle_lock:
            self._start(frame_provider)

    def _start(self, frame_provider: Callable[[], Mapping[str, np.ndarray]]) -> None:
        if not self.enabled or self._sampler_thread is not None:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._frame_provider = frame_provider
        self._stop_event.clear()
        self._sampler_thread = threading.Thread(
            target=self._sample_loop,             # 真正持续裁帧
            daemon=True,
            name="alarm-evidence-sampler",
        )
        self._sampler_thread.start()
        logger.info(
            "[AlarmEvidence] 已启动 "
            f"pre={self.pre_seconds}s post={self.post_seconds}s fps={self.fps}"
        )

    def stop(self) -> None:
        """停止采帧"""
        with self._lifecycle_lock:
            self._stop()

    def _stop(self) -> None:
        with self._lock:
            self._stop_event.set()
        thread = self._sampler_thread
        if thread is not None:
            thread.join()
        self._sampler_thread = None
        with self._lock:
            pending = list(self._tasks)
            self._tasks.clear()
            self._buffers.clear()
            self._last_sample.clear()
            for task in pending:
                self._write_queue.put_nowait(task)
        # 停止期间保留已接受任务，等落盘和状态回写完成后再关闭 worker。
        self._write_queue.join()
        for _ in self._writer_threads:
            self._write_queue.put(None)
        for worker in self._writer_threads:
            worker.join()
        self._writer_threads.clear()

    def should_sample(self, source_key: str, timestamp: float | None = None) -> bool:
        """当前的source是否到了下一次采样的时间"""
        if not self.enabled or self._stop_event.is_set():
            return False
        now = self._clock() if timestamp is None else float(timestamp)
        with self._lock:
            last = self._last_sample.get(source_key)
            return last is None or now - last >= self._sample_interval

    def record_frame(
        self,
        source_key: str,
        frame: np.ndarray | None,
        timestamp: float | None = None,
    ) -> bool:
        """把一帧写入"""
        # 录像关闭、source_key为空、frame不是NumPy数组、frame是空图这些情况就不要这个帧
        if not self.enabled or not source_key or not isinstance(frame, np.ndarray) or not frame.size:
            return False
        now = self._clock() if timestamp is None else float(timestamp)
        with self._lock:
            # 做FPS检查
            if self._stop_event.is_set():
                return False
            last = self._last_sample.get(source_key)
            if last is not None and now - last < self._sample_interval:
                return False
        try:
            # _encode_frame将原始帧编码为bytes
            sampled = self._encode_frame(frame)
        except (TypeError, ValueError, cv2.error) as exc:
            logger.warning(f"[AlarmEvidence] 缓冲帧失败 source={source_key}: {exc}")
            return False
        with self._lock:
            # 第二次检查FPS
            if self._stop_event.is_set():
                return False
            last = self._last_sample.get(source_key)
            if last is not None and now - last < self._sample_interval:
                return False
            # 写入
            self._last_sample[source_key] = now
            buffer = self._buffers[source_key]
            buffer.append((now, sampled))
            cutoff = now - self.pre_seconds
            # 早于10秒前的旧帧删掉
            while buffer and buffer[0][0] < cutoff:
                buffer.popleft()

            finished: list[_ClipTask] = []
            for task in self._tasks:
                # 看看有没有正在录这个source的报警视频
                if task.source_key != source_key:
                    continue
                # 报警后的每个新采样加入
                task.frames.append(sampled)
                # 采到10秒以后就结束
                if now >= task.end_time:
                    finished.append(task)
            if finished:
                finished_ids = {id(task) for task in finished}
                self._tasks = [task for task in self._tasks if id(task) not in finished_ids]

            for task in finished:
                # _finish_task负责做MP4（采样线程只负责采样）
                self._write_queue.put_nowait(task)
        return True

    def start_alarm(
        self,
        source_key: str,
        trigger_frame: np.ndarray | None = None,
        timestamp: float | None = None,
    ) -> str | None:
        """真正的报警的时刻，AlarmDispatcher 发生告警时会调用它"""
        # 检查录像是否启用
        if not self.enabled or not source_key or self._stop_event.is_set():
            return None
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(f"[AlarmEvidence] 无法创建视频目录 path={self.output_dir}: {exc}")
            return None
        now = self._clock() if timestamp is None else float(timestamp)
        # 如果传了报警瞬间的帧，尽可能把这一帧也计入缓存
        if isinstance(trigger_frame, np.ndarray) and trigger_frame.size:
            self.record_frame(source_key, trigger_frame, now)
        # 视频文件名：包含毫秒时间戳和UUID
        filename = f"{int(now * 1000)}_{uuid.uuid4().hex}.mp4"
        video_path = str(self.output_dir / filename)
        with self._lock:
            if self._stop_event.is_set():
                return None
            # 为采帧、排队、编码整个生命周期预留名额，满载时不创建 pending 视频引用。
            if not self._task_slots.acquire(blocking=False):
                logger.warning(f"[AlarmEvidence] 录像任务已满，跳过本次视频 source={source_key}")
                return None
            try:
                self._ensure_writers()
            except RuntimeError as exc:
                self._task_slots.release()
                logger.warning(f"[AlarmEvidence] 无法启动录像 worker，跳过本次视频: {exc}")
                return None
            # 报警前10秒从哪里来，当前摄像头的历史buffer全部复制进ClipTask.frames
            frames = [frame for _, frame in self._buffers.get(source_key, ())]
            task = _ClipTask(
                source_key=source_key,
                video_path=video_path,
                end_time=now + self.post_seconds,                # 未来继续append10秒画面
                frames=frames,
            )
            # 小于0就立即_finish_tasks，这样只有历史buffer的视频
            if self.post_seconds <= 0:
                self._write_queue.put_nowait(task)
            else:
                self._tasks.append(task)
        return video_path

    def _ensure_writers(self) -> None:
        """持有 _lock 时调用；手动送帧和定时采帧共用同一组固定 worker。"""
        if self._writer_threads:
            return
        for index in range(self._worker_count):
            worker = threading.Thread(
                target=self._write_loop,
                daemon=True,
                name=f"alarm-evidence-writer-{index + 1}",
            )
            worker.start()
            self._writer_threads.append(worker)

    def _write_loop(self) -> None:
        while True:
            task = self._write_queue.get()
            try:
                if task is None:
                    return
                self._finish_task(task)
            except Exception as exc:
                logger.exception(f"[AlarmEvidence] 录像 worker 处理失败: {exc}")
                if task is not None:
                    self._report_status(task.video_path, "failed")
            finally:
                if task is not None:
                    self._task_slots.release()
                self._write_queue.task_done()

    def _sample_loop(self) -> None:
        """
        持续取帧
        """
        while not self._stop_event.wait(min(0.1, self._sample_interval)):
            provider = self._frame_provider
            if provider is None:
                continue
            try:
                frames = list(provider().items())
            except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                logger.warning(f"[AlarmEvidence] 获取摄像头帧失败: {exc}")
                continue
            now = self._clock()
            for source_key, frame in frames:
                # record_frame自己判断距离上次报警是否大于0.2秒，满足才真正缓存
                self.record_frame(str(source_key), frame, now)

    def _finish_task(self, task: _ClipTask) -> None:
        """生成MP4"""
        status = "failed"
        try:
            if not task.frames:
                raise ValueError("报警视频没有可写入帧")
            # 取第一帧确认尺寸
            first_frame = self._decode_frame(task.frames[0])
            height, width = first_frame.shape[:2]
            # 创建cv2.VideoWriter
            writer = cv2.VideoWriter(
                task.video_path,
                cv2.VideoWriter_fourcc(*"mp4v"),        # OpenCV 使用 MPEG-4 Part 2 类编码写 MP4。
                self.fps,
                (width, height),
            )
            if not writer.isOpened():
                raise OSError(f"无法创建报警视频: {task.video_path}")
            try:
                # 一帧一帧写视频
                for encoded_frame in task.frames:
                    # 恢复成numpy图像
                    frame = self._decode_frame(encoded_frame)
                    # 检查尺寸
                    if frame.shape[:2] != (height, width):
                        frame = cv2.resize(frame, (width, height))
                    # 把这一帧写进MP4
                    writer.write(frame)
            finally:
                # 必须释放
                writer.release()
            # 检查视频格式，换成浏览器兼容的格式
            ensure_browser_compatible_mp4(task.video_path)
            # 成功以后状态设为ready
            status = "ready"
        # 捕获异常
        except (OSError, TypeError, ValueError, cv2.error, VideoEncodingError) as exc:
            logger.warning(f"[AlarmEvidence] 视频生成失败 path={task.video_path}: {exc}")
        # 回写数据库状态
        self._report_status(task.video_path, status)

    def _report_status(self, video_path: str, status: str) -> None:
        callback = self._status_callback
        if callback is not None:
            try:
                # 数据库状态ready还是failed
                callback(video_path, status)
            except Exception as exc:
                logger.warning(f"[AlarmEvidence] 视频状态回写失败 path={video_path}: {exc}")

    def _encode_frame(self, frame: np.ndarray) -> bytes:
        """把原始帧压成JPEG缓存"""
        height, width = frame.shape[:2]
        sampled = frame
        if width > self.max_width:
            scale = self.max_width / width
            sampled = cv2.resize(
                frame,
                (self.max_width, max(1, int(height * scale))),
            )
        # 使用cv2.imencode压缩成JPEG（JPEG质量=82）
        ok, encoded = cv2.imencode(
            ".jpg",
            sampled,
            [int(cv2.IMWRITE_JPEG_QUALITY), 82],
        )
        if not ok:
            raise ValueError("报警视频缓冲帧 JPEG 编码失败")
        return encoded.tobytes()

    @staticmethod
    def _decode_frame(encoded: bytes) -> np.ndarray:
        """怎么把JPEG恢复成图像写视频"""
        # 使用cv2.imdecode恢复
        frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None or not frame.size:
            raise ValueError("报警视频缓冲帧 JPEG 解码失败")
        return frame


alarm_evidence_recorder = AlarmEvidenceRecorder()
