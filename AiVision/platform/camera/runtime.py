# 文件说明：实现运行时相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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
import subprocess as sp
import time
from collections import deque
from multiprocessing import Event, Process, shared_memory

import cv2
import numpy as np

from AiVision.core.logger import logger

from .probe import CameraProbeError, probe_video_shape


# 功能：单个摄像头的采集运行时；输入与输出详见下方说明
# 参数：
#   - `config`（dict）：运行配置对象
#   - `active_index`（未显式标注）：`active_index` 对应的业务输入值
#   - `frame_seq`（未显式标注）：`frame_seq` 对应的业务输入值
#   - `event_queue`（未显式标注）：`event_queue` 对应的业务输入值；默认值为 `None`
# 返回：CameraRuntime；返回新建的 `CameraRuntime` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraRuntime:
    """单个摄像头的采集运行时"""

    # 功能：初始化或配置 `__init__` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `config`（dict）：运行配置对象
    #   - `active_index`（未显式标注）：`active_index` 对应的业务输入值
    #   - `frame_seq`（未显式标注）：`frame_seq` 对应的业务输入值
    #   - `event_queue`（未显式标注）：`event_queue` 对应的业务输入值；默认值为 `None`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`config.get`、`float`、`max`、`self._probe_size`、`Event`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, config: dict, active_index, frame_seq, event_queue=None):
        self.cfg = config
        self.name: str = config["name"]
        self.shm_name: str = config["shm_name"]
        self.url: str = config["url"]
        self.active_index = active_index
        self.frame_seq = frame_seq
        self.event_queue = event_queue

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
        self.restart_cooldown = float(config.get("restart_cooldown", 1.0))
        self.restart_window_seconds = max(1.0, float(config.get("restart_window_seconds", 600.0)))

        if not config.get("enable", True):
            self.status = False
            self.msg = f"摄像头 {self.name} 已禁用"
            return

        self._probe_size()

        if self.status:
            self.stop_event = Event()
            self.ready_event = Event()

    # 功能：通过隔离的 ffprobe 子进程获取视频分辨率；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/runtime.py` 的 `CameraRuntime::__init__` 调用本符号
    #   - 内部调用：`probe_video_shape`、`logger.warning`。
    # 副作用/注意事项：会更新当前实例的运行状态；会向日志系统输出运行或异常信息。
    def _probe_size(self):
        """通过隔离的 ffprobe 子进程获取视频分辨率。"""
        try:
            self.shape = probe_video_shape(self.url)
            self.height, self.width, self.channels = self.shape
        except CameraProbeError as exc:
            logger.warning(f"[Camera:{self.name}] 获取分辨率失败: {exc}")
            self.status = False
            self.msg = f"[{self.name}] 获取分辨率异常: {exc}"

    # ---------- 生命周期 ----------

    # 功能：启动或执行 `start` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `active_index`（未显式标注）：`active_index` 对应的业务输入值
    #   - `timeout`（float）：允许操作等待的最长秒数；默认值为 `10.0`
    #   - `max_count`（int）：`max_count` 对应的数量或大小；默认值为 `4`
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.stop_event.clear`、`self.ready_event.clear`、`Process`、`self.proc.start`、`self.ready_event.wait`、`self.stop`、`TimeoutError`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
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

    # 功能：停止并释放 `stop` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/runtime.py` 的 `CameraRuntime::start` 调用本符号
    #   - 内部调用：`self.stop_event.set`、`self.proc.join`、`self.pipe.terminate`、`self.pipe.wait`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：启动或执行 `_start_ffmpeg` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/runtime.py` 的 `CameraRuntime::_restart_ffmpeg` 调用本符号；`AiVision/platform/camera/runtime.py` 的
    #         `CameraRuntime::_capture_loop` 调用本符号
    #   - 内部调用：`sp.Popen`、`max`、`int`、`self.cfg.get`、`logger.info`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息。
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

    # 功能：实现 `_restart_ffmpeg` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/runtime.py` 的 `CameraRuntime::_capture_loop` 调用本符号
    #   - 内部调用：`self.pipe.terminate`、`self.pipe.wait`、`self.pipe.kill`、`self.pipe.stdout.close`、`time.sleep`、`self._start_ffmpeg`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def _restart_ffmpeg(self):
        if self.pipe:
            try:
                self.pipe.terminate()
                self.pipe.wait(timeout=2)
            except sp.TimeoutExpired:
                self.pipe.kill()
                self.pipe.wait(timeout=2)
            except Exception:
                pass
            try:
                if self.pipe.stdout:
                    self.pipe.stdout.close()
            except Exception:
                pass
        time.sleep(self.restart_cooldown)
        self._start_ffmpeg()

    # 功能：发送或分发 `_emit_runtime_event` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event_type`（str）：事件类型标识
    #   - `detail`（str）：`detail` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/runtime.py` 的 `CameraRuntime::_capture_loop` 调用本符号
    #   - 内部调用：`self.event_queue.put_nowait`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _emit_runtime_event(self, event_type: str, detail: str):
        if self.event_queue is None:
            return
        try:
            self.event_queue.put_nowait({
                "shm_name": self.shm_name,
                "camera_name": self.name,
                "event_type": event_type,
                "detail": detail,
            })
        except Exception:
            pass

    # ---------- 采集主循环 ----------

    # 功能：实现 `_capture_loop` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `active_index`（未显式标注）：`active_index` 对应的业务输入值
    #   - `frame_seq`（未显式标注）：`frame_seq` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`setproctitle`、`self._create_or_attach_shm`、`np.ndarray`、`self._start_ffmpeg`、`deque`、`self.stop_event.is_set`、`time.time`、`self.pipe.stdout.read`、`len`、`RuntimeError`
    #          等共 32 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
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
        restart_times = deque()

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
                    now = time.time()
                    while restart_times and now - restart_times[0] > self.restart_window_seconds:
                        restart_times.popleft()
                    restart_times.append(now)
                    if len(restart_times) > self.max_restart:
                        self._emit_runtime_event(
                            "视频流异常",
                            (
                                f"{e}; {self.restart_window_seconds:.0f}s 内达到最大重启次数"
                                f"({self.max_restart}),采集进程退出"
                            ),
                        )
                        logger.error(
                            f"[Camera:{self.name}] {self.restart_window_seconds:.0f}s 内达到最大重启次数"
                            f"({self.max_restart}),退出"
                        )
                        break
                    self._emit_runtime_event(
                        "视频流异常",
                        (
                            f"{e}; 正在重启 ffmpeg "
                            f"({len(restart_times)}/{self.max_restart}, "
                            f"window={self.restart_window_seconds:.0f}s)"
                        ),
                    )
                    logger.warning(
                        f"[Camera:{self.name}] 视频流异常: {e},重启 ffmpeg "
                        f"({len(restart_times)}/{self.max_restart}, "
                        f"window={self.restart_window_seconds:.0f}s)"
                    )
                    prev_gray = None
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

    # 功能：创建共享内存,如果残留则先清理后重建；输入与输出详见下方说明
    # 参数：
    #   - `name`（str）：业务对象名称
    #   - `size`（int）：`size` 对应的数量或大小
    # 返回：shared_memory.SharedMemory；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/runtime.py` 的 `CameraRuntime::_capture_loop` 调用本符号
    #   - 内部调用：`shared_memory.SharedMemory`、`existing.close`、`existing.unlink`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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
