"""公共告警取证：维护证据源的 JPEG 历史缓存并后台编码视频。

普通告警组合配置的前录与后录时段；开放时长事件通过令牌管理，使用
临时顺序缓冲保存完整事件帧。取证源可为摄像头或业务拼图，容量、采样
频率及最大尺寸由存储配置控制，视频完成状态通过回调写回记录。
"""
from __future__ import annotations

import threading
import time
import uuid
import struct
import tempfile
from collections import defaultdict, deque
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from queue import Queue
from typing import BinaryIO, Callable, Iterator, Mapping

import cv2
import numpy as np

from AiVision.core.logger import logger
from AiVision.core.settings import settings
from AiVision.core.video_encoding import VideoEncodingError, ensure_browser_compatible_mp4

# 一次正在录制中的报警视频任务
@dataclass
class _ClipTask:
    """待编码证据任务，普通片段使用内存帧，开放事件使用顺序缓冲。"""
    source_key: str
    video_path: str
    end_time: float            # 当前时间+10秒
    frames: list[bytes]        # 前十秒已经缓存的帧（不是numpy，而是jpeg bytes）
    spool: BinaryIO | None = None

class AlarmEvidenceRecorder:
    """以固定工作线程和容量限制管理多源视频证据。"""
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
        """解析存储配置并建立缓存、任务容量及队列，构造时不开始采样。"""
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
        self._episodes: dict[str, _ClipTask] = {}
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
        """取证启用时建立输出目录并启动定时采样，重复启动不创建额外线程。"""
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
        """停止采样，取消未闭合事件并排空已接受片段，再关闭编码线程。"""
        with self._lock:
            self._stop_event.set()
        thread = self._sampler_thread
        if thread is not None:
            thread.join()
        self._sampler_thread = None
        with self._lock:
            pending = list(self._tasks)
            self._tasks.clear()
            # 未结束的业务事件没有告警归属；停止时取消并释放磁盘和容量。
            for token in tuple(self._episodes):
                self.cancel_episode(token)
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

            for token, episode in tuple(self._episodes.items()):
                if episode.source_key != source_key:
                    continue
                try:
                    self._append_episode_frame(episode, sampled)
                except OSError as exc:
                    # 不能把缺帧的长事件伪装成完整录像，容量也必须立即归还。
                    self.cancel_episode(token)
                    logger.warning(f"[AlarmEvidence] 事件证据写入失败 source={source_key}: {exc}")

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

    def begin_episode(self, source_key: str, trigger_frame: np.ndarray | None = None,
                      timestamp: float | None = None) -> str | None:
        """开始开放时长的证据采集；调用方持有 token，不关心存储和编码。"""
        if not self.enabled or not source_key or self._stop_event.is_set():
            return None
        now = self._clock() if timestamp is None else float(timestamp)
        if isinstance(trigger_frame, np.ndarray) and trigger_frame.size:
            self.record_frame(source_key, trigger_frame, now)
        with self._lock:
            if self._stop_event.is_set() or not self._task_slots.acquire(blocking=False):
                return None
            spool = None
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                # 长事件不能无限占用内存；匿名磁盘文件在取消、完成或进程退出时回收。
                spool = tempfile.TemporaryFile(mode="w+b", dir=self.output_dir)
                token = uuid.uuid4().hex
                task = _ClipTask(source_key, str(self.output_dir / f"{int(now * 1000)}_{token}.mp4"),
                                 float("inf"), [], spool)
                for _, encoded in self._buffers.get(source_key, ()):
                    self._append_episode_frame(task, encoded)
                self._ensure_writers()
                self._episodes[token] = task
                return token
            except (OSError, RuntimeError) as exc:
                if spool is not None:
                    self._close_spool(spool)
                self._task_slots.release()
                logger.warning(f"[AlarmEvidence] 无法开始事件证据 source={source_key}: {exc}")
                return None

    def finish_episode(self, token: str) -> str | None:
        """封存完整事件并交给公共编码队列；同一个 token 只能结束一次。"""
        with self._lock:
            task = self._episodes.pop(token, None)
            if task is None:
                return None
            self._write_queue.put_nowait(task)
            return task.video_path

    def cancel_episode(self, token: str) -> bool:
        """正常结束、配置失效等无需报警的事件不落最终视频。"""
        with self._lock:
            task = self._episodes.pop(token, None)
            if task is None:
                return False
            try:
                self._close_spool(task.spool)
            finally:
                self._task_slots.release()
            return True

    def clear_source(self, source_key: str) -> None:
        """解除一个证据源；已接受的普通片段完成落盘，未结束事件取消。"""
        with self._lock:
            self._buffers.pop(source_key, None)
            self._last_sample.pop(source_key, None)
            for token, task in tuple(self._episodes.items()):
                if task.source_key == source_key:
                    self.cancel_episode(token)
            pending = [task for task in self._tasks if task.source_key == source_key]
            self._tasks = [task for task in self._tasks if task.source_key != source_key]
            for task in pending:
                self._write_queue.put_nowait(task)

    def _finish_due_tasks(self, now: float) -> None:
        """把已到后录截止时间的任务从采集列表转入编码队列。"""
        with self._lock:
            finished = [task for task in self._tasks if now >= task.end_time]
            self._tasks = [task for task in self._tasks if now < task.end_time]
            for task in finished:
                self._write_queue.put_nowait(task)

    @staticmethod
    def _close_spool(spool: BinaryIO) -> None:
        """关闭事件临时缓冲，记录关闭失败而不中断其他任务清理。"""
        try:
            spool.close()
        except OSError as exc:
            logger.warning(f"[AlarmEvidence] 事件证据缓冲关闭失败: {exc}")

    @staticmethod
    def _append_episode_frame(task: _ClipTask, encoded: bytes) -> None:
        """按长度前缀写入完整 JPEG，短写视为取证失败。"""
        record = struct.pack("!I", len(encoded)) + encoded
        if task.spool.write(record) != len(record):
            raise OSError("事件证据帧未完整写入")

    @staticmethod
    def _task_frames(task: _ClipTask) -> Iterator[bytes]:
        """统一遍历内存或顺序缓冲帧，截断或非法帧长度显式报错。"""
        if task.spool is None:
            yield from task.frames
            return
        task.spool.seek(0)
        while header := task.spool.read(4):
            if len(header) != 4:
                raise ValueError("事件证据帧头不完整")
            size = struct.unpack("!I", header)[0]
            encoded = task.spool.read(size)
            if not size or len(encoded) != size:
                raise ValueError("事件证据帧不完整")
            yield encoded

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
        """后台编码任务，并在所有退出路径释放缓冲与容量占位。"""
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
                    try:
                        if task.spool is not None:
                            self._close_spool(task.spool)
                    finally:
                        self._task_slots.release()
                self._write_queue.task_done()

    def _sample_loop(self) -> None:
        """
        持续取帧
        """
        while not self._stop_event.wait(min(0.1, self._sample_interval)):
            # 来源离线也必须结束已接受的普通片段，不能永久占用任务名额。
            self._finish_due_tasks(self._clock())
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
            encoded_frames = self._task_frames(task)
            first_encoded = next(encoded_frames, None)
            if first_encoded is None:
                raise ValueError("报警视频没有可写入帧")
            # 取第一帧确认尺寸
            first_frame = self._decode_frame(first_encoded)
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
                for encoded_frame in chain((first_encoded,), encoded_frames):
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
        """隔离状态回写异常，避免数据库回调故障中断视频编码线程。"""
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
