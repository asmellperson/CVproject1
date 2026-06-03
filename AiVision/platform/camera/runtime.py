"""
platform/camera/runtime.py
摄像头采集子进程 — 每路摄像头一个进程,ffmpeg 拉流,双缓冲共享内存写入。

代码与旧 function/product.py 几乎一致,只清理了注释和命名,核心机制不动:
    - 双缓冲 shm_name_0 / shm_name_1
    - active_index 标识当前可读 buffer
    - 花屏检测(帧差)
    - 自动重启(冷却 + 最大次数)
"""
from __future__ import annotations
import datetime
import os
import subprocess as sp
import time
from contextlib import contextmanager
from multiprocessing import Process, Event, shared_memory

import cv2
import numpy as np

from core.logger import logger


@contextmanager
def _suppress_native_stderr():
    """Suppress C/C++ library stderr output during short probe calls."""
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_stderr_fd = os.dup(2)
    try:
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(saved_stderr_fd, 2)
        os.close(saved_stderr_fd)
        os.close(devnull_fd)


class CameraRuntime:
    """单个摄像头的采集运行时"""

    def __init__(self, config: dict, active_index, frame_seq):
        self.cfg = config
        self.name: str = config["name"]
        self.shm_name: str = config["shm_name"]
        self.url: str = config["url"]
        self.active_index = active_index
        self.frame_seq = frame_seq

        self.status = True
        self.running = False
        self.msg: str | tuple = ""

        self.height = self.width = self.channels = 0
        self.shape: tuple[int, int, int] = (0, 0, 0)
        self.pipe = None
        self.proc: Process | None = None

        self.frame_interval = 1.0 / config.get("fps", 5)
        self.diff_threshold = config.get("diff_threshold", 70)
        self.max_restart = config.get("max_restart", 10)
        self.restart_cooldown = 1.0

        if not config.get("enable", True):
            self.status = False
            self.msg = f"摄像头 {self.name} 已禁用"
            return

        self._probe_size()

        if self.status:
            self.stop_event = Event()
            self.ready_event = Event()

    def _probe_size(self):
        """通过 OpenCV 临时连接拿分辨率"""
        cap = None
        try:
            with _suppress_native_stderr():
                cap = cv2.VideoCapture(self.url)
                opened = cap.isOpened()
            if not opened:
                raise RuntimeError("无法打开 RTSP 流")
            with _suppress_native_stderr():
                ret, frame = cap.read()
            if not ret:
                raise RuntimeError("无法读取第一帧")
            self.height, self.width, self.channels = frame.shape
            self.shape = frame.shape
        except Exception as e:
            logger.warning(f"[Camera:{self.name}] 获取分辨率失败: {e}")
            self.status = False
            self.msg = f"[{self.name}] 获取分辨率异常: {e}"
        finally:
            if cap is not None:
                cap.release()

    # ---------- 生命周期 ----------

    def start(self, active_index, timeout: float = 10.0, max_count: int = 4):
        if self.running:
            return
        self.stop_event.clear()
        self.ready_event.clear()

        self.proc = Process(
            target=self._capture_loop,
            kwargs={"active_index": active_index, "frame_seq": self.frame_seq},
            name=f"camera-capture-{self.shm_name}",
            daemon=True,
        )
        self.proc.start()
        self.running = True

        attempts = 0
        while not self.ready_event.wait(timeout=timeout):
            attempts += 1
            if attempts >= max_count:
                self.running = False
                self.stop()
                raise TimeoutError(f"[{self.name}] 摄像头初始化超时")

    def stop(self):
        if not self.running:
            return
        self.stop_event.set()
        self.proc.join(timeout=5)
        self.running = False
        if self.pipe:
            try:
                self.pipe.terminate()
                self.pipe.wait(timeout=2)
            except Exception:
                pass

    # ---------- ffmpeg ----------

    def _start_ffmpeg(self):
        self.pipe = sp.Popen(
            [
                "ffmpeg", "-rtsp_transport", "tcp", "-flags", "low_delay",
                "-analyzeduration", "500000", "-probesize", "500000",
                "-i", self.url,
                "-vf", f"fps={max(1, int(self.cfg.get('fps', 5)))},scale={self.width}:{self.height}",
                "-pix_fmt", "bgr24",
                "-vsync", "drop", "-async", "0",
                "-f", "rawvideo", "-",
            ],
            stdout=sp.PIPE,
            stderr=sp.DEVNULL,
            bufsize=10**8,
        )
        logger.info(f"[Camera:{self.name}] ffmpeg 进程启动")

    def _restart_ffmpeg(self):
        if self.pipe:
            self.pipe.terminate()
        time.sleep(self.restart_cooldown)
        self._start_ffmpeg()

    # ---------- 采集主循环 ----------

    def _capture_loop(self, active_index, frame_seq):
        try:
            from setproctitle import setproctitle
            setproctitle(f"Camera[{self.shm_name}]")
        except ImportError:
            pass

        frame_size = self.width * self.height * self.channels
        shm_names = [self.shm_name + "_0", self.shm_name + "_1"]
        shms = [self._create_or_attach_shm(name, frame_size) for name in shm_names]
        frame_shape = (self.height, self.width, self.channels)
        buffers = [np.ndarray(frame_shape, dtype=np.uint8, buffer=s.buf) for s in shms]

        self._start_ffmpeg()
        idx = 0
        prev_gray = None
        restart_count = 0

        try:
            while not self.stop_event.is_set():
                start = time.time()
                try:
                    raw = self.pipe.stdout.read(frame_size)
                    if len(raw) != frame_size:
                        raise RuntimeError("帧读取异常(stream closed)")

                    frame = np.frombuffer(raw, dtype=np.uint8).reshape(frame_shape)

                    # 花屏检测
                    small = frame[::4, ::4]
                    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                    gray = cv2.GaussianBlur(gray, (5, 5), 0)
                    if prev_gray is not None:
                        diff = cv2.absdiff(gray, prev_gray)
                        _, bin_diff = cv2.threshold(diff, 10, 255, cv2.THRESH_BINARY)
                        ratio = bin_diff.mean() / 255.0
                        if ratio > self.diff_threshold:
                            print(f"[{datetime.datetime.now()}][{self.name}] 花屏 (ratio={ratio:.2f}),跳过")
                            continue
                    prev_gray = gray

                    buffers[idx][:] = frame
                    active_index.value = idx
                    frame_seq.value += 1
                    self.ready_event.set()
                    idx = 1 - idx

                    sleep_time = self.frame_interval - (time.time() - start)
                    if sleep_time > 0:
                        time.sleep(sleep_time)

                except Exception as e:
                    logger.warning(f"[Camera:{self.name}] 视频流异常: {e},重启 ffmpeg")
                    restart_count += 1
                    if restart_count > self.max_restart:
                        logger.error(f"[Camera:{self.name}] 达到最大重启次数,退出")
                        break
                    self._restart_ffmpeg()
        finally:
            if self.pipe:
                try:
                    self.pipe.terminate()
                    self.pipe.wait(timeout=2)
                except Exception:
                    self.pipe.kill()
            for shm in shms:
                try:
                    shm.close()
                    shm.unlink()
                except Exception as e:
                    logger.warning(f"[Camera:{self.name}] 释放共享内存失败: {e}")

    @staticmethod
    def _create_or_attach_shm(name: str, size: int) -> shared_memory.SharedMemory:
        """创建共享内存,如果残留则先清理后重建"""
        try:
            return shared_memory.SharedMemory(create=True, size=size, name=name)
        except FileExistsError:
            try:
                existing = shared_memory.SharedMemory(name=name)
                existing.close()
                existing.unlink()
            except FileNotFoundError:
                pass
            return shared_memory.SharedMemory(create=True, size=size, name=name)
