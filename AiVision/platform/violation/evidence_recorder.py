"""Shared pre/post alarm evidence video recorder."""
from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

import cv2
import numpy as np

from core.logger import logger
from core.settings import settings


@dataclass
class _ClipTask:
    source_key: str
    video_path: str
    end_time: float
    frames: list[bytes]


class AlarmEvidenceRecorder:
    """Sample camera frames, retain a short ring buffer, and emit alarm MP4s."""

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
        storage = settings.storage
        self.enabled = storage.alarm_clip_enabled if enabled is None else bool(enabled)
        self.pre_seconds = max(0.0, storage.alarm_clip_pre_seconds if pre_seconds is None else float(pre_seconds))
        self.post_seconds = max(0.0, storage.alarm_clip_post_seconds if post_seconds is None else float(post_seconds))
        self.fps = max(0.1, storage.alarm_clip_fps if fps is None else float(fps))
        self.max_width = max(160, storage.alarm_clip_max_width if max_width is None else int(max_width))
        root = Path(output_dir or storage.data_path).expanduser().resolve()
        self.output_dir = root / "alarm_clips"
        self._status_callback = status_callback
        self._clock = clock
        self._sample_interval = 1.0 / self.fps
        self._buffers: dict[str, deque[tuple[float, bytes]]] = defaultdict(deque)
        self._last_sample: dict[str, float] = {}
        self._tasks: list[_ClipTask] = []
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._sampler_thread: threading.Thread | None = None
        self._frame_provider: Callable[[], Mapping[str, np.ndarray]] | None = None

    def set_status_callback(self, callback: Callable[[str, str], None] | None) -> None:
        self._status_callback = callback

    def start(self, frame_provider: Callable[[], Mapping[str, np.ndarray]]) -> None:
        if not self.enabled or self._sampler_thread is not None:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._frame_provider = frame_provider
        self._stop_event.clear()
        self._sampler_thread = threading.Thread(
            target=self._sample_loop,
            daemon=True,
            name="alarm-evidence-sampler",
        )
        self._sampler_thread.start()
        logger.info(
            "[AlarmEvidence] 已启动 "
            f"pre={self.pre_seconds}s post={self.post_seconds}s fps={self.fps}"
        )

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._sampler_thread
        if thread is not None:
            thread.join(timeout=3)
        self._sampler_thread = None
        with self._lock:
            pending = list(self._tasks)
            self._tasks.clear()
            self._buffers.clear()
            self._last_sample.clear()
        for task in pending:
            self._finish_task(task)

    def should_sample(self, source_key: str, timestamp: float | None = None) -> bool:
        if not self.enabled:
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
        if not self.enabled or not source_key or not isinstance(frame, np.ndarray) or not frame.size:
            return False
        now = self._clock() if timestamp is None else float(timestamp)
        with self._lock:
            last = self._last_sample.get(source_key)
            if last is not None and now - last < self._sample_interval:
                return False
        try:
            sampled = self._encode_frame(frame)
        except (TypeError, ValueError, cv2.error) as exc:
            logger.warning(f"[AlarmEvidence] 缓冲帧失败 source={source_key}: {exc}")
            return False
        with self._lock:
            last = self._last_sample.get(source_key)
            if last is not None and now - last < self._sample_interval:
                return False
            self._last_sample[source_key] = now
            buffer = self._buffers[source_key]
            buffer.append((now, sampled))
            cutoff = now - self.pre_seconds
            while buffer and buffer[0][0] < cutoff:
                buffer.popleft()

            finished: list[_ClipTask] = []
            for task in self._tasks:
                if task.source_key != source_key:
                    continue
                task.frames.append(sampled)
                if now >= task.end_time:
                    finished.append(task)
            if finished:
                finished_ids = {id(task) for task in finished}
                self._tasks = [task for task in self._tasks if id(task) not in finished_ids]

        for task in finished:
            threading.Thread(
                target=self._finish_task,
                args=(task,),
                daemon=True,
                name="alarm-evidence-writer",
            ).start()
        return True

    def start_alarm(
        self,
        source_key: str,
        trigger_frame: np.ndarray | None = None,
        timestamp: float | None = None,
    ) -> str | None:
        if not self.enabled or not source_key:
            return None
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(f"[AlarmEvidence] 无法创建视频目录 path={self.output_dir}: {exc}")
            return None
        now = self._clock() if timestamp is None else float(timestamp)
        if isinstance(trigger_frame, np.ndarray) and trigger_frame.size:
            self.record_frame(source_key, trigger_frame, now)
        filename = f"{int(now * 1000)}_{uuid.uuid4().hex}.mp4"
        video_path = str(self.output_dir / filename)
        with self._lock:
            frames = [frame for _, frame in self._buffers.get(source_key, ())]
            task = _ClipTask(
                source_key=source_key,
                video_path=video_path,
                end_time=now + self.post_seconds,
                frames=frames,
            )
            if self.post_seconds <= 0:
                threading.Thread(target=self._finish_task, args=(task,), daemon=True).start()
            else:
                self._tasks.append(task)
        return video_path

    def _sample_loop(self) -> None:
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
                self.record_frame(str(source_key), frame, now)

    def _finish_task(self, task: _ClipTask) -> None:
        status = "failed"
        try:
            if not task.frames:
                raise ValueError("报警视频没有可写入帧")
            first_frame = self._decode_frame(task.frames[0])
            height, width = first_frame.shape[:2]
            writer = cv2.VideoWriter(
                task.video_path,
                cv2.VideoWriter_fourcc(*"mp4v"),
                self.fps,
                (width, height),
            )
            if not writer.isOpened():
                raise OSError(f"无法创建报警视频: {task.video_path}")
            try:
                for encoded_frame in task.frames:
                    frame = self._decode_frame(encoded_frame)
                    if frame.shape[:2] != (height, width):
                        frame = cv2.resize(frame, (width, height))
                    writer.write(frame)
            finally:
                writer.release()
            status = "ready"
        except (OSError, TypeError, ValueError, cv2.error) as exc:
            logger.warning(f"[AlarmEvidence] 视频生成失败 path={task.video_path}: {exc}")
        callback = self._status_callback
        if callback is not None:
            try:
                callback(task.video_path, status)
            except Exception as exc:
                logger.warning(f"[AlarmEvidence] 视频状态回写失败 path={task.video_path}: {exc}")

    def _encode_frame(self, frame: np.ndarray) -> bytes:
        height, width = frame.shape[:2]
        sampled = frame
        if width > self.max_width:
            scale = self.max_width / width
            sampled = cv2.resize(
                frame,
                (self.max_width, max(1, int(height * scale))),
            )
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
        frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None or not frame.size:
            raise ValueError("报警视频缓冲帧 JPEG 解码失败")
        return frame


alarm_evidence_recorder = AlarmEvidenceRecorder()
