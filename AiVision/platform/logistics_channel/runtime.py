# 文件说明：实现运行时相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""四个物流单人检测模块共用的通道级运行时。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from threading import Event, Lock, RLock, Thread
import time
from typing import Callable

import numpy as np

from AiVision.core.alarm.dispatcher import AlarmRequest, alarm_dispatcher
from AiVision.core.logger import logger
from AiVision.core.settings import settings
from AiVision.features import all_specs
from AiVision.platform.camera.config_manager import camera_config_manager

from .compositor import CameraTile, compose_channel_frame
from .constants import LOGISTICS_FEATURES, require_logistics_feature
from .service import logistics_channel_service
from .state import CameraSnapshot, ChannelDecision, ChannelPresenceState, classify_channel


# 功能：定义 `_CameraInfo` 类，封装运行时相关的状态、约束与操作
# 参数：
#   - `camera_id`（int）：摄像头唯一标识
#   - `name`（str）：业务对象名称
#   - `shm_name`（str）：摄像头共享内存名称
# 返回：_CameraInfo；返回新建的 `_CameraInfo` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_parse_channel` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _CameraInfo:
    camera_id: int
    name: str
    shm_name: str


# 功能：定义 `_ChannelConfig` 类，封装运行时相关的状态、约束与操作
# 参数：
#   - `feature_name`（str）：`feature_name` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `name`（str）：业务对象名称
#   - `enabled`（bool）：是否启用相应能力
#   - `detection_start`（object）：`detection_start` 对应的业务输入值
#   - `detection_end`（object）：`detection_end` 对应的业务输入值
#   - `confidence_threshold`（float）：`confidence_threshold` 对应的业务输入值
#   - `empty_grace_seconds`（float）：`empty_grace_seconds` 对应的时间间隔或时长
#   - `multi_grace_seconds`（float）：`multi_grace_seconds` 对应的时间间隔或时长
#   - `alarm_interval`（float）：`alarm_interval` 对应的时间间隔或时长
#   - `alarm`（dict）：`alarm` 对应的业务输入值
#   - `cameras`（tuple[_CameraInfo, ...]）：`cameras` 对应的业务输入值
# 返回：_ChannelConfig；返回新建的 `_ChannelConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_parse_channel` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _ChannelConfig:
    feature_name: str
    channel_id: int
    name: str
    enabled: bool
    detection_start: object
    detection_end: object
    confidence_threshold: float
    empty_grace_seconds: float
    multi_grace_seconds: float
    alarm_interval: float
    alarm: dict
    cameras: tuple[_CameraInfo, ...]


# 功能：定义 `_ChannelView` 类，封装运行时相关的状态、约束与操作
# 参数：
#   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
#   - `generation`（int）：`generation` 对应的业务输入值
#   - `snapshots`（tuple[CameraSnapshot | None, ...]）：`snapshots` 对应的业务输入值
#   - `frames`（tuple[np.ndarray | None, ...]）：`frames` 对应的业务输入值
# 返回：_ChannelView；返回新建的 `_ChannelView` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_snapshot_channel` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _ChannelView:
    channel: _ChannelConfig
    generation: int
    snapshots: tuple[CameraSnapshot | None, ...]
    frames: tuple[np.ndarray | None, ...]


# 功能：定义 `_PreparedView` 类，封装运行时相关的状态、约束与操作
# 参数：
#   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
#   - `generation`（int）：`generation` 对应的业务输入值
#   - `snapshots`（tuple[CameraSnapshot, ...]）：`snapshots` 对应的业务输入值
#   - `states`（dict[str, dict]）：`states` 对应的业务输入值
#   - `tiles`（tuple[CameraTile, ...]）：`tiles` 对应的业务输入值
#   - `active`（bool）：`active` 对应的业务输入值
# 返回：_PreparedView；返回新建的 `_PreparedView` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_prepare_view` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _PreparedView:
    channel: _ChannelConfig
    generation: int
    snapshots: tuple[CameraSnapshot, ...]
    states: dict[str, dict]
    tiles: tuple[CameraTile, ...]
    active: bool


# 功能：定义 `_IncidentWork` 类，封装运行时相关的状态、约束与操作
# 参数：
#   - `key`（tuple[str, int]）：用于查询、分组或缓存的键
#   - `generation`（int）：`generation` 对应的业务输入值
#   - `token`（int）：用于认证或续接请求的令牌
#   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
#   - `decision`（ChannelDecision）：`decision` 对应的业务输入值
#   - `states`（dict[str, dict]）：`states` 对应的业务输入值
#   - `tiles`（tuple[CameraTile, ...]）：`tiles` 对应的业务输入值
#   - `evaluated_at`（float）：`evaluated_at` 对应的业务输入值
# 返回：_IncidentWork；返回新建的 `_IncidentWork` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_transition` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _IncidentWork:
    key: tuple[str, int]
    generation: int
    token: int
    channel: _ChannelConfig
    decision: ChannelDecision
    states: dict[str, dict]
    tiles: tuple[CameraTile, ...]
    evaluated_at: float


# 功能：聚合逐路快照、维护通道计时并统一分发通道告警；输入与输出详见下方说明
# 参数：
#   - `channel_service`（未显式标注）：`channel_service` 对应的业务输入值；默认值为 `logistics_channel_service`
#   - `dispatcher`（未显式标注）：`dispatcher` 对应的业务输入值；默认值为 `alarm_dispatcher`
#   - `camera_provider`（Callable[[int], dict | None] | None）：`camera_provider` 对应的业务输入值；默认值为 `None`
#   - `is_camera_active`（Callable[[str], bool] | None）：`is_camera_active` 对应的业务输入值；默认值为 `None`
#   - `frame_provider`（Callable[[str], np.ndarray | None] | None）：`frame_provider` 对应的业务输入值；默认值为 `None`
#   - `stale_seconds`（float | None）：`stale_seconds` 对应的时间间隔或时长；默认值为 `None`
#   - `wall_time_provider`（Callable[[], datetime] | None）：`wall_time_provider` 对应的业务输入值；默认值为 `None`
#   - `violation_type_provider`（Callable[[str], int] | None）：`violation_type_provider` 对应的业务输入值；默认值为 `None`
#   - `clock_provider`（Callable[[], float] | None）：`clock_provider` 对应的业务输入值；默认值为 `None`
#   - `compositor`（Callable[[tuple[CameraTile, ...]], np.ndarray] | None）：`compositor` 对应的业务输入值；默认值为 `None`
#   - `evidence_recorder`（未显式标注）：`evidence_recorder` 对应的业务输入值；默认值为 `None`
#   - `start_background`（bool）：`start_background` 对应的业务输入值；默认值为 `True`
#   - `stop_timeout_seconds`（float）：`stop_timeout_seconds` 对应的时间间隔或时长；默认值为 `2.0`
# 返回：LogisticsChannelRuntime；返回新建的 `LogisticsChannelRuntime` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的 `build_runtime`
#         实例化本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
#         `test_service_camera_online_compositor_and_dispatcher_run_outside_global_lock` 实例化本符号；`AiVision/platform/orchestrator.py`
#         的 `Orchestrator::__init__` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelRuntime:
    """聚合逐路快照、维护通道计时并统一分发通道告警。"""

    # 功能：初始化或配置 `__init__` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `channel_service`（未显式标注）：`channel_service` 对应的业务输入值；默认值为 `logistics_channel_service`
    #   - `dispatcher`（未显式标注）：`dispatcher` 对应的业务输入值；默认值为 `alarm_dispatcher`
    #   - `camera_provider`（Callable[[int], dict | None] | None）：`camera_provider` 对应的业务输入值；默认值为 `None`
    #   - `is_camera_active`（Callable[[str], bool] | None）：`is_camera_active` 对应的业务输入值；默认值为 `None`
    #   - `frame_provider`（Callable[[str], np.ndarray | None] | None）：`frame_provider` 对应的业务输入值；默认值为 `None`
    #   - `stale_seconds`（float | None）：`stale_seconds` 对应的时间间隔或时长；默认值为 `None`
    #   - `wall_time_provider`（Callable[[], datetime] | None）：`wall_time_provider` 对应的业务输入值；默认值为 `None`
    #   - `violation_type_provider`（Callable[[str], int] | None）：`violation_type_provider` 对应的业务输入值；默认值为 `None`
    #   - `clock_provider`（Callable[[], float] | None）：`clock_provider` 对应的业务输入值；默认值为 `None`
    #   - `compositor`（Callable[[tuple[CameraTile, ...]], np.ndarray] | None）：`compositor` 对应的业务输入值；默认值为 `None`
    #   - `evidence_recorder`（未显式标注）：`evidence_recorder` 对应的业务输入值；默认值为 `None`
    #   - `start_background`（bool）：`start_background` 对应的业务输入值；默认值为 `True`
    #   - `stop_timeout_seconds`（float）：`stop_timeout_seconds` 对应的时间间隔或时长；默认值为 `2.0`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`camera_config_manager.get_camera`、`str`、`float`、`datetime.now().astimezone`、`datetime.now`、`all_specs`、`Event`、`Lock`、`RLock`、`set`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(
        self,
        *,
        channel_service=logistics_channel_service,
        dispatcher=alarm_dispatcher,
        camera_provider: Callable[[int], dict | None] | None = None,
        is_camera_active: Callable[[str], bool] | None = None,
        frame_provider: Callable[[str], np.ndarray | None] | None = None,
        stale_seconds: float | None = None,
        wall_time_provider: Callable[[], datetime] | None = None,
        violation_type_provider: Callable[[str], int] | None = None,
        clock_provider: Callable[[], float] | None = None,
        compositor: Callable[[tuple[CameraTile, ...]], np.ndarray] | None = None,
        evidence_recorder=None,
        start_background: bool = True,
        stop_timeout_seconds: float = 2.0,
    ) -> None:
        self._service = channel_service
        self._dispatcher = dispatcher
        self._camera_provider = camera_provider or (
            lambda camera_id: camera_config_manager.get_camera(str(camera_id))
        )
        self._is_camera_active = is_camera_active or (lambda _shm_name: True)
        self._frame_provider = frame_provider or (lambda _shm_name: None)
        self._stale_seconds = (
            settings.runtime.logistics_status_stale_seconds
            if stale_seconds is None
            else float(stale_seconds)
        )
        self._wall_time_provider = wall_time_provider or (lambda: datetime.now().astimezone())
        self._violation_type_provider = violation_type_provider or (
            lambda feature_name: all_specs()[feature_name].violation_type
        )
        self._clock_provider = clock_provider or time.time
        self._compositor = compositor or compose_channel_frame
        self._evidence_recorder = evidence_recorder
        self._start_background = start_background
        self._stop_timeout_seconds = float(stop_timeout_seconds)
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lifecycle_lock = Lock()
        self._lock = RLock()
        self._snapshots: dict[tuple[str, int], CameraSnapshot] = {}
        self._frames: dict[tuple[str, int], np.ndarray] = {}
        self._channels: dict[tuple[str, int], _ChannelConfig] = {}
        self._camera_channels: dict[tuple[str, int], int] = {}
        self._loaded_features: set[str] = set()
        self._generations: dict[str, int] = {feature: 0 for feature in LOGISTICS_FEATURES}
        self._states: dict[tuple[str, int], ChannelPresenceState] = {}
        self._statuses: dict[tuple[str, int], dict] = {}
        self._channel_frames: dict[tuple[str, int], np.ndarray] = {}
        self._active_incidents: dict[tuple[str, int], str] = {}
        self._pending_incidents: dict[tuple[str, int], tuple[str, int, int]] = {}
        self._next_incident_token = 0
        self._running = False

    # 功能：启动或执行 `start` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`existing.is_alive`、`RuntimeError`、`self._stop_event.clear`、`Thread`、`thread.start`、`self._stop_event.set`、`logger.info`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    def start(self) -> None:
        thread = None
        with self._lifecycle_lock:
            with self._lock:
                existing = self._thread
                if existing is not None and existing.is_alive():
                    if self._running:
                        return
                    raise RuntimeError("物流通道运行时上一巡检线程仍在停止中，禁止重复启动")
                self._thread = None
                if self._running:
                    return
                self._stop_event.clear()
                self._running = True
                if self._start_background:
                    thread = Thread(
                        target=self._evaluation_loop,
                        daemon=True,
                        name="logistics-channel-runtime",
                    )
                    self._thread = thread
            if thread is not None:
                try:
                    thread.start()
                except Exception:
                    with self._lock:
                        self._running = False
                        self._stop_event.set()
                        if self._thread is thread:
                            self._thread = None
                    raise
        logger.info("[LogisticsChannelRuntime] 已启动")

    # 功能：停止并释放 `stop` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.set`、`thread.join`、`thread.is_alive`、`logger.error`、`RuntimeError`、`self._clear_all_state_locked`、`logger.info`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    def stop(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                self._running = False
                self._stop_event.set()
                thread = self._thread
            if thread is not None:
                thread.join(timeout=self._stop_timeout_seconds)
                if thread.is_alive():
                    logger.error("[LogisticsChannelRuntime] 巡检线程停止超时，保留停止状态")
                    raise RuntimeError("物流通道巡检线程停止超时，禁止重新启动")
            with self._lock:
                if self._thread is not thread:
                    raise RuntimeError("物流通道巡检线程引用在停止期间发生变化")
                self._thread = None
                self._clear_all_state_locked()
        logger.info("[LogisticsChannelRuntime] 已停止")

    # 功能：启动或执行 `camera_should_run` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._ensure_feature_loaded`、`self._camera_channels.get`、`self._channels.get`、`self._channel_is_active`、`self._channel_is_current_locked`、`self._reset_non_alarm_locked`、`self._reset_cooldown`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def camera_should_run(self, feature_name: str, camera_id: int) -> bool:
        feature_name = require_logistics_feature(feature_name)
        self._ensure_feature_loaded(feature_name)
        with self._lock:
            channel_id = self._camera_channels.get((feature_name, camera_id))
            channel = self._channels.get((feature_name, channel_id)) if channel_id is not None else None
            generation = self._generations[feature_name]
        if channel is None:
            return False
        active = self._channel_is_active(channel)
        reset_cooldown = False
        if not active:
            with self._lock:
                if self._channel_is_current_locked(channel, generation):
                    reset_cooldown = self._reset_non_alarm_locked(channel, "inactive")
            if reset_cooldown:
                self._reset_cooldown(channel)
        return active

    # 功能：返回摄像头所属通道的人体检测阈值；未绑定通道时返回 None；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：float | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._ensure_feature_loaded`、`self._camera_channels.get`、`self._channels.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def person_confidence_threshold(self, feature_name: str, camera_id: int) -> float | None:
        """返回摄像头所属通道的人体检测阈值；未绑定通道时返回 None。"""
        feature_name = require_logistics_feature(feature_name)
        self._ensure_feature_loaded(feature_name)
        with self._lock:
            channel_id = self._camera_channels.get((feature_name, camera_id))
            channel = self._channels.get((feature_name, channel_id)) if channel_id is not None else None
            return None if channel is None else channel.confidence_threshold

    # 功能：更新或保存 `update_camera_snapshot` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `snapshot`（CameraSnapshot）：`snapshot` 对应的业务输入值
    #   - `annotated_frame`（np.ndarray | None）：`annotated_frame` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`isinstance`、`annotated_frame.copy`、`logger.warning`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def update_camera_snapshot(
        self,
        feature_name: str,
        snapshot: CameraSnapshot,
        annotated_frame: np.ndarray | None,
    ) -> None:
        feature_name = require_logistics_feature(feature_name)
        frame_copy = None
        if isinstance(annotated_frame, np.ndarray) and annotated_frame.size:
            frame_copy = annotated_frame.copy()
        with self._lock:
            running = self._running
            self._snapshots[(feature_name, snapshot.camera_id)] = snapshot
            if frame_copy is not None:
                self._frames[(feature_name, snapshot.camera_id)] = frame_copy
        if not running:
            logger.warning(
                f"[LogisticsChannelRuntime] 未启动时收到快照 "
                f"feature={feature_name} camera_id={snapshot.camera_id}"
            )

    # 功能：更新或保存 `evaluate_after_camera_update` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：ChannelDecision | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._ensure_feature_loaded`、`self._camera_channels.get`、`self.evaluate`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def evaluate_after_camera_update(
        self,
        feature_name: str,
        camera_id: int,
    ) -> ChannelDecision | None:
        feature_name = require_logistics_feature(feature_name)
        self._ensure_feature_loaded(feature_name)
        with self._lock:
            channel_id = self._camera_channels.get((feature_name, camera_id))
        return None if channel_id is None else self.evaluate(feature_name, channel_id)

    # 功能：实现 `evaluate` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `now`（float | None）：`now` 对应的业务输入值；默认值为 `None`
    # 返回：ChannelDecision；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::evaluate_after_camera_update`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_evaluation_loop` 调用本符号
    #   - 内部调用：`require_logistics_feature`、`self._clock_provider`、`float`、`range`、`self._snapshot_channel`、`ChannelDecision`、`self._prepare_view`、`self._evidence_key`、`evidence_recorder.should_sample`、`evidence_recorder.record_frame`
    #          等共 14 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def evaluate(
        self,
        feature_name: str,
        channel_id: int,
        *,
        now: float | None = None,
    ) -> ChannelDecision:
        feature_name = require_logistics_feature(feature_name)
        evaluated_at = self._clock_provider() if now is None else float(now)
        for _attempt in range(3):
            view = self._snapshot_channel(feature_name, channel_id)
            if view is None:
                return ChannelDecision("unconfigured", False, 0.0, None)
            prepared = self._prepare_view(view, evaluated_at)
            evidence_recorder = self._evidence_recorder
            evidence_key = self._evidence_key(prepared.channel)
            if evidence_recorder is not None and evidence_recorder.should_sample(
                evidence_key,
                evaluated_at,
            ):
                evidence_recorder.record_frame(
                    evidence_key,
                    self._compose(prepared.channel, prepared.tiles),
                    evaluated_at,
                )
            transition = self._transition(prepared, evaluated_at)
            if transition is None:
                continue
            decision, work, reset_cooldown = transition
            if reset_cooldown:
                self._reset_cooldown(prepared.channel)
            if work is not None:
                self._execute_incident(work)
            return decision
        return ChannelDecision("unknown", False, 0.0, None)

    # 功能：摄像头信息、ROI 或绑定变化后重新加载所属功能配置；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::refresh_camera_all` 调用本符号
    #   - 内部调用：`require_logistics_feature`、`self._camera_channels.get`、`self._channels.get`、`self._snapshots.pop`、`self._frames.pop`、`self._clear_channel_state_locked`、`self._invalidate_feature_locked`、`self._reset_cooldown`、`self._ensure_feature_loaded`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def refresh_camera(self, feature_name: str, camera_id: int) -> None:
        """摄像头信息、ROI 或绑定变化后重新加载所属功能配置。"""
        feature_name = require_logistics_feature(feature_name)
        reset_channel = None
        with self._lock:
            channel_id = self._camera_channels.get((feature_name, camera_id))
            reset_channel = self._channels.get((feature_name, channel_id)) if channel_id else None
            self._snapshots.pop((feature_name, camera_id), None)
            self._frames.pop((feature_name, camera_id), None)
            if reset_channel is not None:
                self._clear_channel_state_locked(reset_channel)
            self._invalidate_feature_locked(feature_name)
        if reset_channel is not None:
            self._reset_cooldown(reset_channel)
        self._ensure_feature_loaded(feature_name)

    # 功能：全局摄像头改名、运行参数更新或删除后刷新四个物流命名空间；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_camera_rename_and_delete_refresh_real_runtime_membership_cache` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::_handle_runtime_config_change` 调用本符号
    #   - 内部调用：`sorted`、`self.refresh_camera`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def refresh_camera_all(self, camera_id: int) -> None:
        """全局摄像头改名、运行参数更新或删除后刷新四个物流命名空间。"""
        for feature_name in sorted(LOGISTICS_FEATURES):
            self.refresh_camera(feature_name, camera_id)

    # 功能：通道配置或成员事件后丢弃旧快照、计时和证据；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的 `test_refresh_clears_timing_snapshot_and_incident_state`
    #         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_refresh_during_slow_composition_discards_stale_incident_result` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::_handle_runtime_config_change` 调用本符号
    #   - 内部调用：`require_logistics_feature`、`self._channels.get`、`self._snapshots.pop`、`self._frames.pop`、`self._clear_channel_state_locked`、`self._invalidate_feature_locked`、`self._reset_cooldown`、`self._ensure_feature_loaded`、`logger.info`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def refresh_channel(self, feature_name: str, channel_id: int) -> None:
        """通道配置或成员事件后丢弃旧快照、计时和证据。"""
        feature_name = require_logistics_feature(feature_name)
        old = None
        with self._lock:
            old = self._channels.get((feature_name, channel_id))
            if old is not None:
                for camera in old.cameras:
                    self._snapshots.pop((feature_name, camera.camera_id), None)
                    self._frames.pop((feature_name, camera.camera_id), None)
                self._clear_channel_state_locked(old)
            self._invalidate_feature_locked(feature_name)
        if old is not None:
            self._reset_cooldown(old)
        self._ensure_feature_loaded(feature_name)
        logger.info(
            f"[LogisticsChannelRuntime] 已刷新 feature={feature_name} "
            f"channel_id={channel_id}"
        )

    # 功能：读取或查询 `get_channel_status` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._statuses.get`、`self._copy_status`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_channel_status(self, feature_name: str, channel_id: int) -> dict | None:
        feature_name = require_logistics_feature(feature_name)
        with self._lock:
            value = self._statuses.get((feature_name, channel_id))
            return self._copy_status(value)

    # 功能：显式请求时才按最新不可变 tile 快照生成拼接画面；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：np.ndarray | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::get_composite_frame` 调用本符号
    #   - 内部调用：`require_logistics_feature`、`self._snapshot_channel`、`self._prepare_view`、`self._clock_provider`、`self._compose`、`self._channel_is_current_locked`、`frame.copy`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_channel_frame(self, feature_name: str, channel_id: int) -> np.ndarray | None:
        """显式请求时才按最新不可变 tile 快照生成拼接画面。"""
        feature_name = require_logistics_feature(feature_name)
        view = self._snapshot_channel(feature_name, channel_id)
        if view is None:
            return None
        prepared = self._prepare_view(view, self._clock_provider())
        frame = self._compose(prepared.channel, prepared.tiles)
        if frame is None:
            return None
        with self._lock:
            if not self._channel_is_current_locked(prepared.channel, prepared.generation):
                return None
            self._channel_frames[(feature_name, channel_id)] = frame
        return frame.copy()

    # 功能：读取或查询 `get_composite_frame` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：np.ndarray | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_disabled_members_are_excluded_from_aggregation_status_and_composite`
    #         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_inactive_detection_window_still_composes_live_preview_frames`
    #         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_compositor_runs_only_for_alarm_or_explicit_frame_request` 调用本符号
    #   - 内部调用：`self.get_channel_frame`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_composite_frame(self, feature_name: str, channel_id: int) -> np.ndarray | None:
        return self.get_channel_frame(feature_name, channel_id)

    # 功能：实现 `_snapshot_channel` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：_ChannelView | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::evaluate`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::get_channel_frame` 调用本符号
    #   - 内部调用：`self._ensure_feature_loaded`、`self._channels.get`、`tuple`、`self._snapshots.get`、`self._frames.get`、`self._channel_is_active`、`zip`、`self._frame_provider`、`isinstance`、`logger.warning`
    #          等共 13 个调用。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _snapshot_channel(self, feature_name: str, channel_id: int) -> _ChannelView | None:
        self._ensure_feature_loaded(feature_name)
        with self._lock:
            channel = self._channels.get((feature_name, channel_id))
            if channel is None:
                return None
            generation = self._generations[feature_name]
            snapshots = tuple(
                self._snapshots.get((feature_name, camera.camera_id))
                for camera in channel.cameras
            )
            detected_frames = tuple(
                self._frames.get((feature_name, camera.camera_id))
                for camera in channel.cameras
            )

        channel_active = self._channel_is_active(channel)
        frames = []
        for camera, detected_frame in zip(channel.cameras, detected_frames, strict=True):
            frame = detected_frame
            if not channel_active or frame is None:
                try:
                    raw_frame = self._frame_provider(camera.shm_name)
                    if isinstance(raw_frame, np.ndarray) and raw_frame.size:
                        frame = raw_frame
                except Exception as exc:
                    logger.warning(
                        f"[LogisticsChannelRuntime] 摄像头预览帧读取失败 "
                        f"camera_id={camera.camera_id}: {exc}"
                    )
            frames.append(
                frame.copy()
                if isinstance(frame, np.ndarray) and frame.size
                else None
            )
        return _ChannelView(
            channel=channel,
            generation=generation,
            snapshots=snapshots,
            frames=tuple(frames),
        )

    # 功能：实现 `_prepare_view` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `view`（_ChannelView）：`view` 对应的业务输入值
    #   - `now`（float）：`now` 对应的业务输入值
    # 返回：_PreparedView；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::evaluate`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::get_channel_frame` 调用本符号
    #   - 内部调用：`self._channel_is_active`、`zip`、`self._camera_online`、`CameraSnapshot`、`self._camera_reason`、`str`、`snapshots.append`、`tiles.append`、`CameraTile`、`_PreparedView`
    #          等共 11 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _prepare_view(self, view: _ChannelView, now: float) -> _PreparedView:
        active = self._channel_is_active(view.channel)
        snapshots: list[CameraSnapshot] = []
        states: dict[str, dict] = {}
        tiles: list[CameraTile] = []
        for camera, raw, frame in zip(
            view.channel.cameras,
            view.snapshots,
            view.frames,
            strict=True,
        ):
            online = self._camera_online(camera)
            snapshot = CameraSnapshot(
                camera_id=camera.camera_id,
                camera_name=camera.name,
                count=raw.count if raw is not None else None,
                updated_at=raw.updated_at if raw is not None else now,
                online=online,
            )
            reason, stale_reason = self._camera_reason(snapshot, raw is not None, now)
            if not active and online:
                reason, stale_reason = "unknown", "detection_inactive"
            effective_count = snapshot.count if reason != "unknown" else None
            states[str(camera.camera_id)] = {
                "camera_id": camera.camera_id,
                "camera_name": camera.name,
                "count": effective_count,
                "status": reason,
                "online": online,
                "updated_at": raw.updated_at if raw is not None else None,
                "stale_reason": stale_reason,
            }
            snapshots.append(snapshot)
            tiles.append(
                CameraTile(
                    camera_id=camera.camera_id,
                    camera_name=camera.name,
                    frame=frame,
                    reason=reason,
                    person_count=effective_count,
                    online=online,
                    detail=stale_reason or "",
                )
            )
        return _PreparedView(
            channel=view.channel,
            generation=view.generation,
            snapshots=tuple(snapshots),
            states=states,
            tiles=tuple(tiles),
            active=active,
        )

    # 功能：实现 `_transition` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `prepared`（_PreparedView）：`prepared` 对应的业务输入值
    #   - `now`（float）：`now` 对应的业务输入值
    # 返回：tuple[ChannelDecision, _IncidentWork | None, bool] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::evaluate` 调用本符号
    #   - 内部调用：`classify_channel`、`self._channel_is_current_locked`、`self._states.setdefault`、`ChannelPresenceState`、`state.evaluate`、`self._build_status`、`self._clear_incident_locked`、`self._active_incidents.get`、`self._pending_incidents.get`、`_IncidentWork`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def _transition(
        self,
        prepared: _PreparedView,
        now: float,
    ) -> tuple[ChannelDecision, _IncidentWork | None, bool] | None:
        base = classify_channel(
            prepared.snapshots,
            now=now,
            stale_seconds=self._stale_seconds,
            active=prepared.active,
        )
        channel = prepared.channel
        key = (channel.feature_name, channel.channel_id)
        with self._lock:
            if not self._channel_is_current_locked(channel, prepared.generation):
                return None
            state = self._states.setdefault(key, ChannelPresenceState())
            decision = state.evaluate(
                base,
                now=now,
                empty_grace_seconds=channel.empty_grace_seconds,
                multi_grace_seconds=channel.multi_grace_seconds,
            )
            self._statuses[key] = self._build_status(channel, decision, prepared.states, now)
            if not decision.alarm:
                # 恢复正常只结束当前事件，不能清除分发器记录的最后告警时间。
                # alarm_interval 表示同一通道、同一功能两次实际告警的最小间隔，
                # 即使检测结果在正常与告警之间短暂波动，也必须继续受该间隔约束。
                self._clear_incident_locked(key)
                return decision, None, False
            active_reason = self._active_incidents.get(key)
            pending = self._pending_incidents.get(key)
            if active_reason == decision.reason or (
                pending is not None
                and pending[0] == decision.reason
                and pending[2] == prepared.generation
            ):
                return decision, None, False
            self._next_incident_token += 1
            token = self._next_incident_token
            self._pending_incidents[key] = (decision.reason, token, prepared.generation)
            return (
                decision,
                _IncidentWork(
                    key=key,
                    generation=prepared.generation,
                    token=token,
                    channel=channel,
                    decision=decision,
                    states=prepared.states,
                    tiles=prepared.tiles,
                    evaluated_at=now,
                ),
                False,
            )

    # 功能：实现 `_execute_incident` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `work`（_IncidentWork）：`work` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::evaluate` 调用本符号
    #   - 内部调用：`self._compose`、`self._build_alarm_request`、`self._incident_is_current`、`self._dispatcher.maybe_dispatch`、`logger.exception`、`self._pending_incidents.get`、`self._pending_incidents.pop`、`self._channel_is_current_locked`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _execute_incident(self, work: _IncidentWork) -> None:
        frame = self._compose(work.channel, work.tiles)
        request = self._build_alarm_request(
            work.channel,
            work.decision,
            work.states,
            frame,
            work.evaluated_at,
        )
        if not self._incident_is_current(work):
            return
        try:
            dispatched = self._dispatcher.maybe_dispatch(
                request,
                alarm_interval=work.channel.alarm_interval,
            )
        except Exception:
            logger.exception(
                f"[LogisticsChannelRuntime] 告警分发失败 "
                f"feature={work.channel.feature_name} channel_id={work.channel.channel_id}"
            )
            dispatched = False
        with self._lock:
            pending = self._pending_incidents.get(work.key)
            if pending != (work.decision.reason, work.token, work.generation):
                return
            self._pending_incidents.pop(work.key, None)
            if not self._channel_is_current_locked(work.channel, work.generation):
                return
            if dispatched:
                self._active_incidents[work.key] = work.decision.reason
                if frame is not None:
                    self._channel_frames[work.key] = frame

    # 功能：检查或判断 `_incident_is_current` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `work`（_IncidentWork）：`work` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_execute_incident` 调用本符号
    #   - 内部调用：`self._channel_is_current_locked`、`self._pending_incidents.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _incident_is_current(self, work: _IncidentWork) -> bool:
        with self._lock:
            return (
                self._channel_is_current_locked(work.channel, work.generation)
                and self._pending_incidents.get(work.key)
                == (work.decision.reason, work.token, work.generation)
            )

    # 功能：检查或判断 `_ensure_feature_loaded` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::camera_should_run`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::person_confidence_threshold`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::evaluate_after_camera_update`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::refresh_camera` 调用本符号；另有 3 处静态调用
    #   - 内部调用：`range`、`self._read_feature`、`self._install_feature_locked`、`RuntimeError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def _ensure_feature_loaded(self, feature_name: str) -> None:
        for _attempt in range(3):
            with self._lock:
                if feature_name in self._loaded_features:
                    return
                generation = self._generations[feature_name]
            channels = self._read_feature(feature_name)
            with self._lock:
                if generation != self._generations[feature_name]:
                    continue
                if feature_name in self._loaded_features:
                    return
                self._install_feature_locked(feature_name, channels)
                return
        raise RuntimeError(f"物流通道配置持续变化，无法加载 feature={feature_name}")

    # 功能：读取或查询 `_read_feature` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：tuple[_ChannelConfig, ...]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_ensure_feature_loaded` 调用本符号
    #   - 内部调用：`self._service.list_channels`、`response.get`、`self._service.get_channel`、`int`、`channels.append`、`self._parse_channel`、`tuple`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _read_feature(self, feature_name: str) -> tuple[_ChannelConfig, ...]:
        response = self._service.list_channels(feature_name) or {}
        channels = []
        for summary in response.get("items") or []:
            detail = self._service.get_channel(feature_name, int(summary["id"]))
            if detail is not None:
                channels.append(self._parse_channel(detail))
        return tuple(channels)

    # 功能：转换或规范化 `_parse_channel` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `detail`（dict）：`detail` 对应的业务输入值
    # 返回：_ChannelConfig；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_read_feature` 调用本符号
    #   - 内部调用：`detail.get`、`sorted`、`member.get`、`int`、`self._camera_provider`、`cameras.append`、`_CameraInfo`、`str`、`raw.get`、`_ChannelConfig`
    #          等共 15 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _parse_channel(self, detail: dict) -> _ChannelConfig:
        config = detail.get("config") or {}
        cameras = []
        members = sorted(
            (member for member in detail.get("members") or [] if member.get("enabled", True)),
            key=lambda member: (member.get("sort_order", 0), member.get("id", 0)),
        )
        for member in members:
            camera_id = int(member["camera_id"])
            raw = self._camera_provider(camera_id) or {}
            cameras.append(
                _CameraInfo(
                    camera_id=camera_id,
                    name=str(raw.get("name") or f"camera-{camera_id}"),
                    shm_name=str(raw.get("shm_name") or f"camera_{camera_id}"),
                )
            )
        return _ChannelConfig(
            feature_name=str(detail["feature_name"]),
            channel_id=int(detail["id"]),
            name=str(detail["name"]),
            enabled=bool(detail.get("enabled", True)),
            detection_start=config["detection_start"],
            detection_end=config["detection_end"],
            confidence_threshold=float(config["confidence_threshold"]),
            empty_grace_seconds=float(config["empty_grace_seconds"]),
            multi_grace_seconds=float(config["multi_grace_seconds"]),
            alarm_interval=float(config["alarm_interval"]),
            alarm=dict(config.get("alarm") or {}),
            cameras=tuple(cameras),
        )

    # 功能：实现 `_evaluation_loop` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`max`、`min`、`self._stop_event.wait`、`sorted`、`self._stop_event.is_set`、`self._ensure_feature_loaded`、`tuple`、`self.evaluate`、`logger.exception`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _evaluation_loop(self) -> None:
        interval = max(0.25, min(1.0, self._stale_seconds / 2.0))
        while not self._stop_event.wait(interval):
            try:
                for feature_name in sorted(LOGISTICS_FEATURES):
                    if self._stop_event.is_set():
                        return
                    self._ensure_feature_loaded(feature_name)
                with self._lock:
                    channels = tuple(self._channels)
                for feature_name, channel_id in channels:
                    if self._stop_event.is_set():
                        return
                    self.evaluate(feature_name, channel_id)
            except Exception:
                logger.exception("[LogisticsChannelRuntime] 周期巡检失败")

    # 功能：实现 `_install_feature_locked` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channels`（tuple[_ChannelConfig, ...]）：`channels` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_ensure_feature_loaded` 调用本符号
    #   - 内部调用：`self._channels.pop`、`self._camera_channels.pop`、`self._loaded_features.add`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _install_feature_locked(
        self,
        feature_name: str,
        channels: tuple[_ChannelConfig, ...],
    ) -> None:
        for key in [key for key in self._channels if key[0] == feature_name]:
            self._channels.pop(key, None)
        for key in [key for key in self._camera_channels if key[0] == feature_name]:
            self._camera_channels.pop(key, None)
        for channel in channels:
            self._channels[(feature_name, channel.channel_id)] = channel
            for camera in channel.cameras:
                self._camera_channels[(feature_name, camera.camera_id)] = channel.channel_id
        self._loaded_features.add(feature_name)

    # 功能：实现 `_invalidate_feature_locked` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::refresh_camera`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::refresh_channel` 调用本符号
    #   - 内部调用：`self._loaded_features.discard`、`self._channels.pop`、`self._camera_channels.pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _invalidate_feature_locked(self, feature_name: str) -> None:
        self._generations[feature_name] += 1
        self._loaded_features.discard(feature_name)
        for key in [key for key in self._channels if key[0] == feature_name]:
            self._channels.pop(key, None)
        for key in [key for key in self._camera_channels if key[0] == feature_name]:
            self._camera_channels.pop(key, None)

    # 功能：检查或判断 `_channel_is_current_locked` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
    #   - `generation`（int）：`generation` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::camera_should_run`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::get_channel_frame`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_transition`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_execute_incident` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`self._channels.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _channel_is_current_locked(self, channel: _ChannelConfig, generation: int) -> bool:
        return (
            self._generations[channel.feature_name] == generation
            and self._channels.get((channel.feature_name, channel.channel_id)) is channel
        )

    # 功能：检查或判断 `_channel_is_active` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::camera_should_run`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_snapshot_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_prepare_view` 调用本符号
    #   - 内部调用：`self._wall_time_provider().timetz().replace`、`self._wall_time_provider().timetz`、`self._wall_time_provider`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def _channel_is_active(self, channel: _ChannelConfig) -> bool:
        if not channel.enabled:
            return False
        local_time = self._wall_time_provider().timetz().replace(tzinfo=None)
        return channel.detection_start <= local_time <= channel.detection_end

    # 功能：实现 `_camera_online` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera`（_CameraInfo）：摄像头配置或实体
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_prepare_view` 调用本符号
    #   - 内部调用：`bool`、`self._is_camera_active`、`logger.warning`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _camera_online(self, camera: _CameraInfo) -> bool:
        try:
            return bool(self._is_camera_active(camera.shm_name))
        except Exception as exc:
            logger.warning(
                f"[LogisticsChannelRuntime] 摄像头在线状态读取失败 "
                f"camera_id={camera.camera_id}: {exc}"
            )
            return False

    # 功能：实现 `_camera_reason` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `snapshot`（CameraSnapshot）：`snapshot` 对应的业务输入值
    #   - `has_snapshot`（bool）：`has_snapshot` 对应的业务输入值
    #   - `now`（float）：`now` 对应的业务输入值
    # 返回：tuple[str, str | None]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_prepare_view` 调用本符号
    #   - 内部调用：`self._finite_number`、`isinstance`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _camera_reason(
        self,
        snapshot: CameraSnapshot,
        has_snapshot: bool,
        now: float,
    ) -> tuple[str, str | None]:
        if not snapshot.online:
            return "unknown", "offline"
        if not has_snapshot:
            return "unknown", "waiting_for_result"
        if (
            not self._finite_number(snapshot.updated_at)
            or snapshot.updated_at > now
            or now - snapshot.updated_at > self._stale_seconds
        ):
            return "unknown", "stale"
        count = snapshot.count
        if count is None:
            return "unknown", "inference_unknown"
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return "unknown", "invalid_count"
        if count == 0:
            return "empty", None
        if count == 1:
            return "normal", None
        return "multiple", None

    # 功能：绘制或渲染 `_compose` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
    #   - `tiles`（tuple[CameraTile, ...]）：`tiles` 对应的业务输入值
    # 返回：np.ndarray | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::evaluate`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::get_channel_frame`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_execute_incident` 调用本符号
    #   - 内部调用：`self._compositor`、`logger.warning`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _compose(
        self,
        channel: _ChannelConfig,
        tiles: tuple[CameraTile, ...],
    ) -> np.ndarray | None:
        if not tiles:
            return None
        try:
            return self._compositor(tiles)
        except (ValueError, TypeError) as exc:
            logger.warning(
                f"[LogisticsChannelRuntime] 拼接失败 feature={channel.feature_name} "
                f"channel_id={channel.channel_id}: {exc}"
            )
            return None

    # 功能：创建或构建 `_build_status` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
    #   - `decision`（ChannelDecision）：`decision` 对应的业务输入值
    #   - `states`（dict[str, dict]）：`states` 对应的业务输入值
    #   - `now`（float）：`now` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_transition` 调用本符号
    #   - 内部调用：`states.items`、`list`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _build_status(
        channel: _ChannelConfig,
        decision: ChannelDecision,
        states: dict[str, dict],
        now: float,
    ) -> dict:
        return {
            "feature_name": channel.feature_name,
            "channel_id": channel.channel_id,
            "channel_name": channel.name,
            "reason": decision.reason,
            "alarm": decision.alarm,
            "duration_seconds": decision.duration_seconds,
            "threshold_seconds": decision.threshold_seconds,
            "camera_ids": [camera.camera_id for camera in channel.cameras],
            "camera_counts": {key: value["count"] for key, value in states.items()},
            "camera_states": states,
            "offending_camera_ids": list(decision.offending_camera_ids),
            "updated_at": now,
        }

    # 功能：创建或构建 `_build_alarm_request` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
    #   - `decision`（ChannelDecision）：`decision` 对应的业务输入值
    #   - `states`（dict[str, dict]）：`states` 对应的业务输入值
    #   - `frame`（np.ndarray | None）：待处理的视频图像帧
    #   - `now`（float）：`now` 对应的业务输入值
    # 返回：AlarmRequest；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_execute_incident` 调用本符号
    #   - 内部调用：`states.items`、`list`、`alarm.get`、`bool`、`horn.get`、`wechat.get`、`np.zeros`、`AlarmRequest`、`int`、`self._violation_type_provider`
    #          等共 12 个调用。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    def _build_alarm_request(
        self,
        channel: _ChannelConfig,
        decision: ChannelDecision,
        states: dict[str, dict],
        frame: np.ndarray | None,
        now: float,
    ) -> AlarmRequest:
        metadata = {
            "feature_name": channel.feature_name,
            "channel_id": channel.channel_id,
            "channel_name": channel.name,
            "reason": decision.reason,
            "camera_ids": [camera.camera_id for camera in channel.cameras],
            "camera_counts": {key: value["count"] for key, value in states.items()},
            "camera_states": states,
            "offending_camera_ids": list(decision.offending_camera_ids),
            "alarm_started_at": now - decision.duration_seconds,
            "triggered_at": now,
        }
        alarm = channel.alarm
        horn = alarm.get("horn") or {}
        wechat = alarm.get("wechat") or {}
        alarm_config = {
            "sql": {"enable": bool(alarm.get("sql_enable")), "parm": {}},
            "horn": {
                "enable": bool(horn.get("enabled")),
                "parm": {
                    "horn_id": horn.get("horn_id"),
                    "horn_event_id": horn.get("horn_event_id"),
                },
            },
            "wechat": {
                "enable": bool(wechat.get("enabled")),
                "parm": {"user": wechat.get("user", "")},
            },
        }
        evidence = frame
        if evidence is None:
            evidence = np.zeros((360, 640, 3), dtype=np.uint8)
            metadata["evidence_error"] = "channel_frame_unavailable"
        return AlarmRequest(
            feature_name=channel.feature_name,
            camera_id=channel.channel_id,
            camera_name=channel.name,
            frame=evidence,
            violation_type=int(self._violation_type_provider(channel.feature_name)),
            alarm_config=alarm_config,
            camera_key=self._evidence_key(channel),
            subject_type="logistics_channel",
            subject_id=str(channel.channel_id),
            subject_name=channel.name,
            reason=decision.reason,
            metadata=metadata,
        )

    # 功能：实现 `_evidence_key` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::evaluate`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_build_alarm_request` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _evidence_key(channel: _ChannelConfig) -> str:
        return f"logistics_channel:{channel.feature_name}:{channel.channel_id}"

    # 功能：删除或清理 `_clear_incident_locked` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（tuple[str, int]）：用于查询、分组或缓存的键
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_transition`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_reset_non_alarm_locked` 调用本符号
    #   - 内部调用：`self._active_incidents.pop`、`self._pending_incidents.pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _clear_incident_locked(self, key: tuple[str, int]) -> bool:
        active = self._active_incidents.pop(key, None) is not None
        self._pending_incidents.pop(key, None)
        return active

    # 功能：实现 `_reset_non_alarm_locked` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
    #   - `reason`（str）：`reason` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::camera_should_run` 调用本符号
    #   - 内部调用：`self._states.get`、`state.reset`、`self._clear_incident_locked`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _reset_non_alarm_locked(self, channel: _ChannelConfig, reason: str) -> bool:
        key = (channel.feature_name, channel.channel_id)
        state = self._states.get(key)
        if state is not None:
            state.reset()
        reset = self._clear_incident_locked(key)
        self._statuses[key] = {
            "feature_name": channel.feature_name,
            "channel_id": channel.channel_id,
            "channel_name": channel.name,
            "reason": reason,
            "alarm": False,
        }
        return reset

    # 功能：删除或清理 `_clear_channel_state_locked` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::refresh_camera`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::refresh_channel` 调用本符号
    #   - 内部调用：`self._states.pop`、`self._statuses.pop`、`self._channel_frames.pop`、`self._active_incidents.pop`、`self._pending_incidents.pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _clear_channel_state_locked(self, channel: _ChannelConfig) -> None:
        key = (channel.feature_name, channel.channel_id)
        self._states.pop(key, None)
        self._statuses.pop(key, None)
        self._channel_frames.pop(key, None)
        self._active_incidents.pop(key, None)
        self._pending_incidents.pop(key, None)

    # 功能：删除或清理 `_clear_all_state_locked` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::stop` 调用本符号
    #   - 内部调用：`self._channels.clear`、`self._camera_channels.clear`、`self._loaded_features.clear`、`self._states.clear`、`self._statuses.clear`、`self._channel_frames.clear`、`self._active_incidents.clear`、`self._pending_incidents.clear`、`self._frames.clear`、`self._snapshots.clear`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _clear_all_state_locked(self) -> None:
        self._channels.clear()
        self._camera_channels.clear()
        self._loaded_features.clear()
        self._states.clear()
        self._statuses.clear()
        self._channel_frames.clear()
        self._active_incidents.clear()
        self._pending_incidents.clear()
        self._frames.clear()
        self._snapshots.clear()

    # 功能：实现 `_reset_cooldown` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `channel`（_ChannelConfig）：`channel` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::camera_should_run`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::evaluate`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::refresh_camera`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::refresh_channel` 调用本符号
    #   - 内部调用：`getattr`、`callable`、`reset`、`str`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _reset_cooldown(self, channel: _ChannelConfig) -> None:
        reset = getattr(self._dispatcher, "reset_subject_cooldown", None)
        if callable(reset):
            reset("logistics_channel", str(channel.channel_id), channel.feature_name)

    # 功能：实现 `_copy_status` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `value`（dict | None）：待转换、校验或写入的值
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::get_channel_status` 调用本符号
    #   - 内部调用：`dict`、`list`、`value.get`、`(value.get('camera_states') or {}).items`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _copy_status(value: dict | None) -> dict | None:
        if value is None:
            return None
        copied = dict(value)
        copied["camera_ids"] = list(value.get("camera_ids") or [])
        copied["offending_camera_ids"] = list(value.get("offending_camera_ids") or [])
        copied["camera_counts"] = dict(value.get("camera_counts") or {})
        copied["camera_states"] = {
            key: dict(state) for key, state in (value.get("camera_states") or {}).items()
        }
        return copied

    # 功能：实现 `_finite_number` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `value`（object）：待转换、校验或写入的值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_camera_reason` 调用本符号
    #   - 内部调用：`isinstance`、`isfinite`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _finite_number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


__all__ = ["LogisticsChannelRuntime"]
