"""
================================================================================
capture_worker.py —— RTSP 视频采集子进程
================================================================================
职责:
    1. 从配置里指定的 RTSP 地址拉流 (FFmpeg TCP rawvideo)
    2. 用一个后台线程持续读帧,主线程负责限频写到 FrameHub
    3. 自动检测断流并重连
    4. 周期性把状态 (fps、frame_id、分辨率) 写到 capture_status.json

输出:
    - /dev/shm/.../frame_meta.json  + frame_slot_{0,1}.bin (FrameHubWriter 写)
    - /dev/shm/.../capture_status.json (心跳)

为什么把读流放到独立线程:
    FFmpeg 的 rawvideo 管道读取对 RTSP 是阻塞的。
    用独立线程不停地 drain,保证主线程拿到的永远是「最新一帧」而不是积压帧。

为什么主循环还要再限频:
    摄像头本身可能 25/30 fps,但下游 YOLO 推理大概只能跑 8-12 fps,
    高频写 FrameHub 没有意义,只会浪费 IO。所以这里用 target_fps 限流。
================================================================================
"""
import argparse
import json
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

import numpy as np
import yaml

# 让本目录下的 frame_hub.py 可被 import
sys.path.insert(0, str(Path(__file__).resolve().parent))

from frame_hub import FrameHubWriter, ResultStore  # noqa: E402


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def set_process_title(title: str) -> None:
    """改进程名,方便 ps / top 里识别(安装了 setproctitle 才生效)"""
    try:
        from setproctitle import setproctitle
        setproctitle(str(title))
    except Exception:
        pass


def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_path(p: str, base: Path) -> Path:
    """相对路径以项目根为基准解析"""
    pp = Path(p)
    return pp.resolve() if pp.is_absolute() else (base / pp).resolve()


def _is_rtsp_source(source: str) -> bool:
    return str(source).lower().startswith(("rtsp://", "rtsps://"))


def build_ffmpeg_command(source: str, target_fps: float) -> list[str]:
    """构造稳定解码 HEVC RTSP 的 FFmpeg rawvideo 命令。"""
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
    if _is_rtsp_source(source):
        # 部分生产服务器的 FFmpeg 不支持 rw_timeout；强制传入会让
        # FFmpeg 在解析参数时立即退出，表现为 capture 永远拿不到首帧。
        command.extend(["-rtsp_transport", "tcp"])
    command.extend([
        "-i", str(source),
        "-an",
        "-vf", f"fps={max(1.0, float(target_fps)):g}",
        "-pix_fmt", "bgr24",
        "-f", "rawvideo",
        "pipe:1",
    ])
    return command


def read_exact(stream, size: int) -> bytes | None:
    """从管道读取恰好 size 字节；提前 EOF 时返回 None。"""
    remaining = int(size)
    chunks = bytearray()
    while remaining > 0:
        try:
            chunk = stream.read(remaining)
        except (OSError, ValueError):
            return None
        if not chunk:
            return None
        chunks.extend(chunk)
        remaining -= len(chunk)
    return bytes(chunks)


def probe_video_shape(source: str, runner=None) -> tuple[int, int, int]:
    """使用 ffprobe 获取视频尺寸，返回 (height, width, channels)。"""
    command = ["ffprobe", "-v", "error"]
    if _is_rtsp_source(source):
        command.extend(["-rtsp_transport", "tcp"])
    command.extend([
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(source),
    ])
    run = runner or subprocess.run
    try:
        result = run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        streams = (json.loads(result.stdout or "{}").get("streams") or [])
        width = int(streams[0].get("width", 0)) if streams else 0
        height = int(streams[0].get("height", 0)) if streams else 0
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("ffprobe 获取视频分辨率失败") from exc
    if width <= 0 or height <= 0:
        raise RuntimeError("ffprobe 未返回有效分辨率")
    return height, width, 3


# 全局停止信号 (SIGINT/SIGTERM 触发)
_STOP = threading.Event()


def _signal_handler(signum, frame):
    _STOP.set()


# ---------------------------------------------------------------------------
# RtspCapture —— 后台线程拉流 + 自动重连
# ---------------------------------------------------------------------------
class RtspCapture:
    """
    后台线程从 FFmpeg rawvideo 管道读取完整 BGR 帧,把最新一帧用锁保护起来。
    主线程通过 read() 拿当前最新帧 + frame_id。

    断流策略:
        - FFmpeg 退出、EOF 或读到不完整帧时关闭旧进程
        - 等待 1 秒后重新拉起 FFmpeg
    """

    def __init__(
        self,
        source: str,
        target_fps: float = 10.0,
        log_prefix: str = "[capture]",
        process_factory=None,
        probe_runner=None,
        sleep_fn=None,
    ):
        self.source = str(source)
        self.target_fps = max(1.0, float(target_fps))
        self.log_prefix = log_prefix
        self.process = None
        self.frame_shape: tuple[int, int, int] | None = None
        self._process_factory = process_factory or subprocess.Popen
        self._probe_runner = probe_runner
        self._sleep = sleep_fn or time.sleep
        self.lock = threading.Lock()
        self.frame = None              # 最新一帧 (BGR ndarray)
        self.frame_id = 0              # 单调递增的帧序号
        self.last_ok_ts = 0.0          # 上次成功读到帧的时间
        self.stop_flag = False
        self.thread = None

    def _open(self) -> bool:
        """探测分辨率并启动 FFmpeg rawvideo 子进程。"""
        try:
            if self.frame_shape is None:
                self.frame_shape = probe_video_shape(
                    self.source,
                    runner=self._probe_runner,
                )
            command = build_ffmpeg_command(self.source, self.target_fps)
            self.process = self._process_factory(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10**8,
            )
            if self.process.stdout is None:
                raise RuntimeError("FFmpeg stdout 管道不可用")
            threading.Thread(
                target=self._drain_stderr,
                args=(self.process,),
                daemon=True,
            ).start()
            self.last_ok_ts = time.time()
            height, width, _ = self.frame_shape
            print(
                f"{self.log_prefix} FFmpeg 已启动，视频尺寸 {width}x{height}，"
                f"目标帧率 {self.target_fps:g}",
                flush=True,
            )
            return True
        except Exception as exc:
            self._close_process()
            print(
                f"{self.log_prefix} FFmpeg 启动失败: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return False

    def _drain_stderr(self, process) -> None:
        """消费 FFmpeg stderr，避免管道写满，并隐藏 RTSP 凭据。"""
        if process.stderr is None:
            return
        while True:
            raw_line = process.stderr.readline()
            if not raw_line:
                return
            message = raw_line.decode("utf-8", errors="replace").strip()
            if message:
                print(
                    f"{self.log_prefix} ffmpeg: "
                    f"{message.replace(self.source, '<redacted>')}",
                    file=sys.stderr,
                    flush=True,
                )

    def _read_one_frame(self):
        """从当前 FFmpeg 管道读取并复制一帧 BGR 图像。"""
        process = self.process
        if process is None or process.stdout is None or self.frame_shape is None:
            return None
        frame_size = int(np.prod(self.frame_shape))
        raw = read_exact(process.stdout, frame_size)
        if raw is None:
            return None
        return np.frombuffer(raw, dtype=np.uint8).reshape(self.frame_shape).copy()

    def _close_process(self) -> None:
        """终止并回收当前 FFmpeg 子进程及其管道。"""
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            pass
        for pipe_name in ("stdout", "stderr"):
            pipe = getattr(process, pipe_name, None)
            close = getattr(pipe, "close", None)
            if callable(close):
                try:
                    close()
                except OSError:
                    pass

    def start(self):
        if not self._open():
            raise RuntimeError("无法通过 FFmpeg 打开视频源")
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return self

    def _loop(self):
        """后台线程主循环"""
        while not self.stop_flag:
            # 上次进程退出后重新拉起 FFmpeg。
            if self.process is None:
                if not self._open():
                    self._sleep(1.0)
                    continue

            frame = self._read_one_frame()
            if frame is None:
                if not self.stop_flag:
                    print(
                        f"{self.log_prefix} FFmpeg 视频流中断，准备重连...",
                        flush=True,
                    )
                self._close_process()
                if not self.stop_flag:
                    self._sleep(1.0)
                continue

            # 成功读到一帧 → 更新最新帧 (写者短临界区)
            self.last_ok_ts = time.time()
            with self.lock:
                self.frame = frame
                self.frame_id += 1

    def read(self):
        """供主线程调用,拿最新帧的拷贝 (避免被后台线程覆盖)"""
        with self.lock:
            if self.frame is None:
                return False, None, -1
            return True, self.frame.copy(), self.frame_id

    def wait_first_frame(self, timeout: float = 15.0) -> bool:
        """阻塞等首帧,主要为了拿到分辨率以初始化 FrameHubWriter"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            ok, _, _ = self.read()
            if ok:
                return True
            time.sleep(0.1)
        return False

    def release(self):
        self.stop_flag = True
        self._close_process()
        if self.thread is not None:
            self.thread.join(timeout=1.5)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main():
    set_process_title("security_vlm[capture]")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=str)
    args = parser.parse_args()

    # 读配置 -------------------------------------------------------------
    project_root = Path(__file__).resolve().parent.parent
    config_path = resolve_path(args.config, project_root)
    cfg = load_yaml(config_path)

    source = str(cfg["data"]["input_video"])
    runtime_dir = Path(cfg["runtime"]["dir"]).resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    # 主循环写帧的目标 fps,从 runtime.camera_fps_hint 读,默认 10
    target_fps = float(cfg.get("runtime", {}).get("camera_fps_hint", 10.0))
    target_fps = max(1.0, target_fps)
    min_interval = 1.0 / target_fps

    # 状态心跳 -----------------------------------------------------------
    status_store = ResultStore(runtime_dir)
    status_key = "capture_status"

    # 信号处理 -----------------------------------------------------------
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    status_store.write(status_key, {"ok": False, "message": "starting", "ts": time.time()})

    # 启动 RTSP 拉流 -----------------------------------------------------
    try:
        capture = RtspCapture(
            source,
            target_fps=target_fps,
            log_prefix="[capture]",
        )
        capture.start()
    except Exception as e:
        status_store.write(status_key, {"ok": False, "message": f"open_failed: {e}",
                                        "ts": time.time()})
        print(f"[capture] 启动失败: {e}", flush=True)
        return

    # 等首帧 → 拿分辨率 → 初始化 FrameHubWriter --------------------------
    if not capture.wait_first_frame(timeout=15.0):
        status_store.write(status_key, {"ok": False, "message": "no_first_frame",
                                        "ts": time.time()})
        capture.release()
        print("[capture] 首帧超时", flush=True)
        return

    _, frame, _ = capture.read()
    h, w = frame.shape[:2]
    print(f"[capture] 首帧获取成功 {w}x{h},开始写入 FrameHub", flush=True)

    writer = FrameHubWriter(runtime_dir, height=h, width=w, channels=3)

    # 主循环: 限频写 FrameHub + 周期心跳 ---------------------------------
    last_frame_id = 0
    last_status_ts = 0.0
    last_write_ts = 0.0
    fps_counter = 0
    fps_window_start = time.time()
    display_fps = 0.0

    try:
        while not _STOP.is_set():
            ok, fr, fid = capture.read()

            # 没新帧或没读到 → 短暂 sleep,继续轮询
            if not ok or fid == last_frame_id:
                time.sleep(0.003)
                continue

            now = time.time()
            # 限频: 距离上次写不到 1/target_fps 秒 → 直接丢
            # (注意此处不更新 last_frame_id, 等下次循环再判断)
            if now - last_write_ts < min_interval:
                continue

            # 写一帧到 FrameHub (双缓冲切换在 writer 内部完成)
            last_frame_id = fid
            writer.write(fr, fid)
            last_write_ts = now
            fps_counter += 1

            # 每 2 秒计算一次平均 fps,用于心跳上报
            if now - fps_window_start >= 2.0:
                display_fps = fps_counter / (now - fps_window_start)
                fps_counter = 0
                fps_window_start = now

            # 每 2 秒上报一次心跳 (前端从这里读分辨率/fps)
            if now - last_status_ts > 2.0:
                status_store.write(status_key, {
                    "ok": True,
                    "frame_id": fid,
                    "fps": round(display_fps, 2),
                    "height": h, "width": w,
                    "ts": now,
                })
                last_status_ts = now
    except Exception as e:
        status_store.write(status_key, {"ok": False, "message": str(e), "ts": time.time()})
        print(f"[capture] 主循环异常: {e}", flush=True)
    finally:
        print("[capture] 退出中...", flush=True)
        capture.release()
        status_store.write(status_key, {"ok": False, "message": "stopped", "ts": time.time()})


if __name__ == "__main__":
    main()
