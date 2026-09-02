# 文件说明：实现视频帧相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
platform/camera/frame_reader.py
统一帧读取器 — 每个摄像头一个线程,从双缓冲共享内存读最新帧到 latest_frames 字典。

旧 CapManager 把这个逻辑混在一起,现在抽出来独立模块。
所有 Consumer 和 API 层都从 latest_frames[shm_name] 读取,避免多次拷贝。
"""
from __future__ import annotations
import threading
import time
from multiprocessing import shared_memory

import numpy as np

from core.logger import logger


# 功能：统一帧读取器集合 — 一个摄像头一个线程；输入与输出详见下方说明
# 参数：无。
# 返回：FrameReaderRegistry；返回新建的 `FrameReaderRegistry` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FrameReaderRegistry:
    """统一帧读取器集合 — 一个摄像头一个线程"""

    # 功能：初始化或配置 `__init__` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        # shm_name → ((shm_0, frame_0), (shm_1, frame_1), active_index, frame_seq)
        self._shm_views: dict[str, tuple] = {}
        self._threads: dict[str, threading.Thread] = {}
        self.latest_frames: dict[str, np.ndarray] = {}
        self.latest_frame_times: dict[str, float] = {}
        self.latest_frame_seq: dict[str, int] = {}
        self._running = False

    # 功能：注册一个摄像头的共享内存视图,启动其读取线程；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    #   - `shape`（tuple）：`shape` 对应的业务输入值
    #   - `active_index`（未显式标注）：`active_index` 对应的业务输入值
    #   - `frame_seq`（未显式标注）：`frame_seq` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/runtime_manager.py` 的 `CameraRuntimeManager::_start_one` 调用本符号
    #   - 内部调用：`shared_memory.SharedMemory`、`np.ndarray`、`logger.error`、`self._start_thread`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def register(self, shm_name: str, shape: tuple, active_index, frame_seq):
        """注册一个摄像头的共享内存视图,启动其读取线程"""
        try:
            shm0 = shared_memory.SharedMemory(name=shm_name + "_0")
            frame0 = np.ndarray(shape, dtype=np.uint8, buffer=shm0.buf)
            shm1 = shared_memory.SharedMemory(name=shm_name + "_1")
            frame1 = np.ndarray(shape, dtype=np.uint8, buffer=shm1.buf)
        except Exception as e:
            logger.error(f"[FrameReader] 共享内存附加失败 {shm_name}: {e}")
            return

        self._shm_views[shm_name] = ((shm0, frame0), (shm1, frame1), active_index, frame_seq)
        if self._running:
            self._start_thread(shm_name)

    # 功能：注销摄像头 — 停止读取线程,释放共享内存视图；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/runtime_manager.py` 的 `CameraRuntimeManager::stop_camera` 调用本符号
    #   - 内部调用：`self._threads.pop`、`thread.join`、`self._shm_views.pop`、`shm0.close`、`shm1.close`、`self.latest_frames.pop`、`self.latest_frame_times.pop`、`self.latest_frame_seq.pop`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def unregister(self, shm_name: str):
        """注销摄像头 — 停止读取线程,释放共享内存视图"""
        thread = self._threads.pop(shm_name, None)
        if thread is not None:
            thread.join(timeout=2)

        view = self._shm_views.pop(shm_name, None)
        if view is not None:
            (shm0, _), (shm1, _), _ = view
            try:
                shm0.close()
                shm1.close()
            except Exception:
                pass

        self.latest_frames.pop(shm_name, None)
        self.latest_frame_times.pop(shm_name, None)
        self.latest_frame_seq.pop(shm_name, None)

    # 功能：启动或执行 `start_all` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`list`、`self._shm_views.keys`、`self._start_thread`、`logger.info`、`len`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def start_all(self):
        self._running = True
        for shm_name in list(self._shm_views.keys()):
            self._start_thread(shm_name)
        logger.info(f"[FrameReader] 已启动 {len(self._threads)} 个读取线程")

    # 功能：停止并释放 `stop_all` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._threads.values`、`thread.join`、`list`、`self._shm_views.keys`、`shm0.close`、`shm1.close`、`self._threads.clear`、`self._shm_views.clear`、`self.latest_frames.clear`、`self.latest_frame_times.clear`
    #          等共 11 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def stop_all(self):
        self._running = False
        for thread in self._threads.values():
            thread.join(timeout=2)
        for shm_name in list(self._shm_views.keys()):
            view = self._shm_views[shm_name]
            (shm0, _), (shm1, _), _ = view
            try:
                shm0.close()
                shm1.close()
            except Exception:
                pass
        self._threads.clear()
        self._shm_views.clear()
        self.latest_frames.clear()
        self.latest_frame_times.clear()
        self.latest_frame_seq.clear()

    # 功能：检查或判断 `is_active` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_active(self, shm_name: str) -> bool:
        return shm_name in self._shm_views

    # 功能：启动或执行 `_start_thread` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/frame_reader.py` 的 `FrameReaderRegistry::register`
    #         调用本符号；`AiVision/platform/camera/frame_reader.py` 的 `FrameReaderRegistry::start_all` 调用本符号
    #   - 内部调用：`threading.Thread`、`t.start`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def _start_thread(self, shm_name: str):
        if shm_name in self._threads:
            return
        t = threading.Thread(
            target=self._read_loop, args=(shm_name,), daemon=True,
            name=f"frame-reader-{shm_name}",
        )
        t.start()
        self._threads[shm_name] = t

    # 功能：读取或查询 `_read_loop` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._shm_views.get`、`int`、`self.latest_frame_seq.get`、`time.sleep`、`(frame0 if idx == 0 else
    #          frame1).copy`、`time.time`、`logger.warning`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _read_loop(self, shm_name: str):
        while self._running:
            view = self._shm_views.get(shm_name)
            if view is None:
                break
            (_, frame0), (_, frame1), active_index, frame_seq = view
            try:
                seq = int(frame_seq.value)
                last_seq = self.latest_frame_seq.get(shm_name, -1)
                if seq == last_seq:
                    time.sleep(0.1)
                    continue
                idx = int(active_index.value)
                self.latest_frames[shm_name] = (frame0 if idx == 0 else frame1).copy()
                self.latest_frame_seq[shm_name] = seq
                self.latest_frame_times[shm_name] = time.time()
            except Exception as e:
                logger.warning(f"[FrameReader:{shm_name}] 读帧异常: {e}")
            time.sleep(0.1)


frame_reader_registry = FrameReaderRegistry()
