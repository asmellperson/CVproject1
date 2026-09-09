"""
platform/camera/runtime.py
一台摄像头怎么真正的拉流
职责：
    __init__:ffprobe获取H/W
    start(): 创建camera采集子进程
    capture_loop():
        创建shm_0/shm_1
        启动ffmpeg
        while
            _read_frame() 分段读取管道
            raw bytes
            Numpy BGR frame
            花屏检测
            写非活动Buffer
            activate_index切换
            frame_seq+1
        断流:
            restart ffmpeg
            超过max_restart
            Camera采集几次呢退出
一台摄像头一个采集子进程
子进程里面还有一个ffmpeg进程
最新帧通过双共享内存提供给其他模块
ffmpeg断流可以自动重启
"""
from __future__ import annotations

import os
import select
import signal
import subprocess as sp
import time
from collections import deque
from multiprocessing import Event, Process, shared_memory
from queue import Full

import cv2
import numpy as np

from AiVision.core.logger import logger

from .probe import CameraProbeError, probe_video_shape

_DEFAULT_DIFF_THRESHOLD_RATIO = 0.7
_CAPTURE_JOIN_SECONDS = 5.0
_CAPTURE_TERMINATE_SECONDS = 5.0
_CAPTURE_KILL_SECONDS = 2.0
_FFMPEG_STOP_SECONDS = 2.0
_READ_POLL_SECONDS = 0.1


class CameraStreamError(OSError):
    """ffmpeg 输出中断或读取失败，可通过重建 ffmpeg 恢复。"""


def _exit_capture_on_signal(_signum, _frame):
    raise SystemExit(0)

class CameraRuntime:
    """单个摄像头的采集运行时"""

    def __init__(self, config: dict, active_index, frame_seq, event_queue=None):
        """
        生命周期：
            主进程
            启动camera
            等ready_event
            第一帧真正进共享内存
            ready_event.set()
            说明camera启动成功
        """
        self.cfg = config
        self.name: str = config["name"]
        self.shm_name: str = config["shm_name"]
        self.url: str = config["url"]
        # 当前两块共享内存中，哪一块是最新完整帧（因为有两个共享内存）
        self.active_index = active_index
        # 帧序号
        self.frame_seq = frame_seq
        # cameraRuntime向上层报告运行异常的队列
        self.event_queue = event_queue
        # 这台camera runtime是否具备运行条件
        self.status = True
        # 当前采集进程是不是真的已经启动
        self.running = False
        self.msg: str | tuple = ""

        self.height = self.width = self.channels = 0
        self.shape: tuple[int, int, int] = (0, 0, 0)
        # 通过subprocess.Popen()创建的ffmpeg进程
        self.pipe = None
        # proc是由python multiprocessing创建的Camera采集进程
        self.proc: Process | None = None

        self.frame_interval = 1.0 / config.get("fps", 5)
        # 花屏检测阈值
        self.diff_threshold = float(config.get("diff_threshold", _DEFAULT_DIFF_THRESHOLD_RATIO))
        if not 0.0 <= self.diff_threshold <= 1.0:
            raise ValueError("Camera diff_threshold must be a ratio between 0 and 1")
        # 一个时间窗口内最多允许ffmpeg重启几次
        self.max_restart = config.get("max_restart", 10)
        # 重启前等多久
        self.restart_cooldown = float(config.get("restart_cooldown", 1.0))
        # 统计重启次数的时间查时间窗口
        self.restart_window_seconds = max(1.0, float(config.get("restart_window_seconds", 600.0)))
        # Camera被禁用
        if not config.get("enable", True):
            self.status = False
            self.msg = f"摄像头 {self.name} 已禁用"
            return
        # 返回的是（H，W，3）
        self._probe_size()

        if self.status:
            # 子进程停止通知事件
            self.stop_event = Event()
            # camera子进程已经成功拿到并写入至少一帧画面
            self.ready_event = Event()
            self._process_group_ready = Event()

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
    def start(self, active_index, timeout: float = 10.0, max_count: int = 4):
        if self.running:
            return
        # 清理之前的停止/就绪标签
        self.stop_event.clear()
        self.ready_event.clear()
        self._process_group_ready.clear()
        # 真正创建Camera子进程
        self.proc = Process(
            # _capture_entry设置进程组和退出信号，再进入_capture_loop采集主循环
            # 函数内部会进行：创建共享内存 -> 启动ffmpeg - > 不断red一帧 -> 检测花屏 -> 写共享内存 -> 更新active_index -> 继续下一帧
            target=self._capture_entry,
            kwargs={"active_index": active_index, "frame_seq": self.frame_seq},
            name=f"camera-capture-{self.shm_name}",
            daemon=True,
        )
        # Python Camera子进程启动
        self.proc.start()
        self.running = True

        attempts = 0
        # 默认10秒等一次，最多4次
        while not self.ready_event.wait(timeout=timeout):
            attempts += 1
            if attempts >= max_count or not self.proc.is_alive():
                # 初始化超时或采集子进程提前退出时，先停止并回收采集进程
                self.stop()
                raise TimeoutError(f"[{self.name}] 摄像头初始化超时")

    def stop(self):
        proc = self.proc
        if proc is None or proc.pid is None:
            self.running = False
            return
        # 通知子进程while循环该退出了
        self.stop_event.set()
        # 先等待子进程5秒结束，未退出再依次terminate/kill
        proc.join(timeout=_CAPTURE_JOIN_SECONDS)
        if proc.is_alive():
            logger.warning(f"[Camera:{self.name}] 采集进程未响应停止，发送 terminate")
            proc.terminate()
            proc.join(timeout=_CAPTURE_TERMINATE_SECONDS)
        if proc.is_alive():
            logger.error(f"[Camera:{self.name}] 采集进程 terminate 超时，发送 kill")
            self._kill_capture_group(proc.pid)
            proc.kill()
            proc.join(timeout=_CAPTURE_KILL_SECONDS)
        if proc.is_alive():
            raise RuntimeError(f"[{self.name}] 采集进程 kill 后仍未退出 pid={proc.pid}")
        self._kill_capture_group(proc.pid)
        self._unlink_capture_shms()
        self.running = False
        self.proc = None
        # self.pipe由采集子进程持有并清理
        # 父进程通过独立进程组和共享内存清理兜底

    def _kill_capture_group(self, pid: int):
        if self._process_group_ready.is_set():
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                return

    def _unlink_capture_shms(self):
        """采集进程已确认退出后，兜底回收强制退出可能遗留的两块共享内存。"""
        for suffix in ("_0", "_1"):
            try:
                shm = shared_memory.SharedMemory(name=self.shm_name + suffix)
            except FileNotFoundError:
                continue
            try:
                shm.unlink()
            except FileNotFoundError:
                continue
            finally:
                shm.close()

    def _capture_entry(self, active_index, frame_seq):
        """采集子进程拥有 ffmpeg；退出时由自身 finally 回收。"""
        if hasattr(os, "setsid"):
            os.setsid()
            self._process_group_ready.set()
        signal.signal(signal.SIGTERM, _exit_capture_on_signal)
        self._capture_loop(active_index, frame_seq)

    # ---------- ffmpeg ----------
    def _start_ffmpeg(self):
        """sp.Popen([...]):真正进入拉流"""
        # RTSP使用TCP、输入self.url、限制FPS、缩放width* height、转BGR24、输出rawvideo、stdout
        # -analyzeduration、-probesize：控制ffmpeg开始播放前分析输入流的数据量/时长
        # -vf：限制输出FPS以及统一输出分辨率
        # -pix_fmt： 让ffmpeg直接输出BGR
        # -f rawvideo: 直接把一帧一帧的原始像素写到stdout
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
            # ffmpeg错误信息全部丢掉
            stderr=sp.DEVNULL,
            bufsize=0,
        )
        logger.info(f"[Camera:{self.name}] ffmpeg 进程启动")

    def _restart_ffmpeg(self):
        """结束旧ffmpeg，等一会，启动新的ffmpeg"""
        self._stop_ffmpeg()
        # 等一小会
        if self.stop_event.wait(self.restart_cooldown):
            return
        # 重新开启ffmpeg
        self._start_ffmpeg()

    def _stop_ffmpeg(self):
        if self.pipe:
            try:
                # 等2秒
                self.pipe.terminate()
                self.pipe.wait(timeout=_FFMPEG_STOP_SECONDS)
            except sp.TimeoutExpired:
                # 如果还不退出旧kill
                self.pipe.kill()
                self.pipe.wait(timeout=_FFMPEG_STOP_SECONDS)
            finally:
                # 关闭stdout
                if self.pipe.stdout:
                    self.pipe.stdout.close()
                self.pipe = None

    def _read_frame(self, frame_size: int) -> bytes | None:
        """分段读取一帧，定期检查停止信号；只把管道 I/O 失败归类为流异常。"""
        raw = bytearray()
        stdout = self.pipe.stdout
        while len(raw) < frame_size:
            if self.stop_event.is_set():
                return None
            try:
                readable, _, _ = select.select([stdout], [], [], _READ_POLL_SECONDS)
                if not readable:
                    continue
                chunk = os.read(stdout.fileno(), frame_size - len(raw))
            except OSError as exc:
                raise CameraStreamError(f"ffmpeg 管道读取失败: {exc}") from exc
            if not chunk:
                raise CameraStreamError("帧读取异常(stream closed)")
            raw.extend(chunk)
        return bytes(raw)

    def _emit_runtime_event(self, event_type: str, detail: str):
        """向上层汇报Camera Runtime异常"""
        if self.event_queue is None:
            return
        try:
            self.event_queue.put_nowait({
                "shm_name": self.shm_name,
                "camera_name": self.name,
                "event_type": event_type,
                "detail": detail,
            })
        # Event Queue满了或者挂了，记录日志后丢弃事件，不等待队列恢复
        except Full:
            logger.warning(f"[Camera:{self.name}] 运行事件队列已满，丢弃事件: {event_type}")
        except Exception:
            logger.exception(f"[Camera:{self.name}] 运行事件投递失败: {event_type}")

    # ---------- 采集主循环 ----------
    def _capture_loop(self, active_index, frame_seq):
        """"""
        try:
            from setproctitle import setproctitle
            setproctitle(f"Camera[{self.shm_name}]")
        except ImportError:
            pass
        # 一帧有多少字节
        frame_size = self.width * self.height * self.channels
        # 两个共享内存，双缓冲Double Buffer
        # （buffer 0 当前给别人读，buffer1 camera偷偷写下一帧）
        # 写完 active_index=1，缓存buffer1 作为读取内存，buffer0写下一帧
        shm_names = [self.shm_name + "_0", self.shm_name + "_1"]
        shms = []
        buffers = []
        try:
            for name in shm_names:
                shms.append(self._create_or_attach_shm(name, frame_size))
            frame_shape = (self.height, self.width, self.channels)
            # 不额外申请一份Numy图像内存，而是让Numpy数组直接"套"在共享内存上
            buffers = [np.ndarray(frame_shape, dtype=np.uint8, buffer=s.buf) for s in shms]
            # 开始ffmpeg
            self._start_ffmpeg()
            # 下一帧是写0还是写1
            idx = 0
            # 上一帧灰度缩略图，用于花屏检测
            prev_gray = None
            # 最近发生多少次ffmpeg重启
            restart_times = deque()

            # 开始无限采集（ self.stop_event.is_set：收到停止命令）
            while not self.stop_event.is_set():
                start = time.time()
                try:
                    # 从ffmpeg读一帧
                    raw = self._read_frame(frame_size)
                    if raw is None:
                        break
                    # 一帧没读完整或者stream关闭了
                    if len(raw) != frame_size:
                        raise CameraStreamError("帧读取异常(stream closed)")
                    # 字节转numpy（获取图像）
                    frame = np.frombuffer(raw, dtype=np.uint8).reshape(frame_shape)

                    # 花屏检测
                    # 1、每四个像素取一个
                    small = frame[::4, ::4]
                    # 转灰度+高斯模糊
                    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                    gray = cv2.GaussianBlur(gray, (5, 5), 0)
                    if prev_gray is not None:
                        # 比较
                        diff = cv2.absdiff(gray, prev_gray)
                        _, bin_diff = cv2.threshold(diff, 10, 255, cv2.THRESH_BINARY)
                        # 范围变成0~1     
                        ratio = bin_diff.mean() / 255.0
                        # 如果diff_threshold没有设成小于1的值，花屏检测不会触发
                        if ratio > self.diff_threshold:
                            logger.warning(f"[Camera:{self.name}] 花屏 (ratio={ratio:.2f}),跳过")
                            prev_gray = gray
                            continue
                    prev_gray = gray
                    # 检测以后写共享内存
                    buffers[idx][:] = frame
                    # 告诉其他进程，新帧已经在Buffer idx里了
                    active_index.value = idx
                    # 帧序号+1
                    frame_seq.value += 1
                    # 第一帧成功
                    self.ready_event.set()
                    # 实现双缓冲切换
                    idx = 1 - idx
                    # 假设设置0.2秒一帧，但是处理只花了0.15秒，那么让其沉睡0.05秒，防止处理过快
                    sleep_time = self.frame_interval - (time.time() - start)
                    if sleep_time > 0:
                        self.stop_event.wait(sleep_time)
                # 仅流读取异常进入ffmpeg重启，程序异常由外层记录并退出
                except CameraStreamError as e:
                    now = time.time()
                    # 超过重启统计窗口（默认600秒）的记录
                    while restart_times and now - restart_times[0] > self.restart_window_seconds:
                        # 从deque头部删除
                        restart_times.popleft()
                    # deque永远只记录：当前统计窗口内的重启次数
                    restart_times.append(now)
                    # 如果大于重启次数，停止，让camera采集子进程退出
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
                    # ffmpeg重启的话，上一帧其实已经没有意义了
                    prev_gray = None
                    # 继续拉流
                    self._restart_ffmpeg()
        except Exception as exc:
            logger.exception(f"[Camera:{self.name}] 采集程序异常，退出采集进程")
            self._emit_runtime_event("采集程序异常", f"{type(exc).__name__}: {exc}")
            raise
        finally:
            # 最终都要释放共享内存
            try:
                self._stop_ffmpeg()
            except Exception:
                logger.exception(f"[Camera:{self.name}] ffmpeg 清理失败")
            buffers.clear()
            for shm in shms:
                try:
                    shm.close()
                    shm.unlink()
                except Exception as e:
                    logger.warning(f"[Camera:{self.name}] 释放共享内存失败: {e}")

    @staticmethod
    def _create_or_attach_shm(name: str, size: int) -> shared_memory.SharedMemory:
        """创建共享内存,如果残留（发现旧的同名的共享内存）则先清理后重建
        流程：
            attach旧的
            close
            unlink
            重新create
        """
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
