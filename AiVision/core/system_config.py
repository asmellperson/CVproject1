"""
core/system_config.py
系统级运行配置,用于保存不属于单个摄像头或单个功能的全局开关。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Column, JSON, String

from core.db import Base, session_scope, get_session


class AiSystemConfig(Base):
    __tablename__ = "ai_system_config"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=True)


class SystemConfigService:
    EXCEPTION_ALERT_KEY = "exception_alert"
    DEFAULT_EXCEPTION_ALERT_INTERVAL_MINUTES = 60
    MIN_EXCEPTION_ALERT_INTERVAL_MINUTES = 5
    MAX_EXCEPTION_ALERT_INTERVAL_MINUTES = 24 * 60

    def get_exception_alert(self) -> dict[str, Any]:
        value = self._get_value(self.EXCEPTION_ALERT_KEY)
        if not isinstance(value, dict):
            value = {}
        return {
            "wechat_enable": bool(value.get("wechat_enable", False)),
            "wechat_user": str(value.get("wechat_user") or ""),
            "repeat_interval_minutes": self._normalize_exception_alert_interval(
                value.get("repeat_interval_minutes", self.DEFAULT_EXCEPTION_ALERT_INTERVAL_MINUTES)
            ),
        }

    def save_exception_alert(self, payload: dict[str, Any]) -> dict[str, Any]:
        value = {
            "wechat_enable": bool(payload.get("wechat_enable", False)),
            "wechat_user": str(payload.get("wechat_user") or "").strip(),
            "repeat_interval_minutes": self._normalize_exception_alert_interval(
                payload.get("repeat_interval_minutes", self.DEFAULT_EXCEPTION_ALERT_INTERVAL_MINUTES)
            ),
        }
        if value["wechat_enable"] and not value["wechat_user"]:
            raise ValueError("wechat_user 不能为空")
        self._set_value(self.EXCEPTION_ALERT_KEY, value)
        return value

    def _normalize_exception_alert_interval(self, raw_value: Any) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("repeat_interval_minutes 必须是整数") from exc
        if not self.MIN_EXCEPTION_ALERT_INTERVAL_MINUTES <= value <= self.MAX_EXCEPTION_ALERT_INTERVAL_MINUTES:
            raise ValueError(
                "repeat_interval_minutes 必须在 "
                f"{self.MIN_EXCEPTION_ALERT_INTERVAL_MINUTES} 到 "
                f"{self.MAX_EXCEPTION_ALERT_INTERVAL_MINUTES} 分钟之间"
            )
        return value

    def _get_value(self, key: str):
        session = get_session()
        try:
            row = session.query(AiSystemConfig).filter_by(key=key).first()
            return row.value if row is not None else None
        finally:
            session.close()

    @staticmethod
    def _set_value(key: str, value):
        with session_scope() as session:
            row = session.query(AiSystemConfig).filter_by(key=key).first()
            if row is None:
                session.add(AiSystemConfig(key=key, value=value))
            else:
                row.value = value


system_config_service = SystemConfigService()
