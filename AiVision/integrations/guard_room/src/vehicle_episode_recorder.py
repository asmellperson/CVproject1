# 文件说明：实现`vehicle_episode_recorder` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""车辆出现周期的视频录制器。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

from .utils import ensure_dir


# 功能：单路摄像头的一次车辆出现周期录制任务；输入与输出详见下方说明
# 参数：
#   - `camera_id`（str）：摄像头唯一标识
#   - `video_path`（str）：`video_path` 对应的业务输入值
#   - `writer`（Optional[cv2.VideoWriter]）：`writer` 对应的业务输入值
#   - `frames_written`（int）：`frames_written` 对应的业务输入值
# 返回：VehicleEpisodeTask；返回新建的 `VehicleEpisodeTask` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/vehicle_episode_recorder.py` 的 `VehicleEpisodeRecorder::update` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class VehicleEpisodeTask:
    """单路摄像头的一次车辆出现周期录制任务。"""

    camera_id: str
    video_path: str
    writer: Optional[cv2.VideoWriter] = None
    frames_written: int = 0


# 功能：从车辆出现开始录制，合格时删除，不合格时返回视频路径；输入与输出详见下方说明
# 参数：
#   - `output_dir`（str | Path）：`output_dir` 对应的业务输入值
#   - `fps`（int）：`fps` 对应的业务输入值；默认值为 `10`
# 返回：VehicleEpisodeRecorder；返回新建的 `VehicleEpisodeRecorder` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::__init__` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class VehicleEpisodeRecorder:
    """从车辆出现开始录制，合格时删除，不合格时返回视频路径。"""

    # 功能：初始化或配置 `__init__` 对应的`vehicle_episode_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `output_dir`（str | Path）：`output_dir` 对应的业务输入值
    #   - `fps`（int）：`fps` 对应的业务输入值；默认值为 `10`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`ensure_dir`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, output_dir: str | Path, fps: int = 10):
        self.output_dir = ensure_dir(output_dir)
        self.fps = fps
        self._tasks: Dict[str, VehicleEpisodeTask] = {}

    # 功能：确保 camera_id 有活跃任务，并写入当前帧；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（str）：摄像头唯一标识
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._tasks.get`、`datetime.now().strftime`、`datetime.now`、`str`、`Path`、`VehicleEpisodeTask`、`self._resize`、`cv2.VideoWriter_fourcc`、`cv2.VideoWriter`、`task.writer.write`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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

    # 功能：取消该摄像头周期录制，并删除临时视频；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_episode_recorder.py` 的 `VehicleEpisodeRecorder::close`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：`self._tasks.pop`、`self._close_task`、`Path`、`path.exists`、`path.unlink`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def cancel(self, camera_id: str) -> None:
        """取消该摄像头周期录制，并删除临时视频。"""
        task = self._tasks.pop(camera_id, None)
        if task is None:
            return
        self._close_task(task)
        path = Path(task.video_path)
        if path.exists():
            path.unlink()

    # 功能：完成该摄像头周期录制，返回可推送的视频路径；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：str | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：`self._tasks.pop`、`self._close_task`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def finish(self, camera_id: str) -> str | None:
        """完成该摄像头周期录制，返回可推送的视频路径。"""
        task = self._tasks.pop(camera_id, None)
        if task is None:
            return None
        self._close_task(task)
        return task.video_path if task.frames_written > 0 else None

    # 功能：关闭并清理所有未完成周期；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`list`、`self._tasks.keys`、`self.cancel`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def close(self) -> None:
        """关闭并清理所有未完成周期。"""
        for camera_id in list(self._tasks.keys()):
            self.cancel(camera_id)

    # 功能：停止并释放 `_close_task` 对应的`vehicle_episode_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `task`（VehicleEpisodeTask）：`task` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_episode_recorder.py` 的 `VehicleEpisodeRecorder::cancel`
    #         调用本符号；`AiVision/integrations/guard_room/src/vehicle_episode_recorder.py` 的 `VehicleEpisodeRecorder::finish` 调用本符号
    #   - 内部调用：`task.writer.release`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    @staticmethod
    def _close_task(task: VehicleEpisodeTask) -> None:
        if task.writer is not None:
            task.writer.release()
            task.writer = None

    # 功能：实现 `_resize` 对应的`vehicle_episode_recorder` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    # 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_episode_recorder.py` 的 `VehicleEpisodeRecorder::update` 调用本符号
    #   - 内部调用：`cv2.resize`、`int`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _resize(frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        target_w = 960
        if w <= target_w:
            return frame
        scale = target_w / w
        return cv2.resize(frame, (target_w, int(h * scale)))
