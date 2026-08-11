# alarm_clip_recorder.py
"""
报警片段录制模块。

负责在报警事件触发时，将后续若干秒的视频帧写入 MP4 文件，
并在录制完成后返回任务对象供上层处理（上传、通知等）。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from .types import AlarmEvent
from .utils import ensure_dir


@dataclass
class AlarmClipTask:
    """单次报警录制任务的完整状态。

    由 AlarmClipRecorder.start_clip() 创建，在 update() 中逐帧填充，
    时间戳到达 end_ts 后被移出活跃队列并作为"已完成任务"返回。

    Attributes:
        event:          触发本次录制的报警事件（含事件类型、帧索引等）。
        alarm_user:     报警所属用户标识，用于后续归档或通知。
        camera_name:    产生报警的摄像头名称。
        snapshot_frame: 报警触发瞬间的原始帧副本，可用于静态缩略图。
        start_ts:       录制开始的流时间戳（秒）。
        end_ts:         录制结束的流时间戳（秒），= start_ts + clip_seconds。
        video_path:     输出 MP4 文件的完整路径。
        writer:         OpenCV VideoWriter 实例；None 表示尚未初始化或已释放。
        frames_written: 已写入的帧数，可用于诊断录制时长是否符合预期。
    """

    event: AlarmEvent
    alarm_user: str
    camera_name: str
    snapshot_frame: np.ndarray
    start_ts: float
    end_ts: float
    video_path: str
    writer: Optional[cv2.VideoWriter] = None
    frames_written: int = 0


class AlarmClipRecorder:
    """线程安全的报警视频片段录制器。

    典型工作流：
        1. 报警触发时调用 start_clip()，注册一个新录制任务。
        2. 主循环每帧调用 update()，将帧追加到所有活跃任务中。
        3. update() 返回本轮刚完成的任务列表，上层可对其做上传/通知等处理。
        4. 程序退出前调用 close()，释放所有未完成任务的文件句柄。

    同一时刻可并发录制多个任务（例如多路摄像头同时触发报警）。
    内部使用 threading.Lock 保护任务列表，确保跨线程安全。
    """

    def __init__(
        self,
        output_dir: str | Path,
        fps: int = 10,
        clip_seconds: float = 5.0,
    ):
        """初始化录制器。

        Args:
            output_dir:   MP4 文件的输出目录；不存在时自动创建。
            fps:          写入视频的帧率，应与实际推帧频率保持一致以避免播放加速/减速。
            clip_seconds: 每段报警视频的时长（秒）。
        """
        self.output_dir = ensure_dir(output_dir)
        self.fps = fps
        self.clip_seconds = clip_seconds
        self._lock = threading.Lock()           # 保护 _tasks 的互斥锁
        self._tasks: List[AlarmClipTask] = []   # 当前所有活跃录制任务

    def start_clip(
        self,
        *,
        event: AlarmEvent,
        frame: np.ndarray,
        timestamp_s: float,
        camera_name: str,
        alarm_user: str,
    ) -> None:
        """注册一个新的报警录制任务。

        仅创建任务对象并加入队列，VideoWriter 的实际初始化推迟到
        首次 update() 调用时执行（此时才能确定缩放后的帧尺寸）。

        Args:
            event:        触发录制的报警事件。
            frame:        报警瞬间的视频帧，会被深拷贝保存为快照。
            timestamp_s:  当前流时间戳（秒），作为录制窗口的起点。
            camera_name:  摄像头标识，写入文件名及任务元数据。
            alarm_user:   用户标识，用于后续归档或推送。
        """
        # 用当前时刻生成文件名，格式：{事件类型}_{帧索引}_{时间戳}.mp4
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{event.event_type}_{event.frame_index}_{ts}.mp4"
        video_path = str(Path(self.output_dir) / filename)

        task = AlarmClipTask(
            event=event,
            alarm_user=alarm_user,
            camera_name=camera_name,
            snapshot_frame=frame.copy(),    # 深拷贝，防止外部修改污染快照
            start_ts=timestamp_s,
            end_ts=timestamp_s + self.clip_seconds,
            video_path=video_path,
        )

        with self._lock:
            self._tasks.append(task)

    def update(self, frame: np.ndarray, timestamp_s: float) -> list[AlarmClipTask]:
        """将当前帧写入所有活跃录制任务，并返回本轮完成的任务。

        应在主视频循环中每帧调用一次。内部对帧做统一缩放后再分发给各任务，
        避免对同一帧重复执行 resize 操作。

        Args:
            frame:        当前原始视频帧（BGR 格式）。
            timestamp_s:  当前流时间戳（秒），用于判断各任务是否到达结束时刻。

        Returns:
            本轮刚完成录制的 AlarmClipTask 列表（VideoWriter 已释放）。
            若无任务完成则返回空列表。
        """
        finished: list[AlarmClipTask] = []

        with self._lock:
            alive: list[AlarmClipTask] = []

            # 统一缩放：所有任务共享同一份缩放结果，只做一次 resize
            h, w = frame.shape[:2]
            target_w = 960  # 目标宽度（像素），可根据存储/带宽需求调整
            if w > target_w:
                scale = target_w / w
                small_frame = cv2.resize(frame, (target_w, int(h * scale)))
            else:
                small_frame = frame  # 原始宽度未超出阈值，无需缩放

            for task in self._tasks:
                # 懒初始化 VideoWriter：首帧时根据实际缩放尺寸创建写入器
                if task.writer is None:
                    sh, sw = small_frame.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    task.writer = cv2.VideoWriter(task.video_path, fourcc, self.fps, (sw, sh))

                # 写入当前帧并累计计数
                if task.writer is not None:
                    task.writer.write(small_frame)
                    task.frames_written += 1

                # 判断录制窗口是否结束
                if timestamp_s >= task.end_ts:
                    # 录制完成：释放写入器，移入完成列表
                    if task.writer is not None:
                        task.writer.release()
                        task.writer = None
                    finished.append(task)
                else:
                    # 录制未完成：保留在活跃队列
                    alive.append(task)

            self._tasks = alive  # 用存活任务列表替换原队列

        return finished

    def close(self) -> None:
        """释放所有未完成任务占用的资源。

        应在程序退出或录制器不再使用时调用，防止 VideoWriter 句柄泄漏
        导致输出文件损坏或无法被其他进程访问。
        """
        with self._lock:
            for task in self._tasks:
                if task.writer is not None:
                    task.writer.release()
                    task.writer = None
            self._tasks.clear()