"""四个物流单人检测模块共用的通道级运行时。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Event, RLock, Thread
import time
from typing import Callable

import numpy as np

from core.alarm.dispatcher import AlarmRequest, alarm_dispatcher
from core.logger import logger
from core.settings import settings
from features import all_specs
from platform.camera.service import camera_service

from .compositor import CameraTile, compose_channel_frame
from .constants import LOGISTICS_FEATURES, require_logistics_feature
from .service import logistics_channel_service
from .state import (
    CameraSnapshot,
    CameraSnapshotStore,
    ChannelDecision,
    ChannelPresenceState,
    classify_channel,
)


@dataclass(frozen=True)
class _CameraInfo:
    camera_id: int
    name: str
    shm_name: str


@dataclass(frozen=True)
class _ChannelConfig:
    feature_name: str
    channel_id: int
    name: str
    enabled: bool
    detection_start: object
    detection_end: object
    empty_grace_seconds: float
    multi_grace_seconds: float
    alarm_interval: float
    alarm: dict
    cameras: tuple[_CameraInfo, ...]


class LogisticsChannelRuntime:
    """聚合逐路快照、维护通道计时并统一分发通道告警。"""

    def __init__(
        self,
        *,
        channel_service=logistics_channel_service,
        dispatcher=alarm_dispatcher,
        camera_provider: Callable[[int], dict | None] | None = None,
        is_camera_active: Callable[[str], bool] | None = None,
        stale_seconds: float | None = None,
        wall_time_provider: Callable[[], datetime] | None = None,
        violation_type_provider: Callable[[str], int] | None = None,
        clock_provider: Callable[[], float] | None = None,
        start_background: bool = True,
    ) -> None:
        self._service = channel_service
        self._dispatcher = dispatcher
        self._camera_provider = camera_provider or (
            lambda camera_id: camera_service.get_camera(str(camera_id))
        )
        self._is_camera_active = is_camera_active or (lambda _shm_name: True)
        self._stale_seconds = (
            settings.runtime.logistics_status_stale_seconds
            if stale_seconds is None
            else float(stale_seconds)
        )
        self._wall_time_provider = wall_time_provider or (
            lambda: datetime.now().astimezone()
        )
        self._violation_type_provider = violation_type_provider or (
            lambda feature_name: all_specs()[feature_name].violation_type
        )
        self._clock_provider = clock_provider or time.time
        self._start_background = start_background
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = RLock()
        self._snapshots = CameraSnapshotStore()
        self._frames: dict[tuple[str, int], np.ndarray] = {}
        self._channels: dict[tuple[str, int], _ChannelConfig] = {}
        self._camera_channels: dict[tuple[str, int], int] = {}
        self._loaded_features: set[str] = set()
        self._states: dict[tuple[str, int], ChannelPresenceState] = {}
        self._statuses: dict[tuple[str, int], dict] = {}
        self._channel_frames: dict[tuple[str, int], np.ndarray] = {}
        self._active_incidents: dict[tuple[str, int], str] = {}
        self._running = False

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            if self._start_background:
                self._thread = Thread(
                    target=self._evaluation_loop,
                    daemon=True,
                    name="logistics-channel-runtime",
                )
                self._thread.start()
        logger.info("[LogisticsChannelRuntime] 已启动")

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        with self._lock:
            self._channels.clear()
            self._camera_channels.clear()
            self._loaded_features.clear()
            self._states.clear()
            self._statuses.clear()
            self._channel_frames.clear()
            self._active_incidents.clear()
            self._frames.clear()
            for feature_name in LOGISTICS_FEATURES:
                self._snapshots.clear_feature(feature_name)
        logger.info("[LogisticsChannelRuntime] 已停止")

    def camera_should_run(self, feature_name: str, camera_id: int) -> bool:
        feature_name = require_logistics_feature(feature_name)
        with self._lock:
            self._ensure_feature_loaded(feature_name)
            channel_id = self._camera_channels.get((feature_name, camera_id))
            if channel_id is None:
                return False
            channel = self._channels.get((feature_name, channel_id))
            active = bool(channel and self._channel_is_active(channel))
            if not active and channel is not None:
                self._reset_non_alarm_locked(channel, "inactive")
            return active

    def update_camera_snapshot(
        self,
        feature_name: str,
        snapshot: CameraSnapshot,
        annotated_frame: np.ndarray | None,
    ) -> None:
        feature_name = require_logistics_feature(feature_name)
        with self._lock:
            if not self._running:
                logger.warning(
                    f"[LogisticsChannelRuntime] 未启动时收到快照 "
                    f"feature={feature_name} camera_id={snapshot.camera_id}"
                )
            self._snapshots.upsert(feature_name, snapshot)
            key = (feature_name, snapshot.camera_id)
            if isinstance(annotated_frame, np.ndarray) and annotated_frame.size:
                self._frames[key] = annotated_frame.copy()

    def evaluate_after_camera_update(
        self,
        feature_name: str,
        camera_id: int,
    ) -> ChannelDecision | None:
        feature_name = require_logistics_feature(feature_name)
        with self._lock:
            self._ensure_feature_loaded(feature_name)
            channel_id = self._camera_channels.get((feature_name, camera_id))
        if channel_id is None:
            return None
        return self.evaluate(feature_name, channel_id)

    def evaluate(
        self,
        feature_name: str,
        channel_id: int,
        *,
        now: float | None = None,
    ) -> ChannelDecision:
        feature_name = require_logistics_feature(feature_name)
        evaluated_at = self._clock_provider() if now is None else float(now)
        with self._lock:
            self._ensure_feature_loaded(feature_name)
            channel = self._channels.get((feature_name, channel_id))
            if channel is None:
                return ChannelDecision("unconfigured", False, 0.0, None)

            active = self._channel_is_active(channel)
            snapshots, states, tiles = self._collect_camera_state_locked(
                channel,
                evaluated_at,
            )
            base = classify_channel(
                snapshots,
                now=evaluated_at,
                stale_seconds=self._stale_seconds,
                active=active,
            )
            state = self._states.setdefault(
                (feature_name, channel_id),
                ChannelPresenceState(),
            )
            decision = state.evaluate(
                base,
                now=evaluated_at,
                empty_grace_seconds=channel.empty_grace_seconds,
                multi_grace_seconds=channel.multi_grace_seconds,
            )
            frame = self._compose_channel_frame(channel, tiles)
            if frame is not None:
                self._channel_frames[(feature_name, channel_id)] = frame
            self._statuses[(feature_name, channel_id)] = self._build_status(
                channel,
                decision,
                states,
                evaluated_at,
            )

            incident_key = (feature_name, channel_id)
            if not decision.alarm:
                self._clear_incident_locked(channel)
                return decision
            if self._active_incidents.get(incident_key) == decision.reason:
                return decision

            request = self._build_alarm_request(
                channel,
                decision,
                states,
                frame,
                evaluated_at,
            )
            try:
                dispatched = self._dispatcher.maybe_dispatch(
                    request,
                    alarm_interval=channel.alarm_interval,
                )
            except Exception:
                logger.exception(
                    f"[LogisticsChannelRuntime] 告警分发失败 "
                    f"feature={feature_name} channel_id={channel_id}"
                )
                dispatched = False
            if dispatched:
                self._active_incidents[incident_key] = decision.reason
            return decision

    def refresh_camera(self, feature_name: str, camera_id: int) -> None:
        """摄像头 ROI/推理配置变化时清理其所属通道的旧判定状态。"""
        feature_name = require_logistics_feature(feature_name)
        with self._lock:
            self._ensure_feature_loaded(feature_name)
            channel_id = self._camera_channels.get((feature_name, camera_id))
        if channel_id is not None:
            self.refresh_channel(feature_name, channel_id)

    def refresh_channel(self, feature_name: str, channel_id: int) -> None:
        """配置或成员事件后丢弃旧快照、计时、证据和成员映射。"""
        feature_name = require_logistics_feature(feature_name)
        with self._lock:
            old = self._channels.get((feature_name, channel_id))
            if old is not None:
                for camera in old.cameras:
                    self._snapshots.remove(feature_name, camera.camera_id)
                    self._frames.pop((feature_name, camera.camera_id), None)
            self._clear_incident_locked(old)
            self._channels.pop((feature_name, channel_id), None)
            self._states.pop((feature_name, channel_id), None)
            self._statuses.pop((feature_name, channel_id), None)
            self._channel_frames.pop((feature_name, channel_id), None)
            self._drop_feature_index_locked(feature_name)
            self._ensure_feature_loaded(feature_name)
        logger.info(
            f"[LogisticsChannelRuntime] 已刷新 feature={feature_name} "
            f"channel_id={channel_id}"
        )

    def get_channel_status(self, feature_name: str, channel_id: int) -> dict | None:
        feature_name = require_logistics_feature(feature_name)
        with self._lock:
            value = self._statuses.get((feature_name, channel_id))
            return dict(value) if value is not None else None

    def get_channel_frame(self, feature_name: str, channel_id: int) -> np.ndarray | None:
        feature_name = require_logistics_feature(feature_name)
        with self._lock:
            frame = self._channel_frames.get((feature_name, channel_id))
            return frame.copy() if frame is not None else None

    def _ensure_feature_loaded(self, feature_name: str) -> None:
        if feature_name in self._loaded_features:
            return
        response = self._service.list_channels(feature_name) or {}
        for summary in response.get("items") or []:
            detail = self._service.get_channel(feature_name, int(summary["id"]))
            if detail is None:
                continue
            channel = self._parse_channel(detail)
            self._channels[(feature_name, channel.channel_id)] = channel
            for camera in channel.cameras:
                self._camera_channels[(feature_name, camera.camera_id)] = channel.channel_id
        self._loaded_features.add(feature_name)

    def _evaluation_loop(self) -> None:
        interval = max(0.25, min(1.0, self._stale_seconds / 2.0))
        while not self._stop_event.wait(interval):
            with self._lock:
                if not self._running:
                    return
                for feature_name in LOGISTICS_FEATURES:
                    self._ensure_feature_loaded(feature_name)
                channels = tuple(self._channels)
            for feature_name, channel_id in channels:
                try:
                    self.evaluate(feature_name, channel_id)
                except Exception:
                    logger.exception(
                        f"[LogisticsChannelRuntime] 通道巡检失败 "
                        f"feature={feature_name} channel_id={channel_id}"
                    )

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
            enabled=bool(detail.get("enabled", True) and config.get("enabled", True)),
            detection_start=config["detection_start"],
            detection_end=config["detection_end"],
            empty_grace_seconds=float(config["empty_grace_seconds"]),
            multi_grace_seconds=float(config["multi_grace_seconds"]),
            alarm_interval=float(config["alarm_interval"]),
            alarm=dict(config.get("alarm") or {}),
            cameras=tuple(cameras),
        )

    def _drop_feature_index_locked(self, feature_name: str) -> None:
        self._loaded_features.discard(feature_name)
        for key in [key for key in self._camera_channels if key[0] == feature_name]:
            self._camera_channels.pop(key, None)
        for key in [key for key in self._channels if key[0] == feature_name]:
            self._channels.pop(key, None)

    def _channel_is_active(self, channel: _ChannelConfig) -> bool:
        if not channel.enabled:
            return False
        local_time = self._wall_time_provider().timetz().replace(tzinfo=None)
        return channel.detection_start <= local_time <= channel.detection_end

    def _collect_camera_state_locked(
        self,
        channel: _ChannelConfig,
        now: float,
    ) -> tuple[list[CameraSnapshot], dict[str, dict], list[CameraTile]]:
        snapshots: list[CameraSnapshot] = []
        states: dict[str, dict] = {}
        tiles: list[CameraTile] = []
        for camera in channel.cameras:
            raw = self._snapshots.get(channel.feature_name, camera.camera_id)
            online = self._camera_online(camera)
            snapshot = CameraSnapshot(
                camera_id=camera.camera_id,
                camera_name=camera.name,
                count=raw.count if raw is not None else None,
                updated_at=raw.updated_at if raw is not None else now,
                online=online,
            )
            reason, stale_reason = self._camera_reason(snapshot, raw is not None, now)
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
                    frame=self._frames.get((channel.feature_name, camera.camera_id)),
                    reason=reason,
                    person_count=effective_count,
                    online=online,
                    detail=stale_reason or "",
                )
            )
        return snapshots, states, tiles

    def _camera_online(self, camera: _CameraInfo) -> bool:
        try:
            return bool(self._is_camera_active(camera.shm_name))
        except Exception as exc:
            logger.warning(
                f"[LogisticsChannelRuntime] 摄像头在线状态读取失败 "
                f"camera_id={camera.camera_id}: {exc}"
            )
            return False

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
        if snapshot.updated_at > now or now - snapshot.updated_at > self._stale_seconds:
            return "unknown", "stale"
        if snapshot.count is None:
            return "unknown", "inference_unknown"
        if snapshot.count == 0:
            return "empty", None
        if snapshot.count == 1:
            return "normal", None
        return "multiple", None

    @staticmethod
    def _compose_channel_frame(
        channel: _ChannelConfig,
        tiles: list[CameraTile],
    ) -> np.ndarray | None:
        if not tiles:
            return None
        try:
            return compose_channel_frame(tiles)
        except (ValueError, TypeError) as exc:
            logger.warning(
                f"[LogisticsChannelRuntime] 拼接失败 feature={channel.feature_name} "
                f"channel_id={channel.channel_id}: {exc}"
            )
            return None

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
            camera_key=f"logistics_channel:{channel.feature_name}:{channel.channel_id}",
            subject_type="logistics_channel",
            subject_id=str(channel.channel_id),
            subject_name=channel.name,
            reason=decision.reason,
            metadata=metadata,
        )

    def _reset_non_alarm_locked(self, channel: _ChannelConfig, reason: str) -> None:
        key = (channel.feature_name, channel.channel_id)
        state = self._states.get(key)
        if state is not None:
            state.reset()
        self._clear_incident_locked(channel)
        self._statuses[key] = {
            "feature_name": channel.feature_name,
            "channel_id": channel.channel_id,
            "channel_name": channel.name,
            "reason": reason,
            "alarm": False,
        }

    def _clear_incident_locked(self, channel: _ChannelConfig | None) -> None:
        if channel is None:
            return
        key = (channel.feature_name, channel.channel_id)
        if self._active_incidents.pop(key, None) is None:
            return
        reset = getattr(self._dispatcher, "reset_subject_cooldown", None)
        if callable(reset):
            reset("logistics_channel", str(channel.channel_id), channel.feature_name)


__all__ = ["LogisticsChannelRuntime"]
