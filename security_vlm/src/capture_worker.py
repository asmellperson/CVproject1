"""
================================================================================
capture_worker.py —— RTSP 视频采集子进程
================================================================================
职责:
    1. 从配置里指定的 RTSP 地址拉流 (cv2.VideoCapture + ffmpeg)
    2. 用一个后台线程持续读帧,主线程负责限频写到 FrameHub
    3. 自动检测断流并重连 (50 次连读失败 或 5 秒拿不到帧)
    4. 周期性把状态 (fps、frame_id、分辨率) 写到 capture_status.json

输出:
    - /dev/shm/.../frame_meta.json  + frame_slot_{0,1}.bin (FrameHubWriter 写)
    - /dev/shm/.../capture_status.json (心跳)

为什么把读流放到独立线程:
    OpenCV 的 cap.read() 对 RTSP 是阻塞的,且 ffmpeg 内部有 jitter buffer。
    用独立线程不停地 drain,保证主线程拿到的永远是「最新一帧」而不是积压帧。

为什么主循环还要再限频:
    摄像头本身可能 25/30 fps,但下游 YOLO 推理大概只能跑 8-12 fps,
    高频写 FrameHub 没有意义,只会浪费 IO。所以这里用 target_fps 限流。
================================================================================
"""
import argparse
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

import cv2
import yaml

# 让本目录下的 frame_hub.py 可被 import
sys.path.insert(0, str(Path(__file__).resolve().parent))

from frame_hub import FrameHubWriter, ResultStore  # noqa: E402

# ---------------------------------------------------------------------------
# 关键: 在 import cv2 后立刻设置 ffmpeg 选项 (OpenCV 通过环境变量传给 ffmpeg)
#   - rtsp_transport=tcp   走 TCP, 海康/大华摄像头默认走这个更稳定
#   - buffer_size=1MB      ffmpeg 内部缓冲, 防止丢包
#   - reorder_queue_size   重排队列 (UDP 时才用)
#   - timeout=5s           连接 + 读超时
# ---------------------------------------------------------------------------
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|buffer_size;1048576|reorder_queue_size;1024|timeout;5000000",
)
os.environ.setdefault("OPENCV_FFMPEG_READ_ATTEMPTS", "10000")


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


# 全局停止信号 (SIGINT/SIGTERM 触发)
_STOP = threading.Event()


def _signal_handler(signum, frame):
    _STOP.set()


# ---------------------------------------------------------------------------
# RtspCapture —— 后台线程拉流 + 自动重连
# ---------------------------------------------------------------------------
class RtspCapture:
    """
    后台线程不断 cap.read(),把最新一帧用锁保护起来。
    主线程通过 read() 拿当前最新帧 + frame_id。

    断流策略:
        - 单次 read 失败计数累加
        - 累计 50 次失败 或 5 秒没拿到新帧 → release + 重新 open
    """

    def __init__(self, source: str, log_prefix: str = "[capture]"):
        self.source = str(source)
        self.log_prefix = log_prefix
        self.cap = None
        self.lock = threading.Lock()
        self.frame = None              # 最新一帧 (BGR ndarray)
        self.frame_id = 0              # 单调递增的帧序号
        self.last_ok_ts = 0.0          # 上次成功读到帧的时间
        self.stop_flag = False
        self.thread = None

    def _open(self) -> bool:
        """打开 RTSP 并把内部缓冲调到 1,降低延迟"""
        cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if not cap.isOpened():
            print(f"{self.log_prefix} 打开失败: {self.source}", flush=True)
            return False
        self.cap = cap
        self.last_ok_ts = time.time()
        return True

    def start(self):
        if not self._open():
            raise RuntimeError(f"无法打开视频源: {self.source}")
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return self

    def _loop(self):
        """后台线程主循环"""
        consecutive_fail = 0
        while not self.stop_flag:
            # 上次重连失败后 cap=None,这里再尝试 open
            if self.cap is None:
                if not self._open():
                    time.sleep(1.0)
                    continue

            ok, frame = self.cap.read()
            if not ok or frame is None:
                consecutive_fail += 1
                # 触发重连的两个条件: 累计失败 50 次 OR 5 秒没拿到帧
                if consecutive_fail >= 50 or (time.time() - self.last_ok_ts) > 5.0:
                    print(f"{self.log_prefix} 读帧连续失败 {consecutive_fail} 次,重连...",
                          flush=True)
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    self.cap = None
                    consecutive_fail = 0
                    time.sleep(1.0)
                else:
                    time.sleep(0.02)
                continue

            # 成功读到一帧 → 更新最新帧 (写者短临界区)
            consecutive_fail = 0
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
        if self.thread is not None:
            self.thread.join(timeout=1.5)
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass


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
        capture = RtspCapture(source, log_prefix="[capture]")
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