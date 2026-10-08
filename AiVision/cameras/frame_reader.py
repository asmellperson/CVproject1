"""
cameras/frame_reader.py
其他模块如何拿到画面

CameraRuntime负责把最新帧写入共享内存
FrameReaderRegistry负责把共享内存中的最新帧读到Aivision主进程

所有 Consumer 和 API 层都从 latest_frames[shm_name] 读取只读快照,绘图时需先拷贝。
"""
from __future__ import annotations
import threading
import time
from multiprocessing import shared_memory

import numpy as np

from AiVision.core.logger import logger

class FrameReaderRegistry:
    """一个FrameReaderRegistry里面管理很多摄像头 — 每台摄像头开一个读取线程"""
    def __init__(self):
        # shm_name → ((shm_0, frame_0), (shm_1, frame_1), active_index, frame_seq)
        """准备共享内存视图、逐路线程及最新帧缓存；此时不连接共享内存或启动读取。"""
        self._shm_views: dict[str, tuple] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self.latest_frames: dict[str, np.ndarray] = {}     # 最新一张完整Numpy图片
        self.latest_frame_times: dict[str, float] = {}      # 最近一次成功读取新帧的时间
        self.latest_frame_seq: dict[str, int] = {}          # FrameReader上一次已经处理到第几帧
        self._running = False

    def register(self, shm_name: str, shape: tuple, active_index, frame_seq) -> bool:
        """
        注册一个摄像头的共享内存视图,Registry已运行时启动其读取线程；成功返回True，失败返回False
        RuntimeManager._start_one()里的frame_reader_registry.register就是进入这里
        """
        with self._lifecycle_lock:
            self.unregister(shm_name)
            attached = []
            try:
                # 先attach第一块共享内存，将共享内存里的图片从（H,W,3）变成Numpy图像
                shm0 = shared_memory.SharedMemory(name=shm_name + "_0")
                attached.append(shm0)
                frame0 = np.ndarray(shape, dtype=np.uint8, buffer=shm0.buf)
                shm1 = shared_memory.SharedMemory(name=shm_name + "_1")
                attached.append(shm1)
                frame1 = np.ndarray(shape, dtype=np.uint8, buffer=shm1.buf)
            except Exception as e:
                logger.error(f"[FrameReader] 共享内存附加失败 {shm_name}: {e}")
                self._close_shms(shm_name, attached)
                return False
            with self._lock:
                # 保存（shm0，frame0）（shm1，frame1），active_index,frame_seq
                self._shm_views[shm_name] = ((shm0, frame0), (shm1, frame1), active_index, frame_seq)
                # 如果整个Registry已经启动，就立即启动FrameReader线程，反之只是先注册，等后面start_all()一起启动
                # 所以兼容：系统启动时批量camera，运行中动态新增camera
                try:
                    if self._running:
                        self._start_thread(shm_name)
                except Exception:
                    logger.exception(f"[FrameReader] 读帧线程启动失败 {shm_name}")
                    self._shm_views.pop(shm_name, None)
                    self._threads.pop(shm_name, None)
                    self._stop_events.pop(shm_name, None)
                    self._close_shms(shm_name, attached)
                    return False
            return True

    def unregister(self, shm_name: str):
        """注销摄像头 — 停止读取线程,释放共享内存视图
        流程：
            移除视图并通知当前摄像头停止读帧
            删除latest frame
            删除timestamp
            删除frame seq
            等待线程退出并关闭SharedMemory连接，超时由线程退出时关闭
        """
        with self._lifecycle_lock:
            with self._lock:
                view = self._shm_views.pop(shm_name, None)
                stop_event = self._stop_events.pop(shm_name, None)
                if stop_event is not None:
                    stop_event.set()
                thread = self._threads.pop(shm_name, None)
                self.latest_frames.pop(shm_name, None)
                self.latest_frame_times.pop(shm_name, None)
                self.latest_frame_seq.pop(shm_name, None)
            if thread is not None:
                thread.join(timeout=2)
                if thread.is_alive():
                    logger.warning(f"[FrameReader] 读帧线程尚未退出 {shm_name}，由线程退出时释放视图")
            elif view is not None:
                (shm0, _), (shm1, _), _, _ = view
                self._close_shms(shm_name, (shm0, shm1))

    def start_all(self):
        """给所有已经注册的Camera开一个读帧线程"""
        with self._lifecycle_lock, self._lock:
            self._running = True
            for shm_name in list(self._shm_views.keys()):
                self._start_thread(shm_name)
        logger.info(f"[FrameReader] 已启动 {len(self._threads)} 个读取线程")

    def stop_all(self):
        """
        和unregister类似，但是这里把总开关关了
        """
        with self._lifecycle_lock:
            self._running = False
            for shm_name in list(self._shm_views):
                self.unregister(shm_name)

    def is_active(self, shm_name: str) -> bool:
        """检查摄像头共享内存是否已登记；这不是帧新鲜度或采集进程存活的独立证明。"""
        with self._lock:
            return shm_name in self._shm_views

    def _start_thread(self, shm_name: str):
        """开启读帧线程使用的是_read_loop函数，这个函数是开启这一台camera的持续读帧循环"""
        if shm_name in self._threads:
            return
        view = self._shm_views[shm_name]
        stop_event = threading.Event()
        t = threading.Thread(
            target=self._read_loop, args=(shm_name, view, stop_event), daemon=True,
            name=f"frame-reader-{shm_name}",
        )
        self._stop_events[shm_name] = stop_event
        self._threads[shm_name] = t
        try:
            t.start()
        except Exception:
            self._threads.pop(shm_name, None)
            self._stop_events.pop(shm_name, None)
            raise

    def _read_loop(self, shm_name: str, view: tuple, stop_event: threading.Event):
        """
        共享内存SharedMemory只copy一次给到latest_frames变量，很多Consumer读的是latest_frame，避免每个Consumer都自己去SharedMemory拷一次
        """
        # 先拿摄像头的共享内存信息
        (shm0, frame0), (shm1, frame1), active_index, frame_seq = view
        try:
            while self._running and not stop_event.is_set():
                try:
                    # 用frame_seq检查有没有新帧
                    seq = int(frame_seq.value)
                    last_seq = self.latest_frame_seq.get(shm_name, -1)
                    if seq <= 0 or seq == last_seq:
                        stop_event.wait(0.1)
                        continue
                    # 查是哪个buffer最新
                    # 一台摄像头某一瞬间可能实际上有buffer 0，buffer 1，以及latest_frame里的copy三份像素内存
                    idx = int(active_index.value)
                    frame = (frame0 if idx == 0 else frame1).copy()
                    if int(frame_seq.value) != seq or int(active_index.value) != idx:
                        stop_event.wait(0.1)
                        continue
                    frame.setflags(write=False)
                    with self._lock:
                        if self._shm_views.get(shm_name) is not view or stop_event.is_set():
                            break
                        self.latest_frames[shm_name] = frame
                        self.latest_frame_seq[shm_name] = seq
                        self.latest_frame_times[shm_name] = time.time()
                except Exception as e:
                    logger.warning(f"[FrameReader:{shm_name}] 读帧异常: {e}")
                stop_event.wait(0.1)
        finally:
            self._close_shms(shm_name, (shm0, shm1))

    @staticmethod
    def _close_shms(shm_name: str, shms):
        """关闭当前进程持有的共享内存视图，失败逐块记录；不在读取端 unlink 采集端资源。"""
        for shm in shms:
            try:
                shm.close()
            except Exception:
                logger.exception(f"[FrameReader] 共享内存视图关闭失败 {shm_name}")


frame_reader_registry = FrameReaderRegistry()
