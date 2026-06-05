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

    def get_exception_alert(self) -> dict[str, Any]:
        value = self._get_value(self.EXCEPTION_ALERT_KEY)
        if not isinstance(value, dict):
            value = {}
        return {
            "wechat_enable": bool(value.get("wechat_enable", False)),
            "wechat_user": str(value.get("wechat_user") or ""),
        }

    def save_exception_alert(self, payload: dict[str, Any]) -> dict[str, Any]:
        value = {
            "wechat_enable": bool(payload.get("wechat_enable", False)),
            "wechat_user": str(payload.get("wechat_user") or "").strip(),
        }
        if value["wechat_enable"] and not value["wechat_user"]:
            raise ValueError("wechat_user 不能为空")
        self._set_value(self.EXCEPTION_ALERT_KEY, value)
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
