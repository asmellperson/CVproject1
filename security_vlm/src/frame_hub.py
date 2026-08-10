"""
================================================================================
frame_hub.py —— 共享内存帧库 + 原子 JSON 状态存储
================================================================================
作用:
    本模块是整个项目的「数据底座」。多个独立 Python 进程
    (capture / detector / session / vlm / web) 之间需要交换两类数据:
        1. 视频帧 (大、二进制、高频)  → 走 /dev/shm 双缓冲 memmap
        2. 状态/结果 (小、JSON、可序列化) → 走 /dev/shm 上的原子写 JSON 文件
 
设计要点:
    - 视频帧用「双缓冲 (double buffer)」: 写者轮流写 slot0 / slot1,读者
      永远读 meta.json 指向的最新 slot,避免读到「写一半」的脏数据。
    - JSON 状态全部走 atomic_write_json (先写 .tmp,再 os.replace),
      任何下游进程中途读取都不会读到半截文件。
    - /dev/shm 是 tmpfs (内存文件系统),IO 极快,可视作进程间共享内存。
 
三个核心类:
    FrameHubWriter : 采集进程写最新帧 (每帧 ~3MB,1080p 大约)
    FrameHubReader : 下游 worker 只读最新帧 (零拷贝 memmap)
    ResultStore    : 进程间通用 KV 状态存储 (原子 JSON)
================================================================================
"""
import json
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, Optional
 
import numpy as np


FRAME_META_NAME = "frame_meta.json"
FRAME_SLOT_NAMES = ("frame_slot_0.bin", "frame_slot_1.bin")


def reset_frame_hub(runtime_dir: Path) -> None:
    """撤下旧 FrameHub 路径，避免分辨率变化时截断仍被映射的文件。

    Linux 允许 unlink 已被 memmap 的文件：旧读者继续持有原 inode，新写者
    会在同一路径创建新文件，因此不会因文件缩小而收到 SIGBUS。
    """
    root = Path(runtime_dir).resolve()
    (root / FRAME_META_NAME).unlink(missing_ok=True)
    for name in FRAME_SLOT_NAMES:
        (root / name).unlink(missing_ok=True)
 
 
# ---------------------------------------------------------------------------
# JSON 原子读写工具
# ---------------------------------------------------------------------------
def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """
    原子写 JSON: 先写到同目录下的唯一临时文件,再用 os.replace 原地替换。
    同目录确保 replace 原子,唯一文件名允许多个线程/进程安全并发写入。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
 
 
def read_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    安全读 JSON: 文件不存在或解析失败时返回 default,不抛异常。
    用于「读者一直轮询、写者偶尔不在线」的场景。
    """
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # 极端情况下可能撞上写者刚 truncate 还没 replace,直接返回旧值
        return default
 
 
# ---------------------------------------------------------------------------
# FrameHubWriter —— 由 capture_worker 使用,写最新视频帧
# ---------------------------------------------------------------------------
class FrameHubWriter:
    """
    采集进程使用: 把最新视频帧写入 /dev/shm 的双缓冲 slot。
 
    文件布局 (假设 runtime_dir = /dev/shm/security_vlm_runtime):
        frame_meta.json      ← 元数据 (当前最新帧在哪个 slot, frame_id 等)
        frame_slot_0.bin     ← 双缓冲槽 0
        frame_slot_1.bin     ← 双缓冲槽 1
 
    写入流程 (write 方法):
        1. 把帧像素 copy 到 self.next_slot 这个 memmap
        2. flush 确保数据落到 tmpfs
        3. 原子写 frame_meta.json,把 slot_idx 切到刚写的那个
        4. self.next_slot 翻转,下次写另一个 slot
    """
 
    def __init__(self, runtime_dir: Path, height: int, width: int, channels: int = 3):
        self.runtime_dir = Path(runtime_dir).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
 
        self.height = int(height)
        self.width = int(width)
        self.channels = int(channels)
        self.dtype = np.uint8
        # 单帧字节数 = H * W * C * sizeof(uint8)
        self.nbytes = self.height * self.width * self.channels * np.dtype(self.dtype).itemsize
 
        self.meta_path = self.runtime_dir / FRAME_META_NAME
        self.slot_paths = [
            self.runtime_dir / FRAME_SLOT_NAMES[0],
            self.runtime_dir / FRAME_SLOT_NAMES[1],
        ]

        # 先撤下旧元数据，避免新 slot 尚未就绪时读者按旧尺寸打开它们。
        # 这也覆盖 capture_worker 被脱离 CameraRuntimeManager 单独启动的场景。
        self.meta_path.unlink(missing_ok=True)
        # 预先把两个 slot 文件 truncate 到固定大小,然后 memmap 进来
        self._init_slots()
        self.buffers = [
            np.memmap(self.slot_paths[0], dtype=self.dtype, mode="r+",
                      shape=(self.height, self.width, self.channels)),
            np.memmap(self.slot_paths[1], dtype=self.dtype, mode="r+",
                      shape=(self.height, self.width, self.channels)),
        ]
        self.next_slot = 0
 
        # 初始 meta: 还没有任何帧 (frame_id = -1)
        atomic_write_json(self.meta_path, {
            "height": self.height, "width": self.width, "channels": self.channels,
            "dtype": "uint8", "slot_idx": 0, "frame_id": -1, "write_ts": 0.0,
        })
 
    def _init_slots(self) -> None:
        """以新 inode 创建固定大小 slot，保留旧 memmap 的访问安全。"""
        for path in self.slot_paths:
            path.unlink(missing_ok=True)
            with open(path, "wb") as f:
                f.truncate(self.nbytes)
 
    def write(self, frame: np.ndarray, frame_id: int) -> Dict[str, Any]:
        """
        写一帧并切换 slot。
        - frame: HxWxC uint8 numpy 数组,大小必须和初始化时一致
        - frame_id: 单调递增整数,下游用它判断「是否新帧」
        """
        slot_idx = self.next_slot
        buf = self.buffers[slot_idx]
        buf[:] = frame              # 整块覆盖
        buf.flush()                 # 强制 tmpfs 落盘
        payload = {
            "height": self.height, "width": self.width, "channels": self.channels,
            "dtype": "uint8", "slot_idx": slot_idx,
            "frame_id": int(frame_id), "write_ts": time.time(),
        }
        atomic_write_json(self.meta_path, payload)
        # 翻转: 下次写另一个 slot,本次写的 slot 留给读者读
        self.next_slot = 1 - slot_idx
        return payload
 
 
# ---------------------------------------------------------------------------
# FrameHubReader —— 由 detector / session / web MJPEG 使用,只读最新帧
# ---------------------------------------------------------------------------
class FrameHubReader:
    """
    下游 worker 使用: 只读最新帧,绝不阻塞写者。
 
    工作流程:
        1. 启动时等待 frame_meta.json 出现 (capture 还没启动时会等)
        2. 读 meta -> 知道最新 slot_idx
        3. 从对应 memmap 复制一份出来 (.copy() 防止下次写覆盖)
    """
 
    def __init__(self, runtime_dir: Path, wait_timeout_sec: float = 15.0):
        self.runtime_dir = Path(runtime_dir).resolve()
        self.meta_path = self.runtime_dir / FRAME_META_NAME
        self.slot_paths = [
            self.runtime_dir / FRAME_SLOT_NAMES[0],
            self.runtime_dir / FRAME_SLOT_NAMES[1],
        ]
        self.wait_timeout_sec = float(wait_timeout_sec)
 
        # 阻塞等待 capture 写出第一份 meta (拿到 H/W/C)
        self.meta = self._wait_meta()
        self.height = int(self.meta["height"])
        self.width = int(self.meta["width"])
        self.channels = int(self.meta["channels"])
        self.dtype = np.uint8
 
        # 只读 memmap,共享同一段 tmpfs 内存,不做拷贝
        self.buffers = [
            np.memmap(self.slot_paths[0], dtype=self.dtype, mode="r",
                      shape=(self.height, self.width, self.channels)),
            np.memmap(self.slot_paths[1], dtype=self.dtype, mode="r",
                      shape=(self.height, self.width, self.channels)),
        ]
 
    def _wait_meta(self) -> Dict[str, Any]:
        """轮询 meta 文件直到出现完整字段或超时"""
        t0 = time.time()
        while True:
            meta = read_json(self.meta_path)
            if meta and all(k in meta for k in ("height", "width", "channels", "slot_idx", "frame_id")):
                return meta
            if time.time() - t0 > self.wait_timeout_sec:
                raise TimeoutError(f"等待 frame_meta.json 超时: {self.meta_path}")
            time.sleep(0.05)
 
    def get_latest_meta(self) -> Dict[str, Any]:
        """
        每次调用都重新读 meta,获取最新 slot_idx 和 frame_id。
        若读失败(撞上写者半路),返回上一次缓存的 meta,保证业务不中断。
        """
        meta = read_json(self.meta_path, self.meta)
        if meta is not None:
            self.meta = meta
        return self.meta
 
    def read_frame(self, meta: Optional[Dict[str, Any]] = None) -> np.ndarray:
        """
        读最新帧。.copy() 是必须的,否则下游处理过程中可能被写者覆盖。
        """
        meta = meta or self.get_latest_meta()
        return np.asarray(self.buffers[int(meta["slot_idx"])]).copy()


def framehub_wait_timeout(cfg: Dict[str, Any]) -> float:
    """返回下游 worker 等待 capture 首帧的统一超时时间。"""
    runtime_cfg = cfg.get("runtime", {}) or {}
    return max(1.0, float(runtime_cfg.get("framehub_wait_timeout_sec", 30.0)))
 
 
# ---------------------------------------------------------------------------
# ResultStore —— 跨进程通用 KV 状态存储
# ---------------------------------------------------------------------------
class ResultStore:
    """
    worker 之间共享 JSON 状态的键值存储 (基于原子文件写)。
 
    用法示例:
        store = ResultStore(runtime_dir)
        store.write("tracker_latest", {...})    # 写
        data = store.read("tracker_latest", {}) # 读 (默认值兜底)
 
    项目里用到的常见 key:
        capture_status        采集进程心跳 + fps
        tracker_latest        YOLO+ByteTrack 最新一帧的检测结果
        tracker_status        检测进程心跳
        session_latest        所有 ROI 的当前 session 状态
        session_status        session 进程心跳
        vlm_latest_stats      累计统计 (合规率、队列长度、花费)
        vlm_history           最近 N 条判定历史
        vlm_status            VLM 进程心跳
    """
 
    def __init__(self, runtime_dir: Path):
        self.runtime_dir = Path(runtime_dir).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
 
    def _path(self, key: str) -> Path:
        return self.runtime_dir / f"{key}.json"
 
    def write(self, key: str, payload: Dict[str, Any]) -> None:
        atomic_write_json(self._path(key), payload)
 
    def read(self, key: str, default: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        return read_json(self._path(key), default)
 
    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
