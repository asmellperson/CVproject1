# alarm_clip_recorder.py
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
    def __init__(
        self,
        output_dir: str | Path,
        fps: int = 10,
        clip_seconds: float = 5.0,
    ):
        self.output_dir = ensure_dir(output_dir)
        self.fps = fps
        self.clip_seconds = clip_seconds
        self._lock = threading.Lock()
        self._tasks: List[AlarmClipTask] = []

    def start_clip(
        self,
        *,
        event: AlarmEvent,
        frame: np.ndarray,
        timestamp_s: float,
        camera_name: str,
        alarm_user: str,
    ) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{event.event_type}_{event.frame_index}_{ts}.mp4"
        video_path = str(Path(self.output_dir) / filename)

        task = AlarmClipTask(
            event=event,
            alarm_user=alarm_user,
            camera_name=camera_name,
            snapshot_frame=frame.copy(),
            start_ts=timestamp_s,
            end_ts=timestamp_s + self.clip_seconds,
            video_path=video_path,
        )

        with self._lock:
            self._tasks.append(task)

    def update(self, frame: np.ndarray, timestamp_s: float) -> list[AlarmClipTask]:
        finished: list[AlarmClipTask] = []

        with self._lock:
            alive: list[AlarmClipTask] = []

            # 先缩放帧,只缩一次
            h, w = frame.shape[:2]
            target_w = 960   # 目标宽度,可配
            if w > target_w:
                scale = target_w / w
                small_frame = cv2.resize(frame, (target_w, int(h * scale)))
            else:
                small_frame = frame

            for task in self._tasks:
                if task.writer is None:
                    sh, sw = small_frame.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    task.writer = cv2.VideoWriter(task.video_path, fourcc, self.fps, (sw, sh))

                if task.writer is not None:
                    task.writer.write(small_frame)
                    task.frames_written += 1

                if timestamp_s >= task.end_ts:
                    if task.writer is not None:
                        task.writer.release()
                        task.writer = None
                    finished.append(task)
                else:
                    alive.append(task)

            self._tasks = alive

        return finished

    def close(self) -> None:
        with self._lock:
            for task in self._tasks:
                if task.writer is not None:
                    task.writer.release()
                    task.writer = None
            self._tasks.clear()