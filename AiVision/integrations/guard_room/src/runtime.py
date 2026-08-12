# runtime.py
"""
系统运行时核心模块。

负责将所有子模块（摄像头读取、目标检测、制服识别、姿态估计、
行为分析、多摄共识、报警管理、视频录制、微信推送）串联为完整的处理流水线。

整体架构：
                    ┌─────────────────────────────────────┐
    RTSPReader ──▶ LatestFrameBuffer ──▶ _process_one_camera (线程池)
    RTSPReader ──▶ LatestFrameBuffer ──▶ _process_one_camera (线程池)
                    └─────────────────────────────────────┘
                                    ↓
                          MultiCameraConsensus
                                    ↓
                    AlarmManager + AlarmClipRecorder + WeChatNotifier
                                    ↓
                              AppState (供 Web API 读取)

线程模型：
    - RTSPReader：每路摄像头一个守护线程，负责拉流并写入 LatestFrameBuffer。
    - _run_loop：主循环守护线程，读 buffer → 推理 → 报警 → 更新状态。
    - ThreadPoolExecutor（cam-infer）：各路摄像头的推理并行执行，结果汇聚后再做共识。

CUDA 内存限制（模块顶部）：
    在 import 时立即限制单进程 GPU 显存，默认 35%，可通过
    GUARD_ROOM_CUDA_MEMORY_FRACTION 覆盖，
    防止多模型（检测 × N 路 + 手机检测 + 姿态估计）共同推理时显存 OOM。
"""
from __future__ import annotations

# ── CUDA 显存限制：在任何模型加载前执行 ─────────────────────────────────────
import os
import torch
if torch.cuda.is_available():
    try:
        _cuda_fraction = float(os.getenv("GUARD_ROOM_CUDA_MEMORY_FRACTION", "0.35"))
        _cuda_fraction = min(1.0, max(0.05, _cuda_fraction))
        torch.cuda.set_per_process_memory_fraction(_cuda_fraction, device=0)
        torch.cuda.empty_cache()
    except RuntimeError as exc:
        print(f"[WARN] CUDA memory limit skipped: {exc}")
    except ValueError as exc:
        print(f"[WARN] invalid GUARD_ROOM_CUDA_MEMORY_FRACTION: {exc}")

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
from ultralytics import YOLO

from .alarm_clip_recorder import AlarmClipRecorder
from .alarms import AlarmManager
from .behavior import BehaviorEngine, RuleDecision
from .config import AppConfig
from .consensus import CameraDecisionBundle, MultiCameraConsensus
from .drawing import draw_alarm_banner, draw_detection, draw_polygon
from .pose import PoseEstimator
from .state import AppState
from .types import Detection
from .ultralytics_compat import yolo_precision_kwargs
from .uniform import UniformClassifier
from .utils import ensure_dir
from .vehicle_behavior import VehicleBehaviorEngine
from .vehicle_episode_recorder import VehicleEpisodeRecorder
from .wechat_notifier import WeChatNotifier


DEFAULT_RTSP_FFMPEG_OPTIONS = (
    "rtsp_transport;tcp|"
    "buffer_size;1048576|"
    "reorder_queue_size;1024|"
    "timeout;5000000"
)


def _is_rtsp_source(source) -> bool:
    return isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://"))


def _ensure_rtsp_ffmpeg_options() -> None:
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", DEFAULT_RTSP_FFMPEG_OPTIONS)
    os.environ.setdefault("OPENCV_FFMPEG_READ_ATTEMPTS", "10000")


def _open_video_capture(source):
    if _is_rtsp_source(source):
        _ensure_rtsp_ffmpeg_options()
        return cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    return cv2.VideoCapture(source)


# ---------------------------------------------------------------------------
# 工具类：帧缓冲与摄像头读取
# ---------------------------------------------------------------------------

class LatestFrameBuffer:
    """线程安全的单槽帧缓冲，始终只保留最新一帧。

    RTSPReader 以生产者身份持续写入；主循环以消费者身份按需读取。
    "只保留最新帧"的设计有意丢弃积压帧，确保处理的始终是当前画面，
    而非滞后数秒的历史帧。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_id: int = 0     # 单调递增，主循环用于判断是否有新帧到来
        self._ts: float = 0.0       # 写入时的 wall clock 时间戳

    def put(self, frame: np.ndarray) -> None:
        """写入新帧，覆盖上一帧（生产者调用）。"""
        with self._lock:
            self._frame = frame
            self._frame_id += 1
            self._ts = time.time()

    def get(self) -> tuple[int, float, np.ndarray | None]:
        """读取当前最新帧的副本（消费者调用）。

        Returns:
            (frame_id, timestamp, frame_copy)；尚无帧时 frame_copy 为 None。
        """
        with self._lock:
            if self._frame is None:
                return self._frame_id, self._ts, None
            return self._frame_id, self._ts, self._frame.copy()


class RTSPReader(threading.Thread):
    """单路摄像头的拉流守护线程。

    持续从 RTSP/本地文件/摄像头索引读取帧，写入 LatestFrameBuffer。
    断流后自动重连，重连间隔由 reconnect_seconds 控制。
    连续 20 帧读取失败视为流中断，触发重连。

    Attributes:
        meta:  从 VideoCapture 读取的流元数据（fps / width / height）；
               打开失败时保留初始默认值。
        error: 当前错误描述；正常运行时为 None，主循环据此判断摄像头是否在线。
    """

    def __init__(
        self,
        *,
        camera_name: str,
        source: str,
        frame_width: int,
        frame_height: int,
        reconnect_seconds: float,
        camera_buffer_size: int,
        buffer: LatestFrameBuffer,
        stop_event: threading.Event,
    ):
        """
        Args:
            camera_name:        摄像头标识，用于日志和线程命名。
            source:             视频源，RTSP URL、文件路径或摄像头索引字符串。
            frame_width/height: 预期分辨率，VideoCapture 读取失败时的回落值。
            reconnect_seconds:  断流后等待重连的秒数。
            camera_buffer_size: OpenCV 内部缓冲帧数；设为 1 降低延迟。
            buffer:             写入目标缓冲区。
            stop_event:         主循环通过此事件通知读取线程退出。
        """
        super().__init__(daemon=True, name=f"guard-room-reader-{camera_name}")
        self.camera_name = camera_name
        self.source = source
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.reconnect_seconds = reconnect_seconds
        self.camera_buffer_size = camera_buffer_size
        self.buffer = buffer
        self.stop_event = stop_event

        self.meta: dict[str, float] = {
            "fps": 12.0,            # 打开前的默认帧率
            "width": frame_width,
            "height": frame_height,
        }
        self.error: str | None = None   # None 表示当前无错误（摄像头在线）

    def run(self) -> None:
        """拉流主循环：打开 → 读帧 → 断流重连。"""
        source = self._normalize_source(self.source)

        while not self.stop_event.is_set():
            cap = _open_video_capture(source)
            try:
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, self.camera_buffer_size)
                except Exception:
                    pass    # 部分后端不支持此属性，静默忽略

                if not cap.isOpened():
                    self.error = f"{self.camera_name} 无法打开视频源: {self.source}"
                    time.sleep(self.reconnect_seconds)
                    continue

                # 读取流元数据，供主循环计算实际 fps
                fps = cap.get(cv2.CAP_PROP_FPS)
                width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                self.meta["fps"] = fps if fps and fps > 1 else 12.0
                self.meta["width"] = int(width or self.frame_width)
                self.meta["height"] = int(height or self.frame_height)
                self.error = None   # 成功打开，清除错误状态

                fail_count = 0
                while not self.stop_event.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        fail_count += 1
                        if fail_count >= 20:    # 连续 20 次失败，视为流中断
                            break
                        time.sleep(0.05)
                        continue

                    fail_count = 0
                    self.buffer.put(frame)      # 写入最新帧，覆盖上一帧
            finally:
                cap.release()

            if not self.stop_event.is_set():
                self.error = f"{self.camera_name} 视频流中断，正在重连"
                time.sleep(self.reconnect_seconds)

    @staticmethod
    def _normalize_source(source: str):
        """将纯数字字符串转换为整数摄像头索引，其余原样返回。"""
        return int(source) if str(source).isdigit() else source


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class SingleCameraResult:
    """单路摄像头一帧处理的完整输出，由 _process_one_camera() 返回。

    Attributes:
        camera_id:       摄像头标识。
        annotated_frame: 已叠加检测框、标签、状态头部的标注帧。
        all_persons:     本帧检测到的所有人体目标。
        guard_persons:   经制服识别（含保持窗口）确认为保安的子集。
        phones:          本帧检测到的手机目标（已去重）。
        vehicles:        本帧检测到的车辆目标（轿车/两轮车等）。
        pose_features:   各 track_id 对应的姿态特征字典。
        local_decisions: 单路摄像头的行为规则判断结果。
        guard_present:   本帧是否有保安在场（guard_persons 非空）。
        guard_confidence:所有保安目标中制服识别置信度的最大值。
        camera_online:   摄像头当前是否在线（读取线程无错误）。
        vehicle_guard_seen: 当前车辆周期内是否已见保安靠近车辆。
    """
    camera_id: str
    annotated_frame: np.ndarray
    all_persons: List[Detection]
    guard_persons: List[Detection]
    phones: List[Detection]
    vehicles: List[Detection]
    pose_features: Dict[int, Dict[str, float]]
    local_decisions: Dict[str, RuleDecision]
    guard_present: bool
    guard_confidence: float
    camera_online: bool
    vehicle_guard_seen: bool = False


# ---------------------------------------------------------------------------
# 辅助类：保安识别平滑 & 制服识别缓存
# ---------------------------------------------------------------------------

class TrackGuardGate:
    """逐目标的保安识别结果保持器（同 guard_gate.py 中的 GuardGate）。

    单帧制服识别可能因遮挡产生漏识别；通过 hold_seconds 窗口将
    正识别结果在时间轴上平滑，避免"保安在画面内但间歇被判为非保安"。
    """

    def __init__(self, hold_seconds: float = 1.0):
        self.hold_seconds = hold_seconds
        self.last_positive_ts: Dict[int, float] = {}   # track_id → 最近一次正识别时间戳

    def keep(self, track_id: int | None, timestamp_s: float, is_guard_now: bool) -> bool:
        """查询目标当前是否应视为保安（含保持窗口）。

        track_id 为 None 时直接透传本帧结果，不做跨帧平滑。
        """
        if track_id is None:
            return is_guard_now

        if is_guard_now:
            self.last_positive_ts[track_id] = timestamp_s
            return True

        last_ts = self.last_positive_ts.get(track_id, -1e9)    # 未见过则视为无穷久前
        return (timestamp_s - last_ts) <= self.hold_seconds


class UniformCache:
    """制服识别结果的 TTL 缓存，避免对同一目标每帧重复推理。

    制服识别（UniformClassifier.predict_person）需要裁图并通过分类模型推理，
    相对耗时；同一 track_id 在 ttl 秒内的结果复用上次推理结论，显著降低 CPU 开销。

    缓存键：(camera_id, track_id)，区分不同摄像头的同号目标。
    容量保护：超过 200 条时清理 3×TTL 之前的过期条目，防止内存无限增长。
    """

    def __init__(self, ttl_seconds: float = 1):
        self.ttl = ttl_seconds
        self._cache: dict[tuple[str, int], tuple[float, bool, float]] = {}  # key → (ts, is_guard, conf)
        self._lock = threading.Lock()

    def get_or_infer(
        self,
        camera_id: str,
        track_id: int | None,
        timestamp_s: float,
        classifier: UniformClassifier,
        frame: np.ndarray,
        bbox: tuple[int, int, int, int],
    ) -> tuple[bool, float]:
        """返回制服识别结果 (is_guard, confidence)，命中缓存则跳过推理。

        track_id 为 None 时（目标无跟踪 ID）不使用缓存，直接推理。
        """
        if track_id is not None:
            key = (camera_id, track_id)
            with self._lock:
                cached = self._cache.get(key)
                if cached and (timestamp_s - cached[0]) < self.ttl:
                    return cached[1], cached[2]     # 缓存命中，直接返回

        is_guard, conf = classifier.predict_person(frame, bbox)

        if track_id is not None:
            with self._lock:
                self._cache[(camera_id, track_id)] = (timestamp_s, is_guard, conf)
                # 容量保护：超过 200 条时清理 3×TTL 之前的过期条目
                if len(self._cache) > 200:
                    expired = [
                        k for k, v in self._cache.items()
                        if (timestamp_s - v[0]) > self.ttl * 3
                    ]
                    for k in expired:
                        self._cache.pop(k, None)

        return is_guard, conf


# ---------------------------------------------------------------------------
# 主运行时
# ---------------------------------------------------------------------------

class GuardRoomRuntime:
    """系统核心运行时，管理完整的检测-分析-报警流水线。

    生命周期：
        runtime.start() → 后台 _run_loop 线程启动 → runtime.stop() → 优雅退出

    外部接口：
        start() / stop()         —— 控制运行状态
        is_running               —— 查询运行状态

    内部关键状态：
        _alarm_latches   —— 报警锁存字典，防止同一行为触发期间重复调用 AlarmManager
        _banner_alarm    —— 当前显示在画面顶部的最新报警事件
        _banner_expire_ts —— 横幅过期时间戳，超过后清除横幅显示
    """

    def __init__(
        self,
        config: AppConfig,
        state: AppState,
        *,
        wechat_notifier: WeChatNotifier | None = None,
        alarm_user: str = "",
        alarm_camera_name: str = "值班室双摄像头",
    ):
        """
        Args:
            config:           应用全局配置。
            state:            共享状态对象，供 Web API 读取最新帧与报警信息。
            wechat_notifier:  企业微信推送器；None 时跳过推送。
            alarm_user:       报警推送的接收人账号。
            alarm_camera_name:推送消息中显示的摄像头名称。
        """
        self.cfg = config
        self.state = state
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # 报警横幅：显示最近一次报警，持续 _banner_show_seconds 秒后自动消失
        self._alarm_latches: dict[str, bool] = {}
        self._banner_alarm = None
        self._banner_expire_ts: float = 0.0
        self._banner_show_seconds: float = 1.0

        self.wechat_notifier = wechat_notifier
        self.alarm_user = alarm_user
        self.alarm_camera_name = alarm_camera_name

        self.alarm_clip_recorder = AlarmClipRecorder(
            output_dir=Path(self.cfg.video.output_dir) / "alarm_clips",
            fps=self.cfg.video.annotated_video_fps,
            clip_seconds=self.cfg.wechat.clip_seconds,
        )
        self.vehicle_episode_recorder = VehicleEpisodeRecorder(
            output_dir=Path(self.cfg.video.output_dir) / "vehicle_clips",
            fps=self.cfg.video.annotated_video_fps,
        )

        self.uniform_cache = UniformCache(ttl_seconds=0.1)  # 0.1s TTL：约 1~2 帧复用
        self._camera_pool: ThreadPoolExecutor | None = None
        self._pose_lock = threading.Lock()

    # -----------------------------------------------------------------------
    # 公开接口
    # -----------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """返回主循环线程是否存活。"""
        return self._thread is not None and self._thread.is_alive()

    def _use_half(self) -> bool:
        """CUDA 推理时启用 FP16，CPU 下保持 FP32。"""
        device = str(getattr(self.cfg.models, "device", "") or "").strip().lower()
        return bool(self.cfg.models.use_half and device != "cpu" and torch.cuda.is_available())

    def _cleanup_alarm_media(self, alarm_manager: AlarmManager, *, now: float) -> None:
        """执行一次报警图片/视频清理；失败只记录，不中断检测主循环。"""
        try:
            cleanup_stats = alarm_manager.cleanup_media(
                retention_days=max(
                    1,
                    int(getattr(
                        self.cfg.video,
                        "alarm_media_retention_days",
                        7,
                    )),
                ),
                max_bytes=max(
                    0,
                    int(float(getattr(
                        self.cfg.video,
                        "alarm_media_max_gb",
                        10.0,
                    )) * 1024 ** 3),
                ),
                now=now,
            )
            if (
                cleanup_stats.removed_files
                or cleanup_stats.pruned_events
                or cleanup_stats.failed_files
                or cleanup_stats.skipped_unsafe_paths
            ):
                print(
                    "[GuardRoom] 报警证据清理完成 "
                    f"files={cleanup_stats.removed_files} "
                    f"events={cleanup_stats.pruned_events} "
                    f"freed_mb={cleanup_stats.removed_bytes / 1024 / 1024:.2f} "
                    f"remaining_mb={cleanup_stats.remaining_bytes / 1024 / 1024:.2f} "
                    f"failed={cleanup_stats.failed_files} "
                    f"unsafe={cleanup_stats.skipped_unsafe_paths}",
                    flush=True,
                )
        except Exception as exc:
            print(f"[GuardRoom] 报警证据清理失败: {exc}", flush=True)

    def start(self) -> None:
        """启动主循环线程（幂等：已运行时直接返回）。"""
        with self._lock:
            if self.is_running:
                return
            self._stop_event.clear()
            camera_count = max(1, len(self.cfg.camera_sources()))
            configured_workers = int(getattr(self.cfg.runtime, "infer_max_workers", 1) or 1)
            max_workers = max(1, min(camera_count, configured_workers))
            if self._camera_pool is None:
                self._camera_pool = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix="cam-infer",
                )
            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="guard-room-runtime",
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """通知主循环退出并等待线程结束，之后关闭线程池。"""
        with self._lock:
            self._stop_event.set()
            thread = self._thread

        if thread and thread.is_alive():
            thread.join(timeout=timeout)

        with self._lock:
            self._thread = None
            pool = self._camera_pool
            self._camera_pool = None

        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

        self.state.mark_running(False)

    # -----------------------------------------------------------------------
    # 报警锁存：防止同一行为期间重复触发
    # -----------------------------------------------------------------------

    def _active_alarm_key(self, event_type: str, track_id: int | None) -> str:
        """生成报警锁存键，格式："{event_type}:{track_id|global}"。"""
        return f"{event_type}:{track_id if track_id is not None else 'global'}"

    def _refresh_alarm_latches(self, decisions: dict[str, object]) -> None:
        """根据当前共识结果刷新报警锁存字典。

        锁存语义：行为持续期间 latch=True，行为结束（active=False）后清除锁存，
        下次同类行为触发时可重新报警。
        这样同一次行为期间只打扰 AlarmManager 一次，不会每帧都调用 emit()。
        """
        active_keys = set()

        if getattr(decisions["absent"], "active", False):
            active_keys.add(self._active_alarm_key("absent", None))
        if getattr(decisions["phone"], "active", False):
            active_keys.add(self._active_alarm_key(
                "phone_use",
                getattr(decisions["phone"], "track_id", None),
            ))
        if getattr(decisions["prone_sleep"], "active", False):
            active_keys.add(self._active_alarm_key(
                "prone_sleep",
                getattr(decisions["prone_sleep"], "track_id", None),
            ))
        if getattr(decisions["vehicle_unattended"], "active", False):
            active_keys.add(self._active_alarm_key(
                "vehicle_unattended",
                getattr(decisions["vehicle_unattended"], "track_id", None),
            ))

        # 仅清除已不再 active 的锁存；active 的保持锁定
        for key in list(self._alarm_latches.keys()):
            if key not in active_keys:
                self._alarm_latches.pop(key, None)

    def _emit_alarm_once(
        self,
        alarm_manager: AlarmManager,
        event_type: str,
        frame,
        timestamp_s: float,
        frame_id: int,
        track_id: int | None,
        confidence: float,
        reason: str,
        cooldown_seconds: float = 60.0,
    ):
        """尝试触发一次报警，锁存期内静默跳过（不调用 AlarmManager）。

        两层去重：
          1. 锁存（_alarm_latches）：行为持续期间只触发一次，避免每帧调用；
          2. 冷却（AlarmManager.emit）：同一类型报警在冷却期内不重复推送。

        Args:
            alarm_manager:   报警管理器，负责写快照和持久化。
            event_type:      报警类型字符串。
            frame:           报警触发时的合并画面帧。
            timestamp_s:     当前流时间戳（秒）。
            frame_id:        当前帧序号。
            track_id:        触发目标的 track_id；无具体目标时为 None。
            confidence:      置信度。
            reason:          人类可读原因。
            cooldown_seconds:AlarmManager 的冷却时长（秒）。

        Returns:
            实际触发的 AlarmEvent；锁存或冷却期内返回 None。
        """
        key = self._active_alarm_key(event_type, track_id)
        if self._alarm_latches.get(key, False):
            return None     # 锁存中，静默跳过

        event = alarm_manager.emit(
            event_type,
            frame,
            timestamp_s,
            frame_id,
            track_id,
            confidence,
            reason,
            camera_name=self.alarm_camera_name,
            cooldown_seconds=cooldown_seconds,
        )
        if event is not None:
            # 真实触发：更新共享状态、锁存、横幅
            self.state.add_alarm(event)
            self._alarm_latches[key] = True
            self._banner_alarm = event
            self._banner_expire_ts = timestamp_s + self._banner_show_seconds
        else:
            # 冷却期拦截：同样锁存，防止每帧都穿透到 AlarmManager
            self._alarm_latches[key] = True
        return event

    # -----------------------------------------------------------------------
    # 主循环
    # -----------------------------------------------------------------------

    def _run_loop(self) -> None:
        """主处理循环（在守护线程中运行）。

        流程：
          1. 初始化所有模型和读取线程；
          2. 等待各路摄像头首帧就绪；
          3. 进入帧循环：
             a. 从各路 buffer 取最新帧；
             b. 按 process_every_n_frames 决定是否执行推理；
             c. 并行处理各路摄像头（线程池）；
             d. 多摄共识 → 报警判断 → 视频录制 → 状态更新。
          4. 异常时写入错误状态，finally 中释放所有资源。
        """
        detector_by_camera: Dict[str, YOLO] = {}
        vehicle_detector_by_camera: Dict[str, YOLO] = {}
        detector_phone = None
        pose_estimator_by_camera: Dict[str, PoseEstimator] = {}
        uniform_classifier = None
        out_writer = None
        readers: Dict[str, RTSPReader] = {}

        try:
            self.state.clear_error()
            self.state.set_config(self.cfg)
            self.state.mark_running(True)

            camera_sources = self.cfg.camera_sources()
            if len(camera_sources) < 1:
                raise RuntimeError("请至少配置一路摄像头，当前需要设置 video.source_cam1 或 video.source")

            # 每路摄像头独立的人体检测器，保留各自 ByteTrack 状态。
            detector_by_camera = {
                camera_id: YOLO(self.cfg.models.detector_model)
                for camera_id, _ in camera_sources
            }
            vehicle_model = str(getattr(self.cfg.models, "vehicle_detector_model", "") or "").strip()
            enable_vehicle_unattended = bool(getattr(self.cfg.runtime, "enable_vehicle_unattended", True))
            if enable_vehicle_unattended and vehicle_model:
                vehicle_detector_by_camera = {
                    camera_id: YOLO(vehicle_model)
                    for camera_id, _ in camera_sources
                    if self._vehicle_detection_enabled_for_camera(camera_id)
                }

            phone_mode = str(
                getattr(self.cfg.runtime, "phone_detect_mode", "guard_crop") or "guard_crop"
            ).strip().lower()
            share_phone_detector = bool(getattr(self.cfg.runtime, "share_phone_detector", True))
            detector_phone = None if share_phone_detector else YOLO(self.cfg.models.detector_model)

            uniform_classifier = UniformClassifier(
                model_path=self.cfg.models.uniform_cls_model,
                device=self.cfg.models.device,
                imgsz=self.cfg.models.uniform_cls_imgsz,
                conf_thres=self.cfg.models.uniform_cls_conf,
                use_half=self._use_half(),
            )

            if bool(getattr(self.cfg.runtime, "share_pose_estimator", True)):
                shared_pose_estimator = PoseEstimator(
                    self.cfg.models.pose_model_task,
                    device=self.cfg.models.device,
                    imgsz=self.cfg.models.pose_imgsz,
                    half=self._use_half(),
                )
                pose_estimator_by_camera = {
                    camera_id: shared_pose_estimator
                    for camera_id, _ in camera_sources
                }
            else:
                pose_estimator_by_camera = {
                    camera_id: PoseEstimator(
                        self.cfg.models.pose_model_task,
                        device=self.cfg.models.device,
                        imgsz=self.cfg.models.pose_imgsz,
                        half=self._use_half(),
                    )
                    for camera_id, _ in camera_sources
                }

            # 每路摄像头独立的行为引擎（各自维护跨帧状态，互不干扰）
            behavior_by_camera = {
                camera_id: BehaviorEngine(self.cfg)
                for camera_id, _ in camera_sources
            }
            vehicle_behavior_by_camera = {
                camera_id: VehicleBehaviorEngine(self.cfg)
                for camera_id, _ in camera_sources
            }

            # 每路摄像头独立的保安识别保持器
            guard_gate_by_camera = {
                camera_id: TrackGuardGate(hold_seconds=self.cfg.rules.guard_hold_seconds)
                for camera_id, _ in camera_sources
            }

            consensus = MultiCameraConsensus(
                guard_hold_seconds=self.cfg.rules.guard_hold_seconds,
                absent_alarm_seconds=self.cfg.rules.absent_alarm_seconds,
                behavior_sync_seconds=self.cfg.rules.dual_sync_seconds,
            )

            alarm_manager = AlarmManager(self.cfg.video.output_dir)
            media_cleanup_interval_seconds = max(
                60.0,
                float(getattr(
                    self.cfg.video,
                    "alarm_media_cleanup_interval_minutes",
                    60,
                )) * 60.0,
            )
            cleanup_started_at = time.time()
            self._cleanup_alarm_media(alarm_manager, now=cleanup_started_at)
            next_media_cleanup_at = cleanup_started_at + media_cleanup_interval_seconds

            latest_buffers = {
                camera_id: LatestFrameBuffer()
                for camera_id, _ in camera_sources
            }

            # 启动各路摄像头的拉流线程
            for camera_id, source in camera_sources:
                reader = RTSPReader(
                    camera_name=camera_id,
                    source=source,
                    frame_width=self.cfg.room.frame_width,
                    frame_height=self.cfg.room.frame_height,
                    reconnect_seconds=self.cfg.video.reconnect_seconds,
                    camera_buffer_size=self.cfg.video.camera_buffer_size,
                    buffer=latest_buffers[camera_id],
                    stop_event=self._stop_event,
                )
                readers[camera_id] = reader
                reader.start()

            # 等待各路摄像头首帧，超时则抛异常
            first_frames = {
                camera_id: self._wait_first_frame(latest_buffers[camera_id], readers[camera_id], timeout_s=12.0)
                for camera_id, _ in camera_sources
            }

            combined_first = self._stack_frames([first_frames[camera_id] for camera_id, _ in camera_sources])
            out_writer = self._build_writer(combined_first.shape[1], combined_first.shape[0])

            frame_id = 0
            infer_fps_ema = 0.0     # 推理帧率的指数移动平均（α=0.15）
            last_infer_ts = time.time()
            started_wall_ts = time.time()   # 流时间戳的起点

            processed_ids = {camera_id: -1 for camera_id, _ in camera_sources}

            # 各规则的"未触发"默认值，用于初始化 last_results / last_global_decisions
            false_decisions = {
                "absent": RuleDecision(),
                "phone": RuleDecision(),
                "prone_sleep": RuleDecision(),
                "vehicle_unattended": RuleDecision(),
            }

            # 首帧前的默认结果（确保 combined 帧在首次推理前也有内容可显示）
            last_results = {
                camera_id: SingleCameraResult(
                    camera_id=camera_id,
                    annotated_frame=first_frames[camera_id].copy(),
                    all_persons=[],
                    guard_persons=[],
                    phones=[],
                    vehicles=[],
                    pose_features={},
                    local_decisions=false_decisions,
                    guard_present=False,
                    guard_confidence=0.0,
                    camera_online=True,
                )
                for camera_id, _ in camera_sources
            }
            last_global_decisions = false_decisions

            # ── 帧循环 ────────────────────────────────────────────────────
            while not self._stop_event.is_set():
                wall_now = time.time()
                if wall_now >= next_media_cleanup_at:
                    self._cleanup_alarm_media(alarm_manager, now=wall_now)
                    next_media_cleanup_at = wall_now + media_cleanup_interval_seconds

                buffer_items = {
                    camera_id: latest_buffers[camera_id].get()
                    for camera_id, _ in camera_sources
                }
                current_frames = {
                    camera_id: item[2]
                    for camera_id, item in buffer_items.items()
                }

                # 任意摄像头尚无帧：等待
                if any(frame is None for frame in current_frames.values()):
                    time.sleep(0.02)
                    continue

                # 所有摄像头帧 ID 均未变化：无新帧，跳过
                if all(buffer_items[camera_id][0] == processed_ids[camera_id] for camera_id, _ in camera_sources):
                    time.sleep(0.01)
                    continue

                for camera_id, _ in camera_sources:
                    processed_ids[camera_id] = buffer_items[camera_id][0]
                frame_id += 1

                timestamp_s = time.time() - started_wall_ts

                # 按 process_every_n_frames 决定是否执行推理（跳帧节省算力）
                need_infer = (
                    self.cfg.video.process_every_n_frames <= 1
                    or frame_id % self.cfg.video.process_every_n_frames == 0
                )

                if need_infer:
                    fps_by_camera = {
                        camera_id: max(1.0, float(readers[camera_id].meta.get("fps", 12.0)))
                        for camera_id, _ in camera_sources
                    }

                    precomputed_phone_map: dict[str, List[Detection]] | None = None

                    if phone_mode == "full_frame_test" and detector_phone is not None:
                        # 全图模式：批量推理所有摄像头，避免 N 次独立 predict 调用
                        precomputed_phone_map = self._detect_phones_full_frames_batch(
                            detector=detector_phone,
                            frames_by_camera={camera_id: current_frames[camera_id] for camera_id, _ in camera_sources},
                        )

                    if self._camera_pool is None:
                        raise RuntimeError("camera pool 未初始化")

                    # 各路摄像头并行处理，提交到线程池
                    futures = {
                        camera_id: self._camera_pool.submit(
                            self._process_one_camera,
                            camera_id=camera_id,
                            frame=current_frames[camera_id],
                            timestamp_s=timestamp_s,
                            # 推理有效 fps = 实际 fps / 跳帧数，用于将帧计数转换为时长
                            fps=max(
                                fps_by_camera[camera_id] / max(1, self.cfg.video.process_every_n_frames),
                                1.0,
                            ),
                            main_detector=detector_by_camera[camera_id],
                            vehicle_detector=vehicle_detector_by_camera.get(camera_id),
                            phone_detector=detector_phone,
                            pose_estimator=pose_estimator_by_camera[camera_id],
                            behavior_engine=behavior_by_camera[camera_id],
                            vehicle_behavior_engine=vehicle_behavior_by_camera[camera_id],
                            guard_gate=guard_gate_by_camera[camera_id],
                            uniform_classifier=uniform_classifier,
                            camera_online=(readers[camera_id].error is None),
                            precomputed_phones=None if precomputed_phone_map is None else precomputed_phone_map.get(camera_id),
                        )
                        for camera_id, _ in camera_sources
                    }

                    # 等待所有摄像头推理完成，取结果
                    last_results = {
                        camera_id: future.result()
                        for camera_id, future in futures.items()
                    }

                    vehicle_alarm_videos: dict[str, str] = {}
                    for camera_id, result in last_results.items():
                        if result.vehicle_guard_seen:
                            self.vehicle_episode_recorder.cancel(camera_id)
                        elif result.vehicles:
                            self.vehicle_episode_recorder.update(camera_id, result.annotated_frame)

                        if result.local_decisions["vehicle_unattended"].active:
                            video_path = self.vehicle_episode_recorder.finish(camera_id)
                            if video_path:
                                vehicle_alarm_videos[camera_id] = video_path

                    # 多摄共识：汇聚各路结果，输出全局报警决策
                    last_global_decisions = consensus.update(
                        timestamp_s=timestamp_s,
                        cameras={
                            camera_id: CameraDecisionBundle(
                                camera_id=camera_id,
                                camera_online=result.camera_online,
                                guard_present=result.guard_present,
                                phone=result.local_decisions["phone"],
                                prone_sleep=result.local_decisions["prone_sleep"],
                                vehicle_unattended=result.local_decisions["vehicle_unattended"],
                            )
                            for camera_id, result in last_results.items()
                        },
                    )
                    self._refresh_alarm_latches(last_global_decisions)
                else:
                    vehicle_alarm_videos = {}

                # ── 合并画面 & 全局状态面板 ──────────────────────────────
                ordered_frames = [last_results[camera_id].annotated_frame for camera_id, _ in camera_sources]
                combined = self._stack_frames(ordered_frames)
                self._draw_global_panel(combined, last_global_decisions, timestamp_s)

                # ── 报警触发（三类，各有独立冷却时长）───────────────────
                new_alarm_events = []

                if last_global_decisions["absent"].active:
                    event = self._emit_alarm_once(
                        alarm_manager=alarm_manager,
                        event_type="absent",
                        frame=combined,
                        timestamp_s=timestamp_s,
                        frame_id=frame_id,
                        track_id=None,
                        confidence=last_global_decisions["absent"].confidence,
                        reason=last_global_decisions["absent"].reason,
                        cooldown_seconds=self.cfg.rules.alarm_cooldown_absent,
                    )
                    if event is not None:
                        new_alarm_events.append(event)

                if last_global_decisions["phone"].active:
                    event = self._emit_alarm_once(
                        alarm_manager=alarm_manager,
                        event_type="phone_use",
                        frame=combined,
                        timestamp_s=timestamp_s,
                        frame_id=frame_id,
                        track_id=None,
                        confidence=last_global_decisions["phone"].confidence,
                        reason=last_global_decisions["phone"].reason,
                        cooldown_seconds=self.cfg.rules.alarm_cooldown_phone,
                    )
                    if event is not None:
                        new_alarm_events.append(event)

                if last_global_decisions["prone_sleep"].active:
                    event = self._emit_alarm_once(
                        alarm_manager=alarm_manager,
                        event_type="prone_sleep",
                        frame=combined,
                        timestamp_s=timestamp_s,
                        frame_id=frame_id,
                        track_id=None,
                        confidence=last_global_decisions["prone_sleep"].confidence,
                        reason=last_global_decisions["prone_sleep"].reason,
                        cooldown_seconds=self.cfg.rules.alarm_cooldown_prone_sleep,
                    )
                    if event is not None:
                        new_alarm_events.append(event)

                vehicle_video_events = set()
                for camera_id, vehicle_video_path in vehicle_alarm_videos.items():
                    result = last_results[camera_id]
                    event = self._emit_alarm_once(
                        alarm_manager=alarm_manager,
                        event_type="vehicle_unattended",
                        frame=result.annotated_frame,
                        timestamp_s=timestamp_s,
                        frame_id=frame_id,
                        track_id=None,
                        confidence=result.local_decisions["vehicle_unattended"].confidence,
                        reason=f"{camera_id} {result.local_decisions['vehicle_unattended'].reason}",
                        cooldown_seconds=self.cfg.rules.alarm_cooldown_vehicle_unattended,
                    )
                    if event is not None:
                        vehicle_video_events.add((event.event_type, event.frame_index))
                        if hasattr(alarm_manager, "attach_video"):
                            alarm_manager.attach_video(event, vehicle_video_path)
                        if hasattr(self.state, "attach_alarm_video"):
                            self.state.attach_alarm_video(event.event_type, event.frame_index, vehicle_video_path)
                        if self.wechat_notifier is not None:
                            self.wechat_notifier.notify_alarm(
                                frame=result.annotated_frame,
                                camera_name=f"{self.alarm_camera_name}-{camera_id}",
                                event_name=event.event_type,
                                alarm_user=self.alarm_user,
                                video_path=vehicle_video_path,
                            )
                    else:
                        path = Path(vehicle_video_path)
                        if path.exists():
                            path.unlink()

                # 横幅：仅在 _banner_show_seconds 内显示，之后自动消失
                visible_alarm = self._banner_alarm if timestamp_s <= self._banner_expire_ts else None
                draw_alarm_banner(combined, visible_alarm)

                # ── 启动新报警的视频录制任务 ─────────────────────────────
                for event in new_alarm_events:
                    if (event.event_type, event.frame_index) in vehicle_video_events:
                        continue
                    self.alarm_clip_recorder.start_clip(
                        event=event,
                        frame=combined.copy(),
                        timestamp_s=timestamp_s,
                        camera_name=self.alarm_camera_name,
                        alarm_user=self.alarm_user,
                    )

                # ── 写入标注视频 ──────────────────────────────────────────
                if out_writer is not None:
                    out_writer.write(combined)      # 标注视频（配置开启时）

                # ── 处理已完成的报警视频片段 ─────────────────────────────
                finished_tasks = self.alarm_clip_recorder.update(combined, timestamp_s)
                for task in finished_tasks:
                    # 回写视频路径到 AlarmEvent
                    if hasattr(alarm_manager, "attach_video"):
                        alarm_manager.attach_video(task.event, task.video_path)

                    # 通知 AppState 更新视频路径，供 Web API 查询
                    if hasattr(self.state, "attach_alarm_video"):
                        self.state.attach_alarm_video(
                            task.event.event_type,
                            task.event.frame_index,
                            task.video_path,
                        )

                    # 企业微信推送（按事件类型子开关过滤）
                    if self.wechat_notifier is not None:
                        event_type = task.event.event_type
                        wechat_cfg = self.cfg.wechat
                        enabled = True
                        if event_type == "phone_use" and not wechat_cfg.enable_phone:
                            enabled = False
                        elif event_type == "absent" and not wechat_cfg.enable_absent:
                            enabled = False
                        elif event_type == "prone_sleep" and not wechat_cfg.enable_prone_sleep:
                            enabled = False

                        if enabled:
                            # 用默认参数捕获 task.event 引用，避免闭包捕获循环变量的经典陷阱
                            _event_ref = task.event

                            def _on_wechat_result(success: bool, _event=_event_ref):
                                if not success:
                                    print(f"[ALARM] {_event.event_type} 微信视频推送失败，本地报警视频已保留")
                                else:
                                    print(f"[ALARM] {_event.event_type} 视频推送成功")

                            self.wechat_notifier.notify_alarm(
                                frame=task.snapshot_frame,
                                camera_name=task.camera_name,
                                event_name=task.event.event_type,
                                alarm_user=task.alarm_user,
                                video_path=task.video_path,
                                on_result=_on_wechat_result,
                            )

                # ── FPS 统计（指数移动平均，α=0.15）────────────────────────
                now = time.time()
                instant_fps = 1.0 / max(1e-6, now - last_infer_ts)
                last_infer_ts = now
                infer_fps_ema = instant_fps if infer_fps_ema == 0 else (infer_fps_ema * 0.85 + instant_fps * 0.15)

                # ── 更新 AppState（供 Web API 推流）─────────────────────
                # 重新拼帧并计算各路摄像头检测结果在合并画面中的 Y 偏移
                stacked_frames, y_offsets = self._stack_frames_with_offsets(
                    [last_results[camera_id].annotated_frame for camera_id, _ in camera_sources]
                )
                combined = stacked_frames
                merged_persons: List[Detection] = []
                merged_guards: List[Detection] = []
                merged_phones: List[Detection] = []
                merged_vehicles: List[Detection] = []
                merged_pose_features: Dict[int, Dict[str, float]] = {}

                for idx, (camera_id, _) in enumerate(camera_sources):
                    result = last_results[camera_id]
                    # 将各路坐标平移到合并画面中的实际位置
                    merged_persons.extend(self._offset_detections(result.all_persons, y_offset=y_offsets[idx]))
                    merged_guards.extend(self._offset_detections(result.guard_persons, y_offset=y_offsets[idx]))
                    merged_phones.extend(self._offset_detections(result.phones, y_offset=y_offsets[idx]))
                    merged_vehicles.extend(self._offset_detections(result.vehicles, y_offset=y_offsets[idx]))
                    # track_id 加偏移以区分不同摄像头的同号目标
                    merged_pose_features.update(
                        self._merge_pose_features(result.pose_features, camera_index=idx)
                    )

                if hasattr(self.state, "update_camera_frames"):
                    self.state.update_camera_frames(
                        {
                            camera_id: last_results[camera_id].annotated_frame
                            for camera_id, _ in camera_sources
                        },
                        jpeg_quality=self.cfg.video.jpeg_quality,
                    )

                self.state.update_frame(
                    combined,
                    frame_count=frame_id,
                    fps=infer_fps_ema,
                    timestamp_s=timestamp_s,
                    persons=merged_persons,
                    guards=merged_guards,
                    guard_confidence=max(
                        (result.guard_confidence for result in last_results.values()),
                        default=0.0,
                    ),
                    phones=merged_phones,
                    vehicles=merged_vehicles,
                    pose_features=merged_pose_features,
                    decisions=last_global_decisions,
                    pose_enabled=any(estimator.enabled for estimator in pose_estimator_by_camera.values()),
                    jpeg_quality=self.cfg.video.jpeg_quality,
                )

                # 汇总各路摄像头的错误信息写入共享状态
                warn_msgs = [reader.error for reader in readers.values() if reader.error]
                if warn_msgs:
                    self.state.set_reader_warning(" | ".join(warn_msgs))
                else:
                    self.state.clear_reader_warning()

        except Exception as exc:
            self.state.set_error(str(exc))
        finally:
            # 无论正常退出还是异常，均确保资源被释放
            self.state.mark_running(False)
            self._stop_event.set()
            self.alarm_clip_recorder.close()
            self.vehicle_episode_recorder.close()

            if out_writer is not None:
                out_writer.release()

            closed_pose_estimators = set()
            for pose_estimator in pose_estimator_by_camera.values():
                if id(pose_estimator) in closed_pose_estimators:
                    continue
                closed_pose_estimators.add(id(pose_estimator))
                pose_estimator.close()

            if uniform_classifier is not None and hasattr(uniform_classifier, "close"):
                uniform_classifier.close()

            detector_by_camera.clear()
            vehicle_detector_by_camera.clear()
            detector_phone = None
            uniform_classifier = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            with self._lock:
                pool = self._camera_pool
                self._camera_pool = None
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)

    # -----------------------------------------------------------------------
    # 单路摄像头处理（在线程池中并行执行）
    # -----------------------------------------------------------------------

    def _process_one_camera(
        self,
        *,
        camera_id: str,
        frame: np.ndarray,
        timestamp_s: float,
        fps: float,
        main_detector: YOLO,
        phone_detector: Optional[YOLO],
        vehicle_detector: Optional[YOLO],
        pose_estimator: PoseEstimator,
        behavior_engine: BehaviorEngine,
        vehicle_behavior_engine: VehicleBehaviorEngine,
        guard_gate: TrackGuardGate,
        uniform_classifier: UniformClassifier,
        camera_online: bool,
        precomputed_phones: Optional[List[Detection]] = None,
    ) -> SingleCameraResult:
        """处理单路摄像头的一帧，返回完整的 SingleCameraResult。

        执行顺序：
          1. 人体检测（带跟踪）；
          2. 制服识别（含缓存 + 保持窗口）→ 筛出保安；
          3. 手机检测（裁图模式或全图模式）；
          4. 车辆检测；
          5. 姿态估计；
          6. 行为规则判断；
          7. 标注帧绘制。

        此方法由线程池调用，使用的所有对象（detector / behavior_engine 等）
        均为当前摄像头专属，无跨线程共享，无需加锁。
        uniform_cache 内部自行加锁（多摄共享同一 cache 实例）。
        """
        main_detections = self._detect_main(main_detector, frame)
        all_persons = [d for d in main_detections if d.cls_id == self.cfg.classes.person]

        guard_persons: List[Detection] = []
        guard_confidence = 0.0

        for person in all_persons:
            is_guard_now, uniform_conf = self.uniform_cache.get_or_infer(
                camera_id=camera_id,
                track_id=person.track_id,
                timestamp_s=timestamp_s,
                classifier=uniform_classifier,
                frame=frame,
                bbox=person.bbox,
            )

            if person.track_id is None:
                # 无跟踪 ID：无法使用 guard_gate 平滑，直接用本帧结果
                if is_guard_now:
                    guard_persons.append(person)
                    guard_confidence = max(guard_confidence, uniform_conf)
                continue

            # 有跟踪 ID：通过 guard_gate 平滑识别结果
            keep_guard = guard_gate.keep(person.track_id, timestamp_s, is_guard_now)
            if keep_guard:
                guard_persons.append(person)
                guard_confidence = max(guard_confidence, uniform_conf)

        # 手机检测：根据 phone_detect_mode 选择裁图或全图策略
        phone_mode = str(
            getattr(self.cfg.runtime, "phone_detect_mode", "guard_crop") or "guard_crop"
        ).strip().lower()

        if phone_mode == "full_frame_test":
            # 全图模式：使用主循环预计算的全图结果（批量推理更高效）
            detector_for_phone = phone_detector or main_detector
            phones = precomputed_phones if precomputed_phones is not None else self._detect_phones_full_frame(detector_for_phone, frame)
            persons_for_phone_rule = all_persons   # 全图模式对所有人做手机规则
        else:
            # 裁图模式（默认）：仅对保安区域裁图检测，减少误检
            phones = self._detect_phones_in_person_regions(phone_detector or main_detector, frame, guard_persons)
            persons_for_phone_rule = guard_persons  # 裁图模式只对保安做手机规则

        vehicles = self._detect_vehicles(vehicle_detector, frame) if vehicle_detector is not None else []
        vehicles = self._filter_vehicles_by_roi(vehicles, frame.shape)
        pose_features = self._estimate_pose(pose_estimator, frame, guard_persons, timestamp_s)

        local_decisions = behavior_engine.update(
            timestamp_s=timestamp_s,
            fps=fps,
            frame_shape=frame.shape,
            persons=persons_for_phone_rule,
            phones=phones,
            pose_features=pose_features,
        )
        local_decisions["vehicle_unattended"] = vehicle_behavior_engine.update(
            timestamp_s=timestamp_s,
            frame_shape=frame.shape,
            guards=guard_persons,
            vehicles=vehicles,
        )

        annotated = frame.copy()
        self._draw_camera(
            annotated,
            camera_id=camera_id,
            all_persons=all_persons,
            guard_persons=guard_persons,
            phones=phones,
            vehicles=vehicles,
            pose_features=pose_features,
            guard_confidence=guard_confidence,
            local_decisions=local_decisions,
            camera_online=camera_online,
        )

        return SingleCameraResult(
            camera_id=camera_id,
            annotated_frame=annotated,
            all_persons=all_persons,
            guard_persons=guard_persons,
            phones=phones,
            vehicles=vehicles,
            pose_features=pose_features,
            local_decisions=local_decisions,
            guard_present=len(guard_persons) > 0,
            guard_confidence=guard_confidence,
            camera_online=camera_online,
            vehicle_guard_seen=vehicle_behavior_engine.episode.guard_seen_near_vehicle,
        )

    # -----------------------------------------------------------------------
    # 检测辅助方法
    # -----------------------------------------------------------------------

    def _detect_main(self, detector: YOLO, frame: np.ndarray) -> List[Detection]:
        """对单帧执行带跟踪的人体检测，返回 Detection 列表。

        使用 detector.track() 而非 predict()，以获得跨帧稳定的 track_id，
        供 guard_gate 和 behavior_engine 做时序状态管理。
        置信度下限取 max(0.20, config) 以避免配置过高导致漏检。
        """
        results = detector.track(
            source=frame,
            persist=True,
            tracker=self.cfg.models.tracker,
            classes=[self.cfg.classes.person],
            conf=max(0.20, self.cfg.models.detector_conf),
            iou=self.cfg.models.detector_iou,
            imgsz=self.cfg.models.detector_imgsz,
            device=(self.cfg.models.device or None),
            verbose=False,
            **yolo_precision_kwargs(self._use_half()),
        )

        boxes = results[0].boxes
        detections: List[Detection] = []
        if boxes is None:
            return detections

        xyxy = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
        confs = boxes.conf.cpu().numpy() if boxes.conf is not None else []
        clss = boxes.cls.cpu().numpy().astype(int) if boxes.cls is not None else []
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else None

        for idx, bbox in enumerate(xyxy):
            track_id = int(ids[idx]) if ids is not None else None
            detections.append(
                Detection(
                    cls_id=int(clss[idx]),
                    conf=float(confs[idx]),
                    bbox=tuple(map(int, bbox.tolist())),
                    track_id=track_id,
                )
            )
        return detections

    def _detect_phones_in_person_regions(
        self,
        detector: YOLO,
        frame: np.ndarray,
        persons: List[Detection],
    ) -> List[Detection]:
        """裁图模式手机检测：对每个保安区域裁图，批量推理后坐标还原到全图。

        裁图策略：
          - 水平方向：人体框两侧各扩展 35%，容纳手持手机时手臂外伸的情况；
          - 垂直方向：顶部扩展 20%，底部扩展 15%，覆盖弯腰或低头场景；
          - 坐标钳位在画面范围内，防止越界。

        误检过滤（平板电脑/书本等大面积物体）：
          满足以下任一条件则视为平板误检并丢弃：
            - 检测框面积 > 人体面积的 12%；
            - 检测框宽度 > 人体宽度的 38%；
            - 检测框高度 > 人体高度的 30%；
            - 面积 > 8% 且长宽比在 [0.55, 1.8]（接近正方形的大框）。

        最后调用 _dedup_overlaps() 去除 IoU > 0.5 的重复检测。
        """
        if not persons:
            return []

        h, w = frame.shape[:2]
        crops: List[np.ndarray] = []
        crop_meta: List[dict] = []

        for person in persons:
            px1, py1, px2, py2 = person.bbox
            person_w = max(1, px2 - px1)
            person_h = max(1, py2 - py1)

            pad_x = int(person_w * 0.35)
            pad_top = int(person_h * 0.20)
            pad_bottom = int(person_h * 0.15)

            x1 = max(0, px1 - pad_x)
            y1 = max(0, py1 - pad_top)
            x2 = min(w, px2 + pad_x)
            y2 = min(h, py2 + pad_bottom)

            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            crops.append(crop)
            crop_meta.append({
                "offset": (x1, y1),    # 裁图左上角在全图中的坐标，用于还原检测框
                "person_w": person_w,
                "person_h": person_h,
                "person_area": person_w * person_h,
            })

        if not crops:
            return []

        # 批量推理所有裁图，比逐个 predict 减少 GPU 调度开销
        results = detector.predict(
            source=crops,
            classes=[self.cfg.classes.play_phone],
            conf=min(0.9, max(0.05, self.cfg.models.phone_conf)),
            iou=self.cfg.models.detector_iou,
            imgsz=self.cfg.models.phone_crop_imgsz,
            device=(self.cfg.models.device or None),
            verbose=False,
            **yolo_precision_kwargs(self._use_half()),
        )

        detections: List[Detection] = []

        for result, meta in zip(results, crop_meta):
            boxes = result.boxes
            if boxes is None:
                continue

            xyxy = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
            confs = boxes.conf.cpu().numpy() if boxes.conf is not None else []

            ox, oy = meta["offset"]
            person_w = meta["person_w"]
            person_h = meta["person_h"]
            person_area = meta["person_area"]

            for idx, bbox in enumerate(xyxy):
                cx1, cy1, cx2, cy2 = map(int, bbox.tolist())
                bw = max(1, cx2 - cx1)
                bh = max(1, cy2 - cy1)
                area = bw * bh
                aspect = bw / max(1, bh)

                # 坐标还原：裁图内坐标 + 裁图偏移 = 全图坐标
                gx1, gy1, gx2, gy2 = cx1 + ox, cy1 + oy, cx2 + ox, cy2 + oy

                area_ratio = area / max(1, person_area)
                width_ratio = bw / max(1, person_w)
                height_ratio = bh / max(1, person_h)

                # 平板/书本误检过滤：满足任一大尺寸条件则丢弃
                suspected_tablet = (
                    area_ratio > 0.12
                    or width_ratio > 0.38
                    or height_ratio > 0.30
                    or (area_ratio > 0.08 and 0.55 <= aspect <= 1.8)
                )
                if suspected_tablet:
                    continue

                detections.append(
                    Detection(
                        cls_id=self.cfg.classes.play_phone,
                        conf=float(confs[idx]),
                        bbox=(gx1, gy1, gx2, gy2),
                        track_id=None,      # 手机不做跨帧跟踪
                    )
                )

        return self._dedup_overlaps(detections)

    def _detect_phones_full_frames_batch(
        self,
        detector: YOLO,
        frames_by_camera: Dict[str, np.ndarray],
    ) -> Dict[str, List[Detection]]:
        """全图批量手机检测（调试模式），一次 predict 处理所有摄像头帧。

        与裁图模式相比误检率更高，主要用于验证模型在全图下的检测能力，
        不建议在生产环境使用（phone_detect_mode="full_frame_test"）。
        phone_full_frame_imgsz 可适当调高以检测画面中较小的手机目标，
        但会明显增加瞬时显存。
        """
        if not frames_by_camera:
            return {}

        camera_ids = list(frames_by_camera.keys())
        frames = [frames_by_camera[cid] for cid in camera_ids]

        results = detector.predict(
            source=frames,
            classes=[self.cfg.classes.play_phone],
            conf=min(0.9, max(0.05, self.cfg.models.phone_conf)),
            iou=self.cfg.models.detector_iou,
            imgsz=self.cfg.models.phone_full_frame_imgsz,
            device=(self.cfg.models.device or None),
            verbose=False,
            **yolo_precision_kwargs(self._use_half()),
        )

        out: Dict[str, List[Detection]] = {}
        for cid, frame, result in zip(camera_ids, frames, results):
            detections: List[Detection] = []
            boxes = result.boxes
            if boxes is not None:
                xyxy = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
                confs = boxes.conf.cpu().numpy() if boxes.conf is not None else []

                h, w = frame.shape[:2]
                for idx, bbox in enumerate(xyxy):
                    x1, y1, x2, y2 = map(int, bbox.tolist())
                    # 坐标钳位：防止浮点精度或 letterbox 导致越界
                    x1 = max(0, min(x1, w - 1))
                    y1 = max(0, min(y1, h - 1))
                    x2 = max(0, min(x2, w - 1))
                    y2 = max(0, min(y2, h - 1))

                    if x2 <= x1 or y2 <= y1:
                        continue    # 钳位后退化为零面积框，丢弃

                    detections.append(
                        Detection(
                            cls_id=self.cfg.classes.play_phone,
                            conf=float(confs[idx]),
                            bbox=(x1, y1, x2, y2),
                            track_id=None,
                        )
                    )

            out[cid] = self._dedup_overlaps(detections)

        return out

    def _detect_phones_full_frame(
        self,
        detector: YOLO,
        frame: np.ndarray,
    ) -> List[Detection]:
        """对单帧执行全图手机检测（_detect_phones_full_frames_batch 的单帧便捷封装）。"""
        result = self._detect_phones_full_frames_batch(
            detector=detector,
            frames_by_camera={"single": frame},
        )
        return result.get("single", [])

    def _detect_vehicles(
        self,
        detector: YOLO,
        frame: np.ndarray,
    ) -> List[Detection]:
        """使用 YOLO11/COCO 车辆模型检测轿车和两轮车。"""
        vehicle_classes = [
            self.cfg.classes.vehicle_bicycle,
            self.cfg.classes.vehicle_car,
            self.cfg.classes.vehicle_motorcycle,
        ]
        result = detector.predict(
            source=frame,
            classes=vehicle_classes,
            conf=min(0.9, max(0.05, self.cfg.models.vehicle_conf)),
            iou=self.cfg.models.detector_iou,
            imgsz=self.cfg.models.vehicle_imgsz,
            device=(self.cfg.models.device or None),
            verbose=False,
            **yolo_precision_kwargs(self._use_half()),
        )[0]

        boxes = result.boxes
        detections: List[Detection] = []
        if boxes is None:
            return detections

        xyxy = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
        confs = boxes.conf.cpu().numpy() if boxes.conf is not None else []
        clss = boxes.cls.cpu().numpy().astype(int) if boxes.cls is not None else []

        h, w = frame.shape[:2]
        for idx, bbox in enumerate(xyxy):
            cls_id = int(clss[idx])
            if cls_id not in vehicle_classes:
                continue
            x1, y1, x2, y2 = map(int, bbox.tolist())
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(0, min(x2, w - 1))
            y2 = max(0, min(y2, h - 1))
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append(
                Detection(
                    cls_id=cls_id,
                    conf=float(confs[idx]),
                    bbox=(x1, y1, x2, y2),
                    track_id=None,
                )
            )

        return self._dedup_overlaps(detections)

    def _vehicle_detection_enabled_for_camera(self, camera_id: str) -> bool:
        """车辆检测仅在配置的单路摄像头上运行。"""
        configured = str(getattr(self.cfg.runtime, "vehicle_camera_id", "cam1") or "cam1").strip()
        return camera_id == configured

    def _filter_vehicles_by_roi(
        self,
        vehicles: List[Detection],
        frame_shape: tuple[int, int, int],
    ) -> List[Detection]:
        """仅保留车辆检测 ROI 内的车辆；未配置 ROI 时不过滤。"""
        polygon = self._vehicle_roi_pixels(frame_shape)
        if len(polygon) < 3:
            return vehicles

        filtered: List[Detection] = []
        for vehicle in vehicles:
            x1, y1, x2, y2 = vehicle.bbox
            probe = ((x1 + x2) / 2.0, float(y2))
            if self._point_in_polygon(probe, polygon):
                filtered.append(vehicle)
        return filtered

    def _vehicle_roi_pixels(self, frame_shape: tuple[int, int, int]) -> list[tuple[int, int]]:
        """将归一化车辆 ROI 转换为像素坐标。"""
        roi = getattr(self.cfg.rules, "vehicle_roi", []) or []
        if len(roi) < 3:
            return []

        h, w = frame_shape[:2]
        points: list[tuple[int, int]] = []
        for point in roi:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                continue
            x_raw, y_raw = float(point[0]), float(point[1])
            if 0.0 <= x_raw <= 1.0 and 0.0 <= y_raw <= 1.0:
                x = int(round(x_raw * w))
                y = int(round(y_raw * h))
            else:
                x = int(round(x_raw))
                y = int(round(y_raw))
            points.append((max(0, min(x, w - 1)), max(0, min(y, h - 1))))
        return points if len(points) >= 3 else []

    @staticmethod
    def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[int, int]]) -> bool:
        """射线法判断点是否在多边形内。"""
        x, y = point
        inside = False
        j = len(polygon) - 1
        for i, (xi, yi) in enumerate(polygon):
            xj, yj = polygon[j]
            intersects = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / max(1e-9, yj - yi) + xi
            )
            if intersects:
                inside = not inside
            j = i
        return inside

    def _estimate_pose(
        self,
        pose_estimator: PoseEstimator,
        frame: np.ndarray,
        persons: List[Detection],
        timestamp_s: float,
    ) -> Dict[int, Dict[str, float]]:
        """调用姿态估计器（未启用时返回空字典）。

        仅对 guard_persons 做姿态估计（而非 all_persons），
        减少不必要的关键点匹配计算。
        """
        if not pose_estimator.enabled:
            return {}
        if bool(getattr(self.cfg.runtime, "share_pose_estimator", True)):
            with self._pose_lock:
                return pose_estimator.infer_frame(frame, persons)
        return pose_estimator.infer_frame(frame, persons)

    # -----------------------------------------------------------------------
    # 画面标注方法
    # -----------------------------------------------------------------------

    def _draw_camera(
        self,
        frame: np.ndarray,
        *,
        camera_id: str,
        all_persons: List[Detection],
        guard_persons: List[Detection],
        phones: List[Detection],
        vehicles: List[Detection],
        pose_features: Dict[int, Dict[str, float]],
        guard_confidence: float,
        local_decisions: Dict[str, RuleDecision],
        camera_online: bool,
    ) -> None:
        """在单路摄像头帧上绘制检测框、姿态信息和状态头部栏。

        绘制层次（从下到上）：
          1. 所有人体框（灰色）；
          2. 保安框（绿色，含低头比率 hd=...）；
          3. 手机框（品红色）；
          4. 顶部状态头部栏（在线=绿底，离线=红底）。
        """
        # 所有人体：灰色框，区分于保安
        for det in all_persons:
            draw_detection(frame, det, f"person id={det.track_id}", color=(128, 128, 128))

        # 保安：绿色框，附加低头比率供调试
        for det in guard_persons:
            label = f"guard id={det.track_id}"
            if (
                det.track_id is not None
                and det.track_id in pose_features
                and "head_down_ratio" in pose_features[det.track_id]
            ):
                label += f" hd={pose_features[det.track_id]['head_down_ratio']:.2f}"
            draw_detection(frame, det, label, color=(0, 255, 0))

        for det in phones:
            draw_detection(frame, det, f"phone {det.conf:.2f}", color=(255, 0, 255))

        for det in vehicles:
            draw_detection(frame, det, f"vehicle {det.conf:.2f}", color=(0, 165, 255))

        vehicle_roi = self._vehicle_roi_pixels(frame.shape) if self._vehicle_detection_enabled_for_camera(camera_id) else []
        if vehicle_roi:
            draw_polygon(frame, vehicle_roi, "vehicle_roi")

        # 顶部状态栏：在线绿底，离线红底，一眼区分摄像头状态
        header_bg = (0, 120, 0) if camera_online else (0, 0, 180)
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 34), header_bg, -1)
        header = (
            f"{camera_id} | online={camera_online} | "
            f"guards={len(guard_persons)} | guard_conf={guard_confidence:.2f} | "
            f"phone={local_decisions['phone'].active} | prone={local_decisions['prone_sleep'].active} | "
            f"vehicle={local_decisions['vehicle_unattended'].active}"
        )
        cv2.putText(frame, header, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)

    def _draw_global_panel(
        self,
        frame: np.ndarray,
        decisions: Dict[str, RuleDecision],
        timestamp_s: float,
    ) -> None:
        """在合并画面底部绘制全局共识状态文字条。"""
        text = (
            f"GLOBAL | t={timestamp_s:.1f}s | "
            f"absent={decisions['absent'].active} | "
            f"phone={decisions['phone'].active} | "
            f"prone={decisions['prone_sleep'].active} | "
            f"vehicle={decisions['vehicle_unattended'].active}"
        )
        y = frame.shape[0] - 14     # 固定在画面底部上方 14 像素
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (0, 180, 255), 2)

    # -----------------------------------------------------------------------
    # 静态工具方法
    # -----------------------------------------------------------------------

    @staticmethod
    def _dedup_overlaps(dets: List[Detection], iou_threshold: float = 0.5) -> List[Detection]:
        """贪心 NMS：按置信度降序保留，IoU 超阈值的后续框丢弃。

        用于去除裁图/全图检测中来自不同裁图区域的重叠手机框。
        """
        if not dets:
            return []

        dets = sorted(dets, key=lambda d: d.conf, reverse=True)
        kept: List[Detection] = []

        for det in dets:
            keep = True
            for old in kept:
                if GuardRoomRuntime._iou(det.bbox, old.bbox) >= iou_threshold:
                    keep = False
                    break
            if keep:
                kept.append(det)
        return kept

    @staticmethod
    def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        """计算两个检测框的 IoU，无交集时返回 0.0。"""
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
            return 0.0
        inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
        area_a = max(1, ax2 - ax1) * max(1, ay2 - ay1)
        area_b = max(1, bx2 - bx1) * max(1, by2 - by1)
        return inter / float(area_a + area_b - inter)

    @staticmethod
    def _resize_to_width(frame: np.ndarray, target_w: int) -> np.ndarray:
        """等比缩放帧到指定宽度，已是目标宽度时原样返回。"""
        h, w = frame.shape[:2]
        if w == target_w:
            return frame
        scale = target_w / max(1, w)
        new_h = max(1, int(round(h * scale)))
        return cv2.resize(frame, (target_w, new_h))

    def _stack_frames(self, frames: List[np.ndarray]) -> np.ndarray:
        """垂直拼接多路帧（不需要偏移量时的便捷封装）。"""
        combined, _ = self._stack_frames_with_offsets(frames)
        return combined

    def _stack_frames_with_offsets(self, frames: List[np.ndarray]) -> tuple[np.ndarray, List[int]]:
        """垂直拼接多路帧，返回合并帧与各路帧在合并帧中的 Y 轴起始偏移。

        所有帧先统一缩放到最小宽度，再垂直拼接，确保等宽。
        y_offsets 用于将各路摄像头的检测框坐标映射到合并帧中的正确位置。

        Returns:
            (combined_frame, y_offsets)，y_offsets[i] 为第 i 路帧顶部的 Y 坐标。
        """
        if not frames:
            raise RuntimeError("没有可拼接的画面")

        target_w = min(frame.shape[1] for frame in frames)     # 以最小宽度为基准
        resized_frames = [self._resize_to_width(frame, target_w) for frame in frames]

        y_offsets: List[int] = []
        current_y = 0
        for frame in resized_frames:
            y_offsets.append(current_y)
            current_y += frame.shape[0]

        return np.vstack(resized_frames), y_offsets

    @staticmethod
    def _offset_detections(dets: List[Detection], y_offset: int = 0) -> List[Detection]:
        """将检测框的 Y 坐标整体平移 y_offset，用于映射到合并画面坐标系。"""
        out: List[Detection] = []
        for d in dets:
            x1, y1, x2, y2 = d.bbox
            out.append(
                Detection(
                    cls_id=d.cls_id,
                    conf=d.conf,
                    bbox=(x1, y1 + y_offset, x2, y2 + y_offset),
                    track_id=d.track_id,
                )
            )
        return out

    @staticmethod
    def _merge_pose_features(
        pose_features: Dict[int, Dict[str, float]],
        camera_index: int,
    ) -> Dict[int, Dict[str, float]]:
        """将姿态特征的 track_id 加上摄像头索引偏移（× 100000），避免多路 ID 冲突。

        例：cam1 的 track_id=5 → 5，cam2 的 track_id=5 → 100005，互不覆盖。
        """
        base = camera_index * 100000
        return {
            int(track_id) + base: value
            for track_id, value in pose_features.items()
        }

    def _wait_first_frame(
        self,
        buffer: LatestFrameBuffer,
        reader: RTSPReader,
        timeout_s: float = 12.0,
    ) -> np.ndarray:
        """阻塞等待摄像头首帧，超时则抛出 RuntimeError。

        超时时优先使用 reader.error 中的具体错误信息，便于定位问题（URL 错误、网络不通等）。
        """
        deadline = time.time() + timeout_s
        while not self._stop_event.is_set() and time.time() < deadline:
            _, _, frame = buffer.get()
            if frame is not None:
                return frame
            time.sleep(0.1)
        raise RuntimeError(reader.error or f"{reader.camera_name} 首帧超时: {reader.source}")

    def _build_writer(self, width: int, height: int):
        """根据配置创建标注视频的 VideoWriter；save_annotated_video=False 时返回 None。"""
        if not self.cfg.video.save_annotated_video:
            return None
        output_dir = ensure_dir(self.cfg.video.output_dir)
        out_path = output_dir / "annotated.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        return cv2.VideoWriter(
            str(out_path),
            fourcc,
            self.cfg.video.annotated_video_fps,
            (width, height),
        )
