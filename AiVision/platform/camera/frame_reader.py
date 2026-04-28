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


class FrameReaderRegistry:
    """统一帧读取器集合 — 一个摄像头一个线程"""

    def __init__(self):
        # shm_name → ((shm_0, frame_0), (shm_1, frame_1), active_index)
        self._shm_views: dict[str, tuple] = {}
        self._threads: dict[str, threading.Thread] = {}
        self.latest_frames: dict[str, np.ndarray] = {}
        self.latest_frame_times: dict[str, float] = {}
        self._running = False

    def register(self, shm_name: str, shape: tuple, active_index):
        """注册一个摄像头的共享内存视图,启动其读取线程"""
        try:
            shm0 = shared_memory.SharedMemory(name=shm_name + "_0")
            frame0 = np.ndarray(shape, dtype=np.uint8, buffer=shm0.buf)
            shm1 = shared_memory.SharedMemory(name=shm_name + "_1")
            frame1 = np.ndarray(shape, dtype=np.uint8, buffer=shm1.buf)
        except Exception as e:
            logger.error(f"[FrameReader] 共享内存附加失败 {shm_name}: {e}")
            return

        self._shm_views[shm_name] = ((shm0, frame0), (shm1, frame1), active_index)
        if self._running:
            self._start_thread(shm_name)

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

    def start_all(self):
        self._running = True
        for shm_name in list(self._shm_views.keys()):
            self._start_thread(shm_name)
        logger.info(f"[FrameReader] 已启动 {len(self._threads)} 个读取线程")

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

    def is_active(self, shm_name: str) -> bool:
        return shm_name in self._shm_views

    def _start_thread(self, shm_name: str):
        if shm_name in self._threads:
            return
        t = threading.Thread(
            target=self._read_loop, args=(shm_name,), daemon=True,
            name=f"frame-reader-{shm_name}",
        )
        t.start()
        self._threads[shm_name] = t

    def _read_loop(self, shm_name: str):
        while self._running:
            view = self._shm_views.get(shm_name)
            if view is None:
                break
            (_, frame0), (_, frame1), active_index = view
            try:
                idx = active_index.value
                self.latest_frames[shm_name] = (frame0 if idx == 0 else frame1).copy()
                self.latest_frame_times[shm_name] = time.time()
            except Exception as e:
                logger.warning(f"[FrameReader:{shm_name}] 读帧异常: {e}")
            time.sleep(0.1)


frame_reader_registry = FrameReaderRegistry()
