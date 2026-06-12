"""Runtime manager for multiple Guard Room sites."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Type

from .config import AppConfig
from .runtime import GuardRoomRuntime
from .service import GuardRoomService
from .state import AppState
from .types import AlarmEvent
from .wechat_notifier import WeChatNotifier


class SiteAppState(AppState):
    """AppState that annotates status and alarms with site metadata."""

    def __init__(self, cfg: AppConfig, config_path: str | Path, *, site_id: int, site_name: str):
        super().__init__(cfg, config_path=config_path)
        self.site_id = int(site_id)
        self.site_name = site_name

    def set_site(self, site_id: int, site_name: str) -> None:
        with self._lock:
            self.site_id = int(site_id)
            self.site_name = site_name

    def get_status(self) -> dict[str, Any]:
        payload = super().get_status()
        payload["site_id"] = self.site_id
        payload["site_name"] = self.site_name
        if payload.get("last_alarm"):
            payload["last_alarm"] = self._with_site(payload["last_alarm"])
        return payload

    def add_alarm(self, alarm: AlarmEvent) -> dict[str, Any]:
        payload = super().add_alarm(alarm)
        with self._lock:
            payload["site_id"] = self.site_id
            payload["site_name"] = self.site_name
            if self.last_alarm is not None:
                self.last_alarm["site_id"] = self.site_id
                self.last_alarm["site_name"] = self.site_name
        return payload

    def get_alarms(self, limit: int = 50) -> list[dict[str, Any]]:
        return [self._with_site(item) for item in super().get_alarms(limit=limit)]

    def get_alarm(self, alarm_id: str) -> dict[str, Any] | None:
        alarm = super().get_alarm(alarm_id)
        return self._with_site(alarm) if alarm else None

    def get_statistics(self) -> dict[str, Any]:
        payload = super().get_statistics()
        payload["site_id"] = self.site_id
        payload["site_name"] = self.site_name
        return payload

    def _with_site(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            **item,
            "site_id": item.get("site_id", self.site_id),
            "site_name": item.get("site_name", self.site_name),
        }


@dataclass
class RuntimeContext:
    site_id: int
    site_name: str
    cfg: AppConfig
    state: SiteAppState
    runtime: GuardRoomRuntime
    wechat_notifier: WeChatNotifier | None = None


class GuardRoomRuntimeManager:
    """Owns one ``GuardRoomRuntime`` per guard-room site."""

    def __init__(
        self,
        service: GuardRoomService,
        *,
        runtime_cls: Type[GuardRoomRuntime] = GuardRoomRuntime,
        notifier_cls: Type[WeChatNotifier] = WeChatNotifier,
    ):
        self.service = service
        self.runtime_cls = runtime_cls
        self.notifier_cls = notifier_cls
        self._contexts: dict[int, RuntimeContext] = {}
        self._lock = threading.RLock()

    def start(self, site_id: int) -> dict[str, Any]:
        """Start one site's runtime and return its status."""
        with self._lock:
            context = self._get_or_create_context(site_id, rebuild=not self._is_running(site_id))
            context.runtime.start()
            return context.state.get_status()

    def stop(self, site_id: int) -> dict[str, Any]:
        """Stop one site's runtime and return its status."""
        with self._lock:
            context = self._contexts.get(site_id)
            if context is None:
                context = self._get_or_create_context(site_id, rebuild=True)
            context.runtime.stop()
            self._stop_notifier(context)
            return context.state.get_status()

    def restart(self, site_id: int) -> dict[str, Any]:
        """Rebuild config from DB, restart one site, and return status."""
        with self._lock:
            old_context = self._contexts.get(site_id)
            if old_context is not None:
                old_context.runtime.stop()
                self._stop_notifier(old_context)
                self._contexts.pop(site_id, None)
            context = self._get_or_create_context(site_id, rebuild=True)
            context.runtime.start()
            return context.state.get_status()

    def get_status(self, site_id: int) -> dict[str, Any]:
        with self._lock:
            return self._get_or_create_context(site_id).state.get_status()

    def get_state(self, site_id: int) -> SiteAppState:
        with self._lock:
            return self._get_or_create_context(site_id).state

    def get_latest_frame(self, site_id: int) -> bytes:
        return self.get_state(site_id).get_latest_frame()

    def get_alarms(self, site_id: int, limit: int = 50) -> list[dict[str, Any]]:
        return self.get_state(site_id).get_alarms(limit=limit)

    def get_alarm(self, site_id: int, alarm_id: str) -> dict[str, Any] | None:
        return self.get_state(site_id).get_alarm(alarm_id)

    def get_statistics(self, site_id: int) -> dict[str, Any]:
        return self.get_state(site_id).get_statistics()

    def stop_all(self) -> None:
        """Stop all managed runtimes."""
        with self._lock:
            for context in list(self._contexts.values()):
                context.runtime.stop()
                self._stop_notifier(context)

    def _get_or_create_context(self, site_id: int, *, rebuild: bool = False) -> RuntimeContext:
        site_id = int(site_id)
        if not rebuild and site_id in self._contexts:
            return self._contexts[site_id]

        site = self.service.get_site(site_id, include_config=False)
        if site is None:
            raise ValueError(f"保安室不存在: {site_id}")

        cfg = self.service.build_app_config(site_id)
        config_path = f"db://guard_room_site/{site_id}"
        state = SiteAppState(cfg, config_path=config_path, site_id=site_id, site_name=site["name"])

        wechat_notifier = None
        if cfg.wechat.enable:
            wechat_notifier = self.notifier_cls(
                corpid=cfg.wechat.corpid,
                corpsecret=cfg.wechat.corpsecret,
                agentid=cfg.wechat.agentid,
            )

        runtime = self.runtime_cls(
            config=cfg,
            state=state,
            wechat_notifier=wechat_notifier,
            alarm_user=cfg.wechat.alarm_user,
            alarm_camera_name=cfg.wechat.camera_name or site["name"],
        )
        context = RuntimeContext(
            site_id=site_id,
            site_name=site["name"],
            cfg=cfg,
            state=state,
            runtime=runtime,
            wechat_notifier=wechat_notifier,
        )
        self._contexts[site_id] = context
        return context

    def _is_running(self, site_id: int) -> bool:
        context = self._contexts.get(site_id)
        return bool(context and getattr(context.runtime, "is_running", False))

    @staticmethod
    def _stop_notifier(context: RuntimeContext) -> None:
        notifier = context.wechat_notifier
        if notifier is not None and hasattr(notifier, "stop"):
            notifier.stop()
        context.wechat_notifier = None
