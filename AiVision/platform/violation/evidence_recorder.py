# 文件说明：实现`evidence_recorder` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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
from core.video_encoding import VideoEncodingError, ensure_browser_compatible_mp4


# 功能：定义 `_ClipTask` 类，封装`evidence_recorder` 模块相关的状态、约束与操作
# 参数：
#   - `source_key`（str）：`source_key` 对应的业务输入值
#   - `video_path`（str）：`video_path` 对应的业务输入值
#   - `end_time`（float）：`end_time` 对应的业务输入值
#   - `frames`（list[bytes]）：`frames` 对应的业务输入值
# 返回：_ClipTask；返回新建的 `_ClipTask` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/violation/evidence_recorder.py` 的 `AlarmEvidenceRecorder::start_alarm` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class _ClipTask:
    source_key: str
    video_path: str
    end_time: float
    frames: list[bytes]


# 功能：Sample camera frames, retain a short ring buffer, and emit alarm MP4s；输入与输出详见下方说明
# 参数：
#   - `output_dir`（str | Path | None）：`output_dir` 对应的业务输入值；默认值为 `None`
#   - `enabled`（bool | None）：是否启用相应能力；默认值为 `None`
#   - `pre_seconds`（float | None）：`pre_seconds` 对应的时间间隔或时长；默认值为 `None`
#   - `post_seconds`（float | None）：`post_seconds` 对应的时间间隔或时长；默认值为 `None`
#   - `fps`（float | None）：`fps` 对应的业务输入值；默认值为 `None`
#   - `max_width`（int | None）：`max_width` 对应的业务输入值；默认值为 `None`
#   - `status_callback`（Callable[[str, str], None] | None）：`status_callback` 对应的回调处理器；默认值为 `None`
#   - `clock`（Callable[[], float]）：`clock` 对应的业务输入值；默认值为 `time.time`
# 返回：AlarmEvidenceRecorder；返回新建的 `AlarmEvidenceRecorder` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_alarm_evidence_recorder.py` 的 `test_recorder_keeps_pre_and_post_alarm_frames`
#         实例化本符号；`AiVision/tests/test_alarm_evidence_recorder.py` 的 `test_recorder_throttles_samples_and_discards_expired_prebuffer`
#         实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AlarmEvidenceRecorder:
    """Sample camera frames, retain a short ring buffer, and emit alarm MP4s."""

    # 功能：初始化或配置 `__init__` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `output_dir`（str | Path | None）：`output_dir` 对应的业务输入值；默认值为 `None`
    #   - `enabled`（bool | None）：是否启用相应能力；默认值为 `None`
    #   - `pre_seconds`（float | None）：`pre_seconds` 对应的时间间隔或时长；默认值为 `None`
    #   - `post_seconds`（float | None）：`post_seconds` 对应的时间间隔或时长；默认值为 `None`
    #   - `fps`（float | None）：`fps` 对应的业务输入值；默认值为 `None`
    #   - `max_width`（int | None）：`max_width` 对应的业务输入值；默认值为 `None`
    #   - `status_callback`（Callable[[str, str], None] | None）：`status_callback` 对应的回调处理器；默认值为 `None`
    #   - `clock`（Callable[[], float]）：`clock` 对应的业务输入值；默认值为 `time.time`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`bool`、`max`、`float`、`int`、`Path(output_dir or storage.data_path).expanduser().resolve`、`Path(output_dir or
    #          storage.data_path).expanduser`、`Path`、`defaultdict`、`threading.RLock`、`threading.Event`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：更新或保存 `set_status_callback` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `callback`（Callable[[str, str], None] | None）：任务完成时调用的回调函数
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::start` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def set_status_callback(self, callback: Callable[[str, str], None] | None) -> None:
        self._status_callback = callback

    # 功能：启动或执行 `start` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame_provider`（Callable[[], Mapping[str, np.ndarray]]）：`frame_provider` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.output_dir.mkdir`、`self._stop_event.clear`、`threading.Thread`、`self._sampler_thread.start`、`logger.info`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
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

    # 功能：停止并释放 `stop` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.set`、`thread.join`、`list`、`self._tasks.clear`、`self._buffers.clear`、`self._last_sample.clear`、`self._finish_task`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：检查或判断 `should_sample` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `source_key`（str）：`source_key` 对应的业务输入值
    #   - `timestamp`（float | None）：事件或帧对应的时间戳；默认值为 `None`
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._clock`、`float`、`self._last_sample.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def should_sample(self, source_key: str, timestamp: float | None = None) -> bool:
        if not self.enabled:
            return False
        now = self._clock() if timestamp is None else float(timestamp)
        with self._lock:
            last = self._last_sample.get(source_key)
            return last is None or now - last >= self._sample_interval

    # 功能：实现 `record_frame` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `source_key`（str）：`source_key` 对应的业务输入值
    #   - `frame`（np.ndarray | None）：待处理的视频图像帧
    #   - `timestamp`（float | None）：事件或帧对应的时间戳；默认值为 `None`
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/evidence_recorder.py` 的 `AlarmEvidenceRecorder::start_alarm`
    #         调用本符号；`AiVision/platform/violation/evidence_recorder.py` 的 `AlarmEvidenceRecorder::_sample_loop`
    #         调用本符号；`AiVision/tests/test_alarm_evidence_recorder.py` 的 `test_recorder_keeps_pre_and_post_alarm_frames`
    #         调用本符号；`AiVision/tests/test_alarm_evidence_recorder.py` 的
    #         `test_recorder_throttles_samples_and_discards_expired_prebuffer` 调用本符号
    #   - 内部调用：`isinstance`、`self._clock`、`float`、`self._last_sample.get`、`self._encode_frame`、`logger.warning`、`buffer.append`、`buffer.popleft`、`task.frames.append`、`finished.append`
    #          等共 13 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
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

    # 功能：启动或执行 `start_alarm` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `source_key`（str）：`source_key` 对应的业务输入值
    #   - `trigger_frame`（np.ndarray | None）：`trigger_frame` 对应的业务输入值；默认值为 `None`
    #   - `timestamp`（float | None）：事件或帧对应的时间戳；默认值为 `None`
    # 返回：str | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.output_dir.mkdir`、`logger.warning`、`self._clock`、`float`、`isinstance`、`self.record_frame`、`int`、`uuid.uuid4`、`str`、`self._buffers.get`
    #          等共 14 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
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

    # 功能：实现 `_sample_loop` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.wait`、`min`、`list`、`provider().items`、`provider`、`logger.warning`、`self._clock`、`self.record_frame`、`str`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
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

    # 功能：实现 `_finish_task` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `task`（_ClipTask）：`task` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/evidence_recorder.py` 的 `AlarmEvidenceRecorder::stop` 调用本符号
    #   - 内部调用：`ValueError`、`self._decode_frame`、`cv2.VideoWriter`、`cv2.VideoWriter_fourcc`、`writer.isOpened`、`OSError`、`cv2.resize`、`writer.write`、`writer.release`、`ensure_browser_compatible_mp4`
    #          等共 12 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
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
            ensure_browser_compatible_mp4(task.video_path)
            status = "ready"
        except (OSError, TypeError, ValueError, cv2.error, VideoEncodingError) as exc:
            logger.warning(f"[AlarmEvidence] 视频生成失败 path={task.video_path}: {exc}")
        callback = self._status_callback
        if callback is not None:
            try:
                callback(task.video_path, status)
            except Exception as exc:
                logger.warning(f"[AlarmEvidence] 视频状态回写失败 path={task.video_path}: {exc}")

    # 功能：实现 `_encode_frame` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    # 返回：bytes；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/evidence_recorder.py` 的 `AlarmEvidenceRecorder::record_frame` 调用本符号
    #   - 内部调用：`cv2.resize`、`max`、`int`、`cv2.imencode`、`ValueError`、`encoded.tobytes`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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

    # 功能：实现 `_decode_frame` 对应的`evidence_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `encoded`（bytes）：`encoded` 对应的业务输入值
    # 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/evidence_recorder.py` 的 `AlarmEvidenceRecorder::_finish_task` 调用本符号
    #   - 内部调用：`cv2.imdecode`、`np.frombuffer`、`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @staticmethod
    def _decode_frame(encoded: bytes) -> np.ndarray:
        frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None or not frame.size:
            raise ValueError("报警视频缓冲帧 JPEG 解码失败")
        return frame


alarm_evidence_recorder = AlarmEvidenceRecorder()
