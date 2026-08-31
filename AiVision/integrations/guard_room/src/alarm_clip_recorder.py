# 文件说明：实现告警相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：单次报警录制任务的完整状态；输入与输出详见下方说明
# 参数：
#   - `event`（AlarmEvent）：待处理的事件对象
#   - `alarm_user`（str）：`alarm_user` 对应的业务输入值
#   - `camera_name`（str）：`camera_name` 对应的业务输入值
#   - `snapshot_frame`（np.ndarray）：`snapshot_frame` 对应的业务输入值
#   - `start_ts`（float）：`start_ts` 对应的业务输入值
#   - `end_ts`（float）：`end_ts` 对应的业务输入值
#   - `video_path`（str）：`video_path` 对应的业务输入值
#   - `writer`（Optional[cv2.VideoWriter]）：`writer` 对应的业务输入值
#   - `frames_written`（int）：`frames_written` 对应的业务输入值
# 返回：AlarmClipTask；返回新建的 `AlarmClipTask` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/alarm_clip_recorder.py` 的 `AlarmClipRecorder::start_clip` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：线程安全的报警视频片段录制器；输入与输出详见下方说明
# 参数：
#   - `output_dir`（str | Path）：`output_dir` 对应的业务输入值
#   - `fps`（int）：`fps` 对应的业务输入值；默认值为 `10`
#   - `clip_seconds`（float）：`clip_seconds` 对应的时间间隔或时长；默认值为 `5.0`
# 返回：AlarmClipRecorder；返回新建的 `AlarmClipRecorder` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::__init__` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：初始化录制器；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `output_dir`（str | Path）：`output_dir` 对应的业务输入值
    #   - `fps`（int）：`fps` 对应的业务输入值；默认值为 `10`
    #   - `clip_seconds`（float）：`clip_seconds` 对应的时间间隔或时长；默认值为 `5.0`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`ensure_dir`、`threading.Lock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：注册一个新的报警录制任务；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event`（AlarmEvent）：待处理的事件对象
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    #   - `timestamp_s`（float）：以秒表示的流时间戳
    #   - `camera_name`（str）：`camera_name` 对应的业务输入值
    #   - `alarm_user`（str）：`alarm_user` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：`datetime.now().strftime`、`datetime.now`、`str`、`Path`、`AlarmClipTask`、`frame.copy`、`self._tasks.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：将当前帧写入所有活跃录制任务，并返回本轮完成的任务；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    #   - `timestamp_s`（float）：以秒表示的流时间戳
    # 返回：list[AlarmClipTask]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`cv2.resize`、`int`、`cv2.VideoWriter_fourcc`、`cv2.VideoWriter`、`task.writer.write`、`task.writer.release`、`finished.append`、`alive.append`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件。
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

    # 功能：释放所有未完成任务占用的资源；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`task.writer.release`、`self._tasks.clear`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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