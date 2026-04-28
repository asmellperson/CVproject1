"""
platform/alarm_device/service.py
喇叭设备 CRUD + 启动时加载所有已启用喇叭的运行时实例。
"""
from __future__ import annotations
from typing import Optional

from core.db import session_scope, get_session
from core.logger import logger
from core.alarm.horn import Horn
from .orm import AiHornConfig


class HornService:

    def list_horns(self, enabled_only: bool = False) -> list[dict]:
        session = get_session()
        try:
            q = session.query(AiHornConfig)
            if enabled_only:
                q = q.filter(AiHornConfig.enable.is_(True))
            return [self._to_dict(h) for h in q.all()]
        finally:
            session.close()

    def get_horn(self, horn_id: int) -> Optional[dict]:
        session = get_session()
        try:
            h = session.query(AiHornConfig).get(horn_id)
            return self._to_dict(h) if h else None
        finally:
            session.close()

    def create_horn(self, payload: dict) -> dict:
        with session_scope() as session:
            h = AiHornConfig(
                name=payload["name"],
                url=payload["url"],
                username=payload.get("username", "admin"),
                password=payload.get("password", "admin"),
                enable=bool(payload.get("enable", True)),
                description=payload.get("description"),
            )
            session.add(h)
            session.flush()
            return self._to_dict(h)

    def update_horn(self, horn_id: int, payload: dict) -> Optional[dict]:
        with session_scope() as session:
            h = session.query(AiHornConfig).get(horn_id)
            if h is None:
                return None
            for f in ("name", "url", "username", "password", "description"):
                if f in payload:
                    setattr(h, f, payload[f])
            if "enable" in payload:
                h.enable = bool(payload["enable"])
            return self._to_dict(h)

    def delete_horn(self, horn_id: int) -> bool:
        with session_scope() as session:
            h = session.query(AiHornConfig).get(horn_id)
            if h is None:
                return False
            session.delete(h)
            return True

    # ---------- Runtime ----------

    def load_runtime_instances(self) -> dict[int, Horn]:
        """启动时调用 — 实例化所有已启用的喇叭并启动心跳"""
        result: dict[int, Horn] = {}
        for cfg in self.list_horns(enabled_only=True):
            horn = Horn({
                "horn_url": cfg["url"],
                "username": cfg["username"],
                "password": cfg["password"],
            })
            horn.start_heartbeat()
            result[cfg["id"]] = horn
        logger.info(f"[HornService] 已加载 {len(result)} 个喇叭设备")
        return result

    @staticmethod
    def _to_dict(h: AiHornConfig) -> dict:
        return {
            "id": h.id,
            "name": h.name,
            "url": h.url,
            "username": h.username,
            "password": h.password,
            "enable": bool(h.enable),
            "description": h.description,
        }


horn_service = HornService()
