"""车辆出现周期的视频录制器。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

from .utils import ensure_dir


@dataclass
class VehicleEpisodeTask:
    """单路摄像头的一次车辆出现周期录制任务。"""

    camera_id: str
    video_path: str
    writer: Optional[cv2.VideoWriter] = None
    frames_written: int = 0


class VehicleEpisodeRecorder:
    """从车辆出现开始录制，合格时删除，不合格时返回视频路径。"""

    def __init__(self, output_dir: str | Path, fps: int = 10):
        self.output_dir = ensure_dir(output_dir)
        self.fps = fps
        self._tasks: Dict[str, VehicleEpisodeTask] = {}

    def update(self, camera_id: str, frame: np.ndarray) -> None:
        """确保 camera_id 有活跃任务，并写入当前帧。"""
        task = self._tasks.get(camera_id)
        if task is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_path = str(Path(self.output_dir) / f"vehicle_unattended_{camera_id}_{ts}.mp4")
            task = VehicleEpisodeTask(camera_id=camera_id, video_path=video_path)
            self._tasks[camera_id] = task

        frame_to_write = self._resize(frame)
        if task.writer is None:
            h, w = frame_to_write.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            task.writer = cv2.VideoWriter(task.video_path, fourcc, self.fps, (w, h))

        if task.writer is not None:
            task.writer.write(frame_to_write)
            task.frames_written += 1

    def cancel(self, camera_id: str) -> None:
        """取消该摄像头周期录制，并删除临时视频。"""
        task = self._tasks.pop(camera_id, None)
        if task is None:
            return
        self._close_task(task)
        path = Path(task.video_path)
        if path.exists():
            path.unlink()

    def finish(self, camera_id: str) -> str | None:
        """完成该摄像头周期录制，返回可推送的视频路径。"""
        task = self._tasks.pop(camera_id, None)
        if task is None:
            return None
        self._close_task(task)
        return task.video_path if task.frames_written > 0 else None

    def close(self) -> None:
        """关闭并清理所有未完成周期。"""
        for camera_id in list(self._tasks.keys()):
            self.cancel(camera_id)

    @staticmethod
    def _close_task(task: VehicleEpisodeTask) -> None:
        if task.writer is not None:
            task.writer.release()
            task.writer = None

    @staticmethod
    def _resize(frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        target_w = 960
        if w <= target_w:
            return frame
        scale = target_w / w
        return cv2.resize(frame, (target_w, int(h * scale)))
