# 文件说明：实现视频帧相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：撤下旧 FrameHub 路径，避免分辨率变化时截断仍被映射的文件；输入与输出详见下方说明
# 参数：
#   - `runtime_dir`（Path）：`runtime_dir` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_frame_hub.py` 的 `test_frame_hub_resolution_change_keeps_old_mapping_safe`
#         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::_start_runtime` 调用本符号
#   - 内部调用：`Path(runtime_dir).resolve`、`Path`、`(root / FRAME_META_NAME).unlink`、`(root / name).unlink`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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
# 功能：原子写 JSON: 先写到同目录下的唯一临时文件,再用 os.replace 原地替换；输入与输出详见下方说明
# 参数：
#   - `path`（Path）：目标路径
#   - `payload`（Dict[str, Any]）：接口或事件携带的业务数据
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`path.parent.mkdir`、`NamedTemporaryFile`、`Path`、`json.dump`、`tmp.flush`、`os.replace`、`tmp_path.unlink`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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
 
 
# 功能：安全读 JSON: 文件不存在或解析失败时返回 default,不抛异常；输入与输出详见下方说明
# 参数：
#   - `path`（Path）：目标路径
#   - `default`（Optional[Dict[str, Any]]）：`default` 对应的业务输入值；默认值为 `None`
# 返回：Optional[Dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/frame_hub.py` 的 `FrameHubReader::_wait_ready`
#         调用本符号；`AiVision/integrations/security_vlm/src/frame_hub.py` 的 `FrameHubReader::get_latest_meta`
#         调用本符号；`AiVision/integrations/security_vlm/src/frame_hub.py` 的 `ResultStore::read` 调用本符号
#   - 内部调用：`path.exists`、`json.loads`、`path.read_text`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
# 功能：采集进程使用: 把最新视频帧写入 /dev/shm 的双缓冲 slot；输入与输出详见下方说明
# 参数：
#   - `runtime_dir`（Path）：`runtime_dir` 对应的业务输入值
#   - `height`（int）：`height` 对应的业务输入值
#   - `width`（int）：`width` 对应的业务输入值
#   - `channels`（int）：`channels` 对应的业务输入值；默认值为 `3`
# 返回：FrameHubWriter；返回新建的 `FrameHubWriter` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_frame_hub.py` 的 `test_frame_hub_resolution_change_keeps_old_mapping_safe`
#         实例化本符号；`AiVision/integrations/security_vlm/tests/test_frame_hub.py` 的
#         `test_frame_hub_reader_retries_when_meta_precedes_slots::start_writer`
#         实例化本符号；`AiVision/integrations/security_vlm/src/capture_worker.py` 的 `main` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
 
    # 功能：初始化或配置 `__init__` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `runtime_dir`（Path）：`runtime_dir` 对应的业务输入值
    #   - `height`（int）：`height` 对应的业务输入值
    #   - `width`（int）：`width` 对应的业务输入值
    #   - `channels`（int）：`channels` 对应的业务输入值；默认值为 `3`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path(runtime_dir).resolve`、`Path`、`self.runtime_dir.mkdir`、`int`、`np.dtype`、`self.meta_path.unlink`、`self._init_slots`、`np.memmap`、`atomic_write_json`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件。
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
 
    # 功能：以新 inode 创建固定大小 slot，保留旧 memmap 的访问安全；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/frame_hub.py` 的 `FrameHubWriter::__init__` 调用本符号
    #   - 内部调用：`path.unlink`、`open`、`f.truncate`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def _init_slots(self) -> None:
        """以新 inode 创建固定大小 slot，保留旧 memmap 的访问安全。"""
        for path in self.slot_paths:
            path.unlink(missing_ok=True)
            with open(path, "wb") as f:
                f.truncate(self.nbytes)
 
    # 功能：写一帧并切换 slot；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    #   - `frame_id`（int）：`frame_id` 对应业务对象的唯一标识
    # 返回：Dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`buf.flush`、`int`、`time.time`、`atomic_write_json`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件。
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
# 功能：下游 worker 使用: 只读最新帧,绝不阻塞写者；输入与输出详见下方说明
# 参数：
#   - `runtime_dir`（Path）：`runtime_dir` 对应的业务输入值
#   - `wait_timeout_sec`（float）：`wait_timeout_sec` 对应的业务输入值；默认值为 `15.0`
# 返回：FrameHubReader；返回新建的 `FrameHubReader` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_frame_hub.py` 的 `test_frame_hub_resolution_change_keeps_old_mapping_safe`
#         实例化本符号；`AiVision/integrations/security_vlm/tests/test_frame_hub.py` 的
#         `test_frame_hub_reader_retries_when_meta_precedes_slots`
#         实例化本符号；`AiVision/integrations/security_vlm/src/detector_worker.py` 的 `main`
#         实例化本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::get_frame_hub` 实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FrameHubReader:
    """
    下游 worker 使用: 只读最新帧,绝不阻塞写者。
 
    工作流程:
        1. 启动时等待 frame_meta.json 出现 (capture 还没启动时会等)
        2. 读 meta -> 知道最新 slot_idx
        3. 从对应 memmap 复制一份出来 (.copy() 防止下次写覆盖)
    """
 
    # 功能：初始化或配置 `__init__` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `runtime_dir`（Path）：`runtime_dir` 对应的业务输入值
    #   - `wait_timeout_sec`（float）：`wait_timeout_sec` 对应的业务输入值；默认值为 `15.0`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path(runtime_dir).resolve`、`Path`、`float`、`self._wait_ready`、`int`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, runtime_dir: Path, wait_timeout_sec: float = 15.0):
        self.runtime_dir = Path(runtime_dir).resolve()
        self.meta_path = self.runtime_dir / FRAME_META_NAME
        self.slot_paths = [
            self.runtime_dir / FRAME_SLOT_NAMES[0],
            self.runtime_dir / FRAME_SLOT_NAMES[1],
        ]
        self.wait_timeout_sec = float(wait_timeout_sec)
 
        # 把 meta 和两个 slot 视为一个整体等待。进程组重启时，meta 可能短暂
        # 指向刚被撤换的 slot；单独等待 meta 会让该竞态变成 FileNotFoundError。
        self.meta, self.buffers = self._wait_ready()
        self.height = int(self.meta["height"])
        self.width = int(self.meta["width"])
        self.channels = int(self.meta["channels"])
        self.dtype = np.uint8

    # 功能：轮询完整 FrameHub，容忍启动或重启期间 meta/slot 短暂不同步；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：tuple[Dict[str, Any], list[np.memmap]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/frame_hub.py` 的 `FrameHubReader::__init__` 调用本符号
    #   - 内部调用：`time.time`、`read_json`、`all`、`int`、`np.memmap`、`TimeoutError`、`time.sleep`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def _wait_ready(self) -> tuple[Dict[str, Any], list[np.memmap]]:
        """轮询完整 FrameHub，容忍启动或重启期间 meta/slot 短暂不同步。"""
        t0 = time.time()
        last_error: Exception | None = None
        while True:
            meta = read_json(self.meta_path)
            if meta and all(k in meta for k in ("height", "width", "channels", "slot_idx", "frame_id")):
                try:
                    height = int(meta["height"])
                    width = int(meta["width"])
                    channels = int(meta["channels"])
                    shape = (height, width, channels)
                    buffers = [
                        np.memmap(path, dtype=np.uint8, mode="r", shape=shape)
                        for path in self.slot_paths
                    ]
                    return meta, buffers
                except (FileNotFoundError, OSError, ValueError) as exc:
                    # capture 可能正在以新 inode 替换 slot，下一轮重新读取 meta，
                    # 同时也能避开旧尺寸 meta 与新尺寸 slot 的瞬时组合。
                    last_error = exc
            if time.time() - t0 > self.wait_timeout_sec:
                detail = f"，最后错误: {last_error}" if last_error else ""
                raise TimeoutError(
                    f"等待 FrameHub 就绪超时: {self.runtime_dir}{detail}"
                ) from last_error
            time.sleep(0.05)
 
    # 功能：每次调用都重新读 meta,获取最新 slot_idx 和 frame_id；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：Dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/frame_hub.py` 的 `FrameHubReader::read_frame`
    #         调用本符号；`AiVision/integrations/security_vlm/src/detector_worker.py` 的 `main`
    #         调用本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `create_app::_mjpeg`
    #         调用本符号；`AiVision/integrations/security_vlm/src/session_worker.py` 的 `main` 调用本符号
    #   - 内部调用：`read_json`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def get_latest_meta(self) -> Dict[str, Any]:
        """
        每次调用都重新读 meta,获取最新 slot_idx 和 frame_id。
        若读失败(撞上写者半路),返回上一次缓存的 meta,保证业务不中断。
        """
        meta = read_json(self.meta_path, self.meta)
        if meta is not None:
            self.meta = meta
        return self.meta
 
    # 功能：读最新帧。.copy() 是必须的,否则下游处理过程中可能被写者覆盖；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `meta`（Optional[Dict[str, Any]]）：`meta` 对应的业务输入值；默认值为 `None`
    # 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_frame_hub.py` 的
    #         `test_frame_hub_resolution_change_keeps_old_mapping_safe`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_frame_hub.py` 的
    #         `test_frame_hub_reader_retries_when_meta_precedes_slots`
    #         调用本符号；`AiVision/integrations/security_vlm/src/detector_worker.py` 的 `main`
    #         调用本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `create_app::_mjpeg` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`self.get_latest_meta`、`np.asarray(self.buffers[int(meta['slot_idx'])]).copy`、`np.asarray`、`int`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def read_frame(self, meta: Optional[Dict[str, Any]] = None) -> np.ndarray:
        """
        读最新帧。.copy() 是必须的,否则下游处理过程中可能被写者覆盖。
        """
        meta = meta or self.get_latest_meta()
        return np.asarray(self.buffers[int(meta["slot_idx"])]).copy()


# 功能：返回下游 worker 等待 capture 首帧的统一超时时间；输入与输出详见下方说明
# 参数：
#   - `cfg`（Dict[str, Any]）：运行配置对象
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/detector_worker.py` 的 `main`
#         调用本符号；`AiVision/integrations/security_vlm/src/session_worker.py` 的 `main` 调用本符号
#   - 内部调用：`cfg.get`、`max`、`float`、`runtime_cfg.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def framehub_wait_timeout(cfg: Dict[str, Any]) -> float:
    """返回下游 worker 等待 capture 首帧的统一超时时间。"""
    runtime_cfg = cfg.get("runtime", {}) or {}
    return max(1.0, float(runtime_cfg.get("framehub_wait_timeout_sec", 30.0)))
 
 
# ---------------------------------------------------------------------------
# ResultStore —— 跨进程通用 KV 状态存储
# ---------------------------------------------------------------------------
# 功能：worker 之间共享 JSON 状态的键值存储 (基于原子文件写)；输入与输出详见下方说明
# 参数：
#   - `runtime_dir`（Path）：`runtime_dir` 对应的业务输入值
# 返回：ResultStore；返回新建的 `ResultStore` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentResultStores::__init__`
#         实例化本符号；`AiVision/integrations/security_vlm/src/detector_worker.py` 的 `main`
#         实例化本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::camera_store`
#         实例化本符号；`AiVision/integrations/security_vlm/src/session_worker.py` 的 `main` 实例化本符号；另有 2 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
 
    # 功能：初始化或配置 `__init__` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `runtime_dir`（Path）：`runtime_dir` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path(runtime_dir).resolve`、`Path`、`self.runtime_dir.mkdir`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件。
    def __init__(self, runtime_dir: Path):
        self.runtime_dir = Path(runtime_dir).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
 
    # 功能：实现 `_path` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/frame_hub.py` 的 `ResultStore::write`
    #         调用本符号；`AiVision/integrations/security_vlm/src/frame_hub.py` 的 `ResultStore::read`
    #         调用本符号；`AiVision/integrations/security_vlm/src/frame_hub.py` 的 `ResultStore::delete`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `read_strict_result_object` 调用本符号；另有 4 处静态调用
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _path(self, key: str) -> Path:
        return self.runtime_dir / f"{key}.json"
 
    # 功能：更新或保存 `write` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    #   - `payload`（Dict[str, Any]）：接口或事件携带的业务数据
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`atomic_write_json`、`self._path`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def write(self, key: str, payload: Dict[str, Any]) -> None:
        atomic_write_json(self._path(key), payload)
 
    # 功能：读取或查询 `read` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    #   - `default`（Optional[Dict[str, Any]]）：`default` 对应的业务输入值；默认值为 `None`
    # 返回：Optional[Dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`read_json`、`self._path`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def read(self, key: str, default: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        return read_json(self._path(key), default)
 
    # 功能：删除或清理 `delete` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._path`、`p.exists`、`p.unlink`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
