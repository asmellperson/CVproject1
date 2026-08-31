# 文件说明：实现状态管理相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# state.py
"""
应用共享状态模块。

AppState 是系统的"黑板"（Blackboard），在运行时（GuardRoomRuntime）和
Web 服务（server.py）之间充当线程安全的数据中转站：

    运行时（写）                    Web API（读）
    update_frame()   ──────────▶  get_latest_frame() / get_status()
    add_alarm()      ──────────▶  get_alarms() / get_alarm()
    mark_running()   ──────────▶  get_status()

设计决策：
    - 使用 RLock（可重入锁）而非 Lock，允许同一线程在持锁时调用其他加锁方法；
    - 报警列表使用 deque(maxlen=...)，超出上限时自动丢弃最旧记录，防止内存无限增长；
    - 统计结果带缓存（_stats_cache），避免每次请求都遍历全量报警（当前预留，未启用）；
    - 占位帧（_build_placeholder）确保系统启动前推流接口也能返回有效 JPEG，不返回空响应。
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from .config import AppConfig
from .types import AlarmEvent, Detection


# 功能：运行时与 Web API 之间的线程安全共享状态容器；输入与输出详见下方说明
# 参数：
#   - `cfg`（AppConfig）：运行配置对象
#   - `config_path`（str | Path）：`config_path` 对应的业务输入值
# 返回：AppState；返回新建的 `AppState` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的
#         `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的
#         `test_status_reports_guards_separately_from_all_detected_people` 实例化本符号；`AiVision/integrations/guard_room/src/server.py` 的
#         `create_app` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AppState:
    """运行时与 Web API 之间的线程安全共享状态容器。

    所有公开方法均通过 RLock 保证线程安全，调用方无需外部加锁。
    """

    # 功能：cfg:         初始应用配置，后续可通过 set_config() 热替换；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `cfg`（AppConfig）：运行配置对象
    #   - `config_path`（str | Path）：`config_path` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`threading.RLock`、`str`、`self._build_placeholder`、`', '.join`、`cfg.camera_sources`、`deque`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(self, cfg: AppConfig, config_path: str | Path):
        """
        Args:
            cfg:         初始应用配置，后续可通过 set_config() 热替换。
            config_path: 配置文件路径，更新配置时需回写此文件。
        """
        self._lock = threading.RLock()  # RLock：允许同一线程嵌套加锁（如 get_status 调用内部方法）

        # ── 配置 ──────────────────────────────────────────────────────────
        self.config = cfg
        self.config_path = str(config_path)

        # ── 推流 ──────────────────────────────────────────────────────────
        # 初始化为占位帧，确保流媒体接口在首帧到来前也能返回有效 JPEG
        self.latest_jpeg: bytes = self._build_placeholder("Waiting for stream")
        self.camera_jpegs: dict[str, bytes] = {}
        self.last_update_ts: Optional[float] = None     # 最近一次帧更新的 wall clock 时间戳

        # ── 运行状态 ──────────────────────────────────────────────────────
        self.running = False
        self.started_at: Optional[float] = None         # 本次启动的 wall clock 时间戳，用于计算 uptime
        self.error: Optional[str] = None                # 运行时异常信息；None 表示正常
        self.reader_warning: Optional[str] = None       # 摄像头读取警告（不影响运行，但需提示）
        self.frame_count = 0
        self.fps = 0.0
        self.pose_enabled = False
        self.source = ", ".join(source for _, source in cfg.camera_sources())

        # ── 报警 ──────────────────────────────────────────────────────────
        self.last_alarm: Optional[dict[str, Any]] = None   # 最近一条报警，供状态接口快速返回
        # maxlen 限制内存：超出后自动丢弃最旧记录
        self.alarms: deque[dict[str, Any]] = deque(maxlen=cfg.runtime.max_alarm_history)

        # ── 检测结果（最近一帧）──────────────────────────────────────────
        self.latest_detections: dict[str, Any] = {
            "persons": [],
            "guards": [],
            "phones": [],
            "vehicles": [],
            "pose_features": {},
            "decisions": {
                "absent": False,
                "phone_use": False,
                "prone_sleep": False,
                "vehicle_unattended": False,
            },
            "metrics": {
                "person_confidence": 0.0,
                "guard_confidence": 0.0,
                "phone_confidence": 0.0,
                "vehicle_confidence": 0.0,
                "head_down_ratio": 0.0,
            },
            "counts": {"persons": 0, "guards": 0, "phones": 0, "vehicles": 0},
        }

        # ── 统计缓存（预留，当前未启用 TTL 逻辑）────────────────────────
        self._stats_cache: Optional[dict] = None
        self._stats_cache_ts: float = 0.0

    # -----------------------------------------------------------------------
    # 配置管理
    # -----------------------------------------------------------------------

    # 功能：替换当前配置对象（配置热更新时调用）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `cfg`（AppConfig）：运行配置对象
    #   - `config_path`（str | Path | None）：`config_path` 对应的业务输入值；默认值为 `None`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop`
    #         调用本符号；`AiVision/integrations/guard_room/src/server.py` 的 `create_app::update_config` 调用本符号
    #   - 内部调用：`', '.join`、`cfg.camera_sources`、`str`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def set_config(self, cfg: AppConfig, config_path: str | Path | None = None) -> None:
        """替换当前配置对象（配置热更新时调用）。

        同步更新 source 字段，确保状态接口返回的摄像头源与新配置一致。

        Args:
            cfg:         新的配置对象。
            config_path: 新的配置文件路径；None 表示路径不变。
        """
        with self._lock:
            self.config = cfg
            self.source = ", ".join(source for _, source in cfg.camera_sources())
            if config_path is not None:
                self.config_path = str(config_path)

    # -----------------------------------------------------------------------
    # 运行状态管理
    # -----------------------------------------------------------------------

    # 功能：标记系统运行/停止状态；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `running`（bool）：`running` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的 `FakeRuntime::start`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的 `FakeRuntime::stop`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::stop`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：`time.time`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def mark_running(self, running: bool) -> None:
        """标记系统运行/停止状态。

        启动时记录起始时间并清除旧错误；停止时清除起始时间。
        """
        with self._lock:
            self.running = running
            if running:
                self.started_at = time.time()
                self.error = None   # 新一轮启动，清除上次错误
            else:
                self.started_at = None

    # 功能：记录运行时异常，同时将 running 置为 False；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `message`（str）：用于展示、记录或发送的文本消息
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def set_error(self, message: str) -> None:
        """记录运行时异常，同时将 running 置为 False。

        由 _run_loop 的 except 块调用；异常后系统不再处于运行状态。
        """
        with self._lock:
            self.error = message
            self.running = False

    # 功能：清除错误信息，通常在新一轮启动前调用；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def clear_error(self) -> None:
        """清除错误信息，通常在新一轮启动前调用。"""
        with self._lock:
            self.error = None

    # 功能：设置摄像头读取警告（如流中断、重连中）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `message`（str）：用于展示、记录或发送的文本消息
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def set_reader_warning(self, message: str) -> None:
        """设置摄像头读取警告（如流中断、重连中）。

        警告不影响系统运行状态，但应在状态接口中暴露给前端。
        """
        with self._lock:
            self.reader_warning = message

    # 功能：清除摄像头读取警告（摄像头恢复正常后调用）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def clear_reader_warning(self) -> None:
        """清除摄像头读取警告（摄像头恢复正常后调用）。"""
        with self._lock:
            self.reader_warning = None

    # -----------------------------------------------------------------------
    # 帧与检测结果更新
    # -----------------------------------------------------------------------

    # 功能：将最新标注帧及检测结果写入共享状态，供推流和状态接口读取；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame_bgr`（np.ndarray）：`frame_bgr` 对应的业务输入值
    #   - `frame_count`（int）：`frame_count` 对应的数量或大小
    #   - `fps`（float）：`fps` 对应的业务输入值
    #   - `timestamp_s`（float）：以秒表示的流时间戳
    #   - `persons`（list[Detection]）：`persons` 对应的业务输入值
    #   - `guards`（list[Detection] | None）：`guards` 对应的业务输入值；默认值为 `None`
    #   - `guard_confidence`（float）：`guard_confidence` 对应的业务输入值；默认值为 `0.0`
    #   - `phones`（list[Detection]）：`phones` 对应的业务输入值
    #   - `pose_features`（dict[int, dict[str, float]]）：`pose_features` 对应的业务输入值
    #   - `decisions`（dict[str, Any]）：`decisions` 对应的业务输入值
    #   - `pose_enabled`（bool）：`pose_enabled` 对应的业务输入值
    #   - `jpeg_quality`（int）：`jpeg_quality` 对应的业务输入值；默认值为 `80`
    #   - `vehicles`（list[Detection] | None）：`vehicles` 对应的业务输入值；默认值为 `None`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的
    #         `test_status_reports_guards_separately_from_all_detected_people`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：`cv2.imencode`、`int`、`max`、`float`、`v.get`、`pose_features.values`、`encoded.tobytes`、`bool`、`time.time`、`self._det_to_dict`
    #          等共 16 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def update_frame(
        self,
        frame_bgr: np.ndarray,
        *,
        frame_count: int,
        fps: float,
        timestamp_s: float,
        persons: list[Detection],
        guards: list[Detection] | None = None,
        guard_confidence: float = 0.0,
        phones: list[Detection],
        pose_features: dict[int, dict[str, float]],
        decisions: dict[str, Any],
        pose_enabled: bool,
        jpeg_quality: int = 80,
        vehicles: list[Detection] | None = None,
    ) -> None:
        """将最新标注帧及检测结果写入共享状态，供推流和状态接口读取。

        JPEG 编码在加锁前完成，减少持锁时间（编码可能耗时数毫秒）。
        编码失败时静默返回，不覆盖上一帧，确保推流接口始终有内容。

        Args:
            frame_bgr:    已标注的合并 BGR 帧。
            frame_count:  当前帧序号。
            fps:          推理帧率的指数移动平均值。
            timestamp_s:  当前流时间戳（秒，从系统启动计）。
            persons:      本帧所有人体检测结果（合并多路坐标后）。
            guards:       经制服识别确认为保安的人体检测结果。
            guard_confidence: 本帧保安制服识别置信度最大值。
            phones:       本帧手机检测结果。
            vehicles:     本帧车辆检测结果。
            pose_features:各 track_id 的姿态特征字典。
            decisions:    多摄共识后的全局行为判断结果。
            pose_enabled: 姿态估计器是否已启用。
            jpeg_quality: JPEG 压缩质量（1~100）。
        """
        # 编码在锁外执行，避免长时间阻塞其他读取操作
        ok, encoded = cv2.imencode(
            ".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)]
        )
        if not ok:
            return  # 编码失败，保留上一帧，不中断推流

        guards = guards or []
        vehicles = vehicles or []

        # 汇总置信度指标，取各类目标中的最大值
        metrics = {
            "person_confidence": max((float(d.conf) for d in persons), default=0.0),
            "guard_confidence": float(guard_confidence),
            "phone_confidence": max((float(d.conf) for d in phones), default=0.0),
            "vehicle_confidence": max((float(d.conf) for d in vehicles), default=0.0),
            "head_down_ratio": max(
                (float(v.get("head_down_ratio", 0.0)) for v in pose_features.values()),
                default=0.0,
            ),
        }

        with self._lock:
            self.latest_jpeg = encoded.tobytes()
            self.frame_count = frame_count
            self.fps = float(fps)
            self.pose_enabled = bool(pose_enabled)
            self.last_update_ts = time.time()   # MJPEG 推流以此字段判断是否有新帧
            self.latest_detections = {
                "persons": [self._det_to_dict(d) for d in persons],
                "guards": [self._det_to_dict(d) for d in guards],
                "phones": [self._det_to_dict(d) for d in phones],
                "vehicles": [self._det_to_dict(d) for d in vehicles],
                "pose_features": {str(k): v for k, v in pose_features.items()},
                "decisions": {
                    # 将 RuleDecision 对象展开为布尔值，便于 JSON 序列化
                    "absent":      bool(getattr(decisions.get("absent"),      "active", False)),
                    "phone_use":   bool(getattr(decisions.get("phone"),       "active", False)),
                    "prone_sleep": bool(getattr(decisions.get("prone_sleep"), "active", False)),
                    "vehicle_unattended": bool(getattr(decisions.get("vehicle_unattended"), "active", False)),
                },
                "metrics": metrics,
                "counts": {
                    "persons": len(persons),
                    "guards": len(guards),
                    "phones": len(phones),
                    "vehicles": len(vehicles),
                },
                "stream_time_s": round(timestamp_s, 2),
            }

    # 功能：保存每路摄像头的最新单路 JPEG 帧，供配置页按摄像头绘制 ROI；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frames_by_camera`（dict[str, np.ndarray]）：`frames_by_camera` 对应的业务输入值
    #   - `jpeg_quality`（int）：`jpeg_quality` 对应的业务输入值；默认值为 `80`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：`frames_by_camera.items`、`cv2.imencode`、`int`、`str`、`encoded.tobytes`、`self.camera_jpegs.update`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_camera_frames(
        self,
        frames_by_camera: dict[str, np.ndarray],
        *,
        jpeg_quality: int = 80,
    ) -> None:
        """保存每路摄像头的最新单路 JPEG 帧，供配置页按摄像头绘制 ROI。"""
        encoded_frames: dict[str, bytes] = {}
        for camera_id, frame_bgr in frames_by_camera.items():
            ok, encoded = cv2.imencode(
                ".jpg",
                frame_bgr,
                [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)],
            )
            if ok:
                encoded_frames[str(camera_id)] = encoded.tobytes()

        if not encoded_frames:
            return

        with self._lock:
            self.camera_jpegs.update(encoded_frames)

    # -----------------------------------------------------------------------
    # 报警管理
    # -----------------------------------------------------------------------

    # 功能：将 AlarmEvent 转换为字典并追加到报警队列；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `alarm`（AlarmEvent）：`alarm` 对应的业务输入值
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`asdict`、`uuid.uuid4`、`datetime.now().isoformat`、`datetime.now`、`self.alarms.appendleft`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def add_alarm(self, alarm: AlarmEvent) -> dict[str, Any]:
        """将 AlarmEvent 转换为字典并追加到报警队列。

        自动注入唯一 ID（12 位 hex）和创建时间，返回完整的报警字典
        供调用方（GuardRoomRuntime）进一步处理（如启动视频录制）。

        Args:
            alarm: 由 AlarmManager.emit() 返回的报警事件对象。

        Returns:
            包含 id / created_at 的完整报警字典。
        """
        payload = asdict(alarm)
        payload["id"] = uuid.uuid4().hex[:12]   # 12 位短 ID，够用且不冗长
        payload["created_at"] = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self.last_alarm = payload
            self.alarms.appendleft(payload)     # 最新记录放队列头部，便于 get_alarms 直接截取
        return payload

    # 功能：将录制完成的视频路径回写到对应报警记录，更新状态为 "ready"；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event_type`（str）：事件类型标识
    #   - `frame_index`（int）：视频流中的帧序号
    #   - `video_path`（str）：`video_path` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：`self.last_alarm.get`、`item.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def attach_alarm_video(self, event_type: str, frame_index: int, video_path: str) -> None:
        """将录制完成的视频路径回写到对应报警记录，更新状态为 "ready"。

        同时更新 last_alarm 和 alarms 队列中的记录，保证两者一致。
        通过 (event_type, frame_index) 组合定位记录，而非 alarm_id，
        因为调用方（AlarmClipRecorder）只持有 AlarmEvent，不持有 alarm_id。
        """
        with self._lock:
            # 优先更新 last_alarm（快速路径，大多数情况下刚触发的就是 last_alarm）
            if (
                self.last_alarm
                and self.last_alarm.get("event_type") == event_type
                and self.last_alarm.get("frame_index") == frame_index
            ):
                self.last_alarm["video_path"] = video_path
                self.last_alarm["video_status"] = "ready"

            # 同步更新队列中的记录（last_alarm 是队列中某条记录的引用，两者可能已同步，但显式更新更安全）
            for item in self.alarms:
                if item.get("event_type") == event_type and item.get("frame_index") == frame_index:
                    item["video_path"] = video_path
                    item["video_status"] = "ready"
                    break

    # 功能：将对应报警的视频状态标记为 "failed"；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event_type`（str）：事件类型标识
    #   - `frame_index`（int）：视频流中的帧序号
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.last_alarm.get`、`item.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def mark_alarm_video_failed(self, event_type: str, frame_index: int) -> None:
        """将对应报警的视频状态标记为 "failed"。

        当视频录制或上传出现不可恢复错误时调用，
        供前端区分"录制中"（pending）与"录制失败"（failed）两种状态。
        """
        with self._lock:
            if (
                self.last_alarm
                and self.last_alarm.get("event_type") == event_type
                and self.last_alarm.get("frame_index") == frame_index
            ):
                self.last_alarm["video_status"] = "failed"

            for item in self.alarms:
                if (
                    item.get("event_type") == event_type
                    and item.get("frame_index") == frame_index
                ):
                    item["video_status"] = "failed"
                    break

    # -----------------------------------------------------------------------
    # 数据读取（Web API 调用）
    # -----------------------------------------------------------------------

    # 功能：返回系统完整状态快照，供 /api/status 接口使用；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`max`、`time.time`、`round`、`datetime.now().isoformat`、`datetime.now`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_status(self) -> dict[str, Any]:
        """返回系统完整状态快照，供 /api/status 接口使用。

        将 uptime、帧信息、最新检测结果、最近报警等合并为单一字典，
        减少前端轮询时的请求次数。
        """
        with self._lock:
            uptime = (
                0.0
                if not self.running or self.started_at is None
                else max(0.0, time.time() - self.started_at)
            )
            return {
                "running": self.running,
                "fps": round(self.fps, 2),
                "frame_count": self.frame_count,
                "pose_enabled": self.pose_enabled,
                "source": self.source,
                "error": self.error,
                "reader_warning": self.reader_warning,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "uptime_sec": round(uptime, 1),
                "last_alarm": self.last_alarm,
                "stream_url": "/api/stream.mjpg",
                "frame_url": "/api/frame.jpg",
                **self.latest_detections,   # 展开检测结果到顶层，方便前端直接访问
            }

    # 功能：返回当前配置的完整字典表示（线程安全）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/server.py` 的 `create_app::get_config`
    #         调用本符号；`AiVision/integrations/guard_room/src/server.py` 的 `create_app::update_config` 调用本符号
    #   - 内部调用：`self.config.to_dict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_config_dict(self) -> dict[str, Any]:
        """返回当前配置的完整字典表示（线程安全）。"""
        with self._lock:
            return self.config.to_dict()

    # 功能：返回最新帧的 JPEG 二进制数据（线程安全）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bytes；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_latest_frame(self) -> bytes:
        """返回最新帧的 JPEG 二进制数据（线程安全）。

        系统未启动时返回占位帧，确保推流接口始终有内容。
        """
        with self._lock:
            return self.latest_jpeg

    # 功能：返回指定摄像头最新单路 JPEG；尚无画面时返回该摄像头占位帧；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：bytes；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`str(camera_id or '').strip`、`str`、`self.camera_jpegs.get`、`self._build_placeholder`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera_frame(self, camera_id: str) -> bytes:
        """返回指定摄像头最新单路 JPEG；尚无画面时返回该摄像头占位帧。"""
        key = str(camera_id or "").strip()
        with self._lock:
            frame = self.camera_jpegs.get(key)
        return frame if frame is not None else self._build_placeholder(f"Waiting for {key or 'camera'}")

    # 功能：返回最近 limit 条报警记录（最新在前）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `limit`（int）：返回或处理的最大记录数；默认值为 `50`
    # 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/state.py` 的 `AppState::get_statistics` 调用本符号
    #   - 内部调用：`list`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_alarms(self, limit: int = 50) -> list[dict[str, Any]]:
        """返回最近 limit 条报警记录（最新在前）。"""
        with self._lock:
            return list(self.alarms)[:limit]

    # 功能：按 alarm_id 查找单条报警记录，不存在时返回 None；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `alarm_id`（str）：`alarm_id` 对应业务对象的唯一标识
    # 返回：Optional[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_alarm(self, alarm_id: str) -> Optional[dict[str, Any]]:
        """按 alarm_id 查找单条报警记录，不存在时返回 None。"""
        with self._lock:
            for item in self.alarms:
                if item["id"] == alarm_id:
                    return item
        return None     # 遍历完未找到，返回 None（在锁外返回也安全，None 是不可变对象）

    # 功能：计算并返回报警统计数据，供图表展示使用；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.get_alarms`、`datetime.now`、`len`、`sum`、`range`、`(now -
    #          timedelta(days=i)).date`、`timedelta`、`datetime.fromisoformat`、`created_at.date`、`now.date` 等共 12 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_statistics(self) -> dict[str, Any]:
        """计算并返回报警统计数据，供图表展示使用。

        统计维度：
            summary  —— 各类报警总数、今日数、近 7 日数；
            hourly   —— 按小时分布（0~23 时，各类数量）；
            weekly   —— 按近 7 天分布（中文星期 + 各类数量）；
            pie      —— 饼图数据（各类报警占比，含颜色）。

        当前每次调用均实时计算（最多遍历 1000 条），
        _stats_cache 字段预留给后续 TTL 缓存优化。
        """
        alarms = self.get_alarms(limit=1000)    # 统计最近 1000 条，平衡精度与性能
        now = datetime.now()

        summary = {
            "total":       len(alarms),
            "absent":      sum(1 for a in alarms if a["event_type"] == "absent"),
            "phone_use":   sum(1 for a in alarms if a["event_type"] == "phone_use"),
            "prone_sleep": sum(1 for a in alarms if a["event_type"] == "prone_sleep"),
            "vehicle_unattended": sum(1 for a in alarms if a["event_type"] == "vehicle_unattended"),
            "today": 0,
            "week": 0,
        }

        # 时段分布：按小时（0~23）分桶
        hourly_map = {h: {"absent": 0, "phone": 0, "prone_sleep": 0, "vehicle_unattended": 0} for h in range(24)}

        # 近 7 天分布：从 6 天前到今天，升序排列
        weekly_keys = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]
        weekly_map = {d: {"absent": 0, "phone": 0, "prone_sleep": 0, "vehicle_unattended": 0} for d in weekly_keys}
        weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        for alarm in alarms:
            created_at = datetime.fromisoformat(alarm["created_at"])
            if created_at.date() == now.date():
                summary["today"] += 1
            if created_at >= now - timedelta(days=7):
                summary["week"] += 1

            # phone_use → phone：统一桶名（与 hourly/weekly 的键对齐）
            bucket_key = "phone" if alarm["event_type"] == "phone_use" else alarm["event_type"]
            if bucket_key not in hourly_map[created_at.hour]:
                continue
            hourly_map[created_at.hour][bucket_key] += 1
            if created_at.date() in weekly_map:
                weekly_map[created_at.date()][bucket_key] += 1

        hourly = [{"time": f"{hour:02d}:00", **vals} for hour, vals in hourly_map.items()]
        weekly = [{"day": weekday_cn[d.weekday()], **weekly_map[d]} for d in weekly_keys]

        # 饼图数据：含前端渲染所需的颜色值
        pie = [
            {"name": "离岗",   "value": summary["absent"],      "color": "#ef4444"},
            {"name": "玩手机", "value": summary["phone_use"],   "color": "#f97316"},
            {"name": "趴睡",   "value": summary["prone_sleep"], "color": "#eab308"},
            {"name": "车辆无人值守", "value": summary["vehicle_unattended"], "color": "#06b6d4"},
        ]

        return {"summary": summary, "hourly": hourly, "weekly": weekly, "pie": pie}

    # -----------------------------------------------------------------------
    # 静态辅助方法
    # -----------------------------------------------------------------------

    # 功能：将 Detection 对象序列化为 JSON 兼容字典；输入与输出详见下方说明
    # 参数：
    #   - `det`（Detection）：`det` 对应的业务输入值
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/state.py` 的 `AppState::update_frame` 调用本符号
    #   - 内部调用：`float`、`list`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _det_to_dict(det: Detection) -> dict[str, Any]:
        """将 Detection 对象序列化为 JSON 兼容字典。

        bbox 转为 list（而非 tuple），确保 JSON 序列化不报错。
        """
        return {
            "cls_id":   det.cls_id,
            "conf":     float(det.conf),
            "bbox":     list(det.bbox),
            "track_id": det.track_id,
        }

    # 功能：生成带文字提示的深色占位帧（1280×720 JPEG）；输入与输出详见下方说明
    # 参数：
    #   - `text`（str）：`text` 对应的业务输入值
    # 返回：bytes；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/state.py` 的 `AppState::__init__`
    #         调用本符号；`AiVision/integrations/guard_room/src/state.py` 的 `AppState::get_camera_frame` 调用本符号
    #   - 内部调用：`np.zeros`、`cv2.putText`、`cv2.imencode`、`encoded.tobytes`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _build_placeholder(text: str) -> bytes:
        """生成带文字提示的深色占位帧（1280×720 JPEG）。

        系统启动前推流接口返回此帧，避免前端收到空响应或报错。
        背景色 (17, 24, 39) 与前端深色主题保持视觉一致。
        """
        canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
        canvas[:] = (17, 24, 39)    # 深色背景，RGB 近似 #111827
        cv2.putText(canvas, text, (90, 360), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 4)
        ok, encoded = cv2.imencode(".jpg", canvas)
        return encoded.tobytes() if ok else b""
