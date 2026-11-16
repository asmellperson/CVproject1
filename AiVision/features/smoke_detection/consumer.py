"""后台订阅设备烟雾事件，独立于网页预览和平台推理流程。"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import time
from typing import Callable

import cv2
import numpy as np

from AiVision.core.cache import config_cache
from AiVision.core.logger import logger
from AiVision.features._shared.consumer import BaseFunctionConsumer
from .device import SmokeDeviceClient
from .events import SmokeEvent


_RECONNECT_SECONDS = 2.0
_STOP_TIMEOUT_SECONDS = 15.0
_FRAME_MAX_AGE_SECONDS = 10.0
_ACTIVITY_MAX_AGE_SECONDS = 30.0
_RECENT_EVENT_LIMIT = 256


@dataclass
class _SmokeState:
    connection_state: str = "connecting"
    message: str = "正在连接设备报警接口"
    active: bool | None = None
    in_alarm: bool = False
    last_activity_at: float = 0.0
    last_event_at: str | None = None
    event_protocol_verified: bool = False
    protocol_warning: bool = False
    recent_events: deque[str] = field(default_factory=lambda: deque(maxlen=_RECENT_EVENT_LIMIT))


@dataclass
class _Subscription:
    camera_id: int
    config: dict
    camera: dict
    stop_event: threading.Event = field(default_factory=threading.Event)
    client: SmokeDeviceClient | None = None
    thread: threading.Thread | None = None


class SmokeConsumer(BaseFunctionConsumer):
    """每台启用设备保持独立连接，仅转发设备明确上报的烟雾事件。"""

    def _process(self, roi: np.ndarray, camera_id: int):
        raise RuntimeError("烟雾检测由摄像头执行，不接受平台逐帧识别")

    def post_process(self, camera_id: int, result: tuple):
        raise RuntimeError("烟雾检测直接展示设备原始画面")

    def __init__(self, *args, device_factory: Callable = SmokeDeviceClient,
                 reconnect_seconds: float = _RECONNECT_SECONDS,
                 stop_timeout_seconds: float = _STOP_TIMEOUT_SECONDS, **kwargs):
        super().__init__(*args, **kwargs)
        self._device_factory = device_factory
        self._reconnect_seconds = reconnect_seconds
        self._stop_timeout_seconds = stop_timeout_seconds
        self._subscriptions: dict[int, _Subscription] = {}
        self._smoke_states: dict[int, _SmokeState] = {}

    def start(self):
        """启动事件订阅，不启动推理路由器或逐帧检测循环。"""
        with self._lifecycle_lock:
            if self.running:
                return
            if any(item.thread and item.thread.is_alive() for item in self._subscriptions.values()):
                raise RuntimeError("烟雾设备订阅线程尚未退出")
            self.config_cache.clear()
            self._load_initial_configs()
            self.config_cache = {key: value for key, value in self.config_cache.items()
                                 if value.get("camera_enable", True)}
            self.running = True
            for camera_id, cfg in list(self.config_cache.items()):
                self._start_subscription(camera_id, cfg)
        logger.info("[smoke_detection] 设备报警订阅已启动")

    def stop(self):
        """先取消所有连接，再以统一期限回收线程，避免逐路累积等待。"""
        with self._lifecycle_lock:
            self.running = False
            with self._camera_state_lock:
                subscriptions = list(self._subscriptions.values())
                for item in subscriptions:
                    item.stop_event.set()
            for item in subscriptions:
                if item.client is not None:
                    item.client.close()
            deadline = time.monotonic() + self._stop_timeout_seconds
            for item in subscriptions:
                if item.thread is not None:
                    item.thread.join(max(0.0, deadline - time.monotonic()))
            alive = [item for item in subscriptions if item.thread and item.thread.is_alive()]
            if alive:
                raise RuntimeError(f"{len(alive)} 路烟雾设备订阅停止超时")
            with self._camera_state_lock:
                self._subscriptions.clear()
                self._smoke_states.clear()
                self._monitor_results.clear()
        logger.info("[smoke_detection] 设备报警订阅已停止")

    def update_config(self, camera_id: int):
        """刷新连接与通知配置；旧连接回调不能污染新配置。"""
        with self._lifecycle_lock:
            cfg = config_cache.get_function_config(camera_id, self.feature_name)
            if not cfg or not cfg.get("enable") or not cfg.get("camera_enable", True):
                self._remove_subscription(camera_id)
                return
            self._remove_subscription(camera_id, keep_state=True)
            with self._camera_state_lock:
                self.config_cache[camera_id] = cfg
            if self.running:
                self._start_subscription(camera_id, cfg)

    def update_status(self, camera_id: int, enabled: bool):
        """沿用摄像头功能启停入口，禁用立即撤销设备连接。"""
        if enabled:
            self.update_config(camera_id)
        else:
            with self._lifecycle_lock:
                self._remove_subscription(camera_id)

    def remove_camera(self, camera_id: int, shm_name: str | None = None):
        """删除摄像头时撤销其连接和设备事件状态。"""
        self.update_status(camera_id, False)
        self._reset_alarm_cooldown(camera_id)

    def _remove_subscription(self, camera_id: int, *, keep_state: bool = False):
        with self._camera_state_lock:
            subscription = self._subscriptions.get(camera_id)
            if subscription is not None:
                subscription.stop_event.set()
            self.config_cache.pop(camera_id, None)
            if not keep_state:
                self._smoke_states.pop(camera_id, None)
        if subscription is not None:
            if subscription.client is not None:
                subscription.client.close()
            if subscription.thread is not None:
                subscription.thread.join(self._stop_timeout_seconds)
                if subscription.thread.is_alive():
                    raise RuntimeError("烟雾设备订阅停止超时")
            with self._camera_state_lock:
                if self._subscriptions.get(camera_id) is subscription:
                    self._subscriptions.pop(camera_id, None)

    def _start_subscription(self, camera_id: int, cfg: dict):
        if not cfg.get("camera_enable", True):
            return
        camera = config_cache.get_camera_config(camera_id)
        subscription = _Subscription(camera_id=camera_id, config=cfg, camera=dict(camera or {}))
        with self._camera_state_lock:
            state = self._smoke_states.setdefault(camera_id, _SmokeState())
            state.connection_state = "connecting"
            state.message = "正在连接设备报警接口"
            state.active = None
            state.in_alarm = False
            state.event_protocol_verified = False
            state.protocol_warning = False
            self._subscriptions[camera_id] = subscription
        subscription.thread = threading.Thread(target=self._listen, args=(subscription,),
                                               name=f"smoke-device-{camera_id}", daemon=True)
        subscription.thread.start()

    def _is_current(self, subscription: _Subscription) -> bool:
        return (self.running and not subscription.stop_event.is_set()
                and self._subscriptions.get(subscription.camera_id) is subscription
                and self.config_cache.get(subscription.camera_id) is subscription.config)

    def _connection(self, subscription: _Subscription, state: str, message: str):
        with self._camera_state_lock:
            if not self._is_current(subscription):
                return
            snapshot = self._smoke_states[subscription.camera_id]
            snapshot.connection_state = state
            if state != "connected" or not snapshot.protocol_warning:
                snapshot.message = message
            snapshot.active = None
            if state == "connected":
                snapshot.last_activity_at = time.time()
                # 断线期间可能已结束又发生新事件；重连以设备事件标识去重，不沿用旧持续态。
                snapshot.in_alarm = False

    def _activity(self, subscription: _Subscription):
        with self._camera_state_lock:
            if self._is_current(subscription):
                self._smoke_states[subscription.camera_id].last_activity_at = time.time()

    def _protocol_warning(self, subscription: _Subscription, message: str):
        with self._camera_state_lock:
            if not self._is_current(subscription):
                return
            state = self._smoke_states[subscription.camera_id]
            state.protocol_warning = bool(message)
            if message:
                state.message = message
                state.active = None
                state.event_protocol_verified = False

    def _listen(self, subscription: _Subscription):
        while self._is_current(subscription):
            client = None
            try:
                client = self._device_factory(subscription.camera, subscription.config)
                with self._camera_state_lock:
                    if not self._is_current(subscription):
                        break
                    subscription.client = client
                for event in client.iter_events(
                    subscription.stop_event,
                    on_connected=lambda: self._connection(subscription, "connected", "设备报警接口已连接，等待烟雾事件"),
                    on_activity=lambda: self._activity(subscription),
                    on_protocol_warning=lambda message: self._protocol_warning(subscription, message),
                ):
                    self._receive_event(subscription, event)
                self._connection(subscription, "disconnected", "设备报警连接已断开，正在重连")
            except Exception as exc:
                # 请求异常可能包含认证地址；这里只记录异常类型，前端使用固定脱敏文案。
                if self._is_current(subscription):
                    logger.warning(f"[smoke_detection] 设备报警订阅异常 camera_id={subscription.camera_id} type={type(exc).__name__}")
                    self._connection(subscription, "error", "设备报警订阅失败，请检查连接与设备能力")
            finally:
                if client is not None:
                    client.close()
                with self._camera_state_lock:
                    if subscription.client is client:
                        subscription.client = None
            if subscription.stop_event.wait(self._reconnect_seconds):
                break

    def _receive_event(self, subscription: _Subscription, event: SmokeEvent):
        with self._camera_state_lock:
            if (not self._is_current(subscription) or event.event_type != "smokeDetection"
                    or event.channel_id != subscription.config["event_channel_id"]):
                return
            state = self._smoke_states[subscription.camera_id]
            state.connection_state = "connected"
            state.last_activity_at = time.time()
            state.last_event_at = event.date_time
            state.active = event.active
            state.event_protocol_verified = True
            state.protocol_warning = False
            state.message = "设备上报烟雾报警" if event.active else "设备上报烟雾报警结束"
            if not event.active:
                state.in_alarm = False
                return
            event_key = f"{event.channel_id}:{event.event_id}:{event.date_time}"
            duplicate = state.in_alarm or event_key in state.recent_events
            if duplicate:
                state.in_alarm = True
                return
            state.in_alarm = True
        # 证据解码及告警持久化不占用状态锁，监控读取和其他设备心跳不等待磁盘操作。
        try:
            frame = self._event_frame(subscription, event)
            if not self._is_current(subscription):
                return
            self._handle_alarm(subscription.camera_id, (True, event), frame, config=subscription.config)
        except Exception:
            with self._camera_state_lock:
                if self._is_current(subscription):
                    self._smoke_states[subscription.camera_id].in_alarm = False
            raise
        with self._camera_state_lock:
            if self._is_current(subscription):
                self._smoke_states[subscription.camera_id].recent_events.append(event_key)

    def _event_frame(self, subscription: _Subscription, event: SmokeEvent) -> np.ndarray | None:
        if event.picture:
            picture = cv2.imdecode(np.frombuffer(event.picture, dtype=np.uint8), cv2.IMREAD_COLOR)
            if picture is not None and picture.size:
                return picture
        key = subscription.config.get("shm_name", "")
        frame = self.latest_frames.get(key)
        sampled_at = self.latest_frame_times.get(key, 0.0)
        if (isinstance(frame, np.ndarray) and frame.ndim == 3 and frame.size
                and sampled_at > 0 and 0 <= time.time() - sampled_at <= _FRAME_MAX_AGE_SECONDS):
            return frame.copy()
        return None

    def _alarm_context(self, camera_id: int, result: tuple) -> dict:
        event = result[1]
        return {
            "reason": "摄像头上报烟雾报警",
            "metadata": {
                "source": "device",
                "device_event_type": event.event_type,
                "device_event_time": event.date_time,
                "device_event_id": event.event_id,
                "device_channel_id": event.channel_id,
                "device_active_post_count": event.active_post_count,
            },
        }

    def get_live_preview(self, camera_key: str, frame: np.ndarray, *, now: float):
        """监控直接展示设备原始画面，不添加平台识别结果或本地检测区域。"""
        with self._camera_state_lock:
            if self.running and any(cfg.get("shm_name") == camera_key and cfg.get("enable")
                                    and cfg.get("camera_enable", True) for cfg in self.config_cache.values()):
                return frame
        return None

    def get_monitor_status(self, camera_key: str) -> dict | None:
        with self._camera_state_lock:
            matched = next(((camera_id, cfg) for camera_id, cfg in self.config_cache.items()
                            if cfg.get("shm_name") == camera_key), None)
            if matched is None:
                return None
            camera_id, cfg = matched
            state = self._smoke_states.get(camera_id, _SmokeState())
            now = time.time()
            connected = (self.running and state.connection_state == "connected"
                         and 0 <= now - state.last_activity_at <= _ACTIVITY_MAX_AGE_SECONDS)
            active = state.active if connected else None
            connection_state = state.connection_state
            message = state.message
            if not self.running:
                connection_state, message = "disabled", "设备报警接收未启动"
            elif state.connection_state == "connected" and not connected:
                connection_state, message = "disconnected", "设备报警连接长时间未收到心跳或事件"
            return {
                "camera_key": camera_key, "feature": self.feature_name,
                "count": None, "alarm": active is True,
                "alarm_state": "active" if active is True else "inactive" if active is False else "unknown",
                "reason": "unsupported_event" if connected and state.protocol_warning else
                          "smoke_alarm" if active is True else "device_clear" if active is False else "unknown",
                "duration_seconds": None, "threshold_seconds": None,
                "updated_at_s": state.last_activity_at,
                "updated_at": datetime.fromtimestamp(state.last_activity_at, tz=timezone.utc).isoformat() if state.last_activity_at else None,
                "valid_for_seconds": max(0.0, _ACTIVITY_MAX_AGE_SECONDS - (now - state.last_activity_at)) if connected else 0.0,
                "details": [], "connection_state": connection_state,
                "last_event_at": state.last_event_at,
                "event_protocol_verified": state.event_protocol_verified,
                "event_channel_id": cfg["event_channel_id"], "message": message,
            }
