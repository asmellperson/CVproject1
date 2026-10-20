"""数据库中的系统异常通知策略，与启动时读取的 Settings 分开管理。

AiSystemConfig 按 key 保存 JSON，SystemConfigService 提供默认值补齐、间隔校验和事务写入。
服务保存不会自行发出异常通知或刷新摄像头配置；运行层和 API 在需要时读取当前策略。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Column, JSON, String

from AiVision.core.db import Base, session_scope, get_session
from AiVision.core.config_revision import require_configuration_values


class AiSystemConfig(Base):
    """按配置名称保存整块 JSON 的系统配置表，具体字段校验由所属 Service 负责。"""
    __tablename__ = "ai_system_config"

    key = Column(String(100), primary_key=True)         # 配置叫什么
    value = Column(JSON, nullable=True)                 # 整块json配置（比如系统异常告警是一个组："wechat_enable"，"wechat_user"， "repeat_interval_minutes"）

# ai_system_config表的业务访问层，目前主要只有异常告警配置
class SystemConfigService:
    """读写 exception_alert 通知策略，统一约束微信接收人和重复通知间隔。"""
    EXCEPTION_ALERT_KEY = "exception_alert"               # 数据库key
    DEFAULT_EXCEPTION_ALERT_INTERVAL_MINUTES = 60         # 默认重复告警间隔
    MIN_EXCEPTION_ALERT_INTERVAL_MINUTES = 5              # 最短
    MAX_EXCEPTION_ALERT_INTERVAL_MINUTES = 24 * 60        # 最长

    def get_exception_alert(self) -> dict[str, Any]:
        """从数据库读取exception_alert"""
        value = self._get_value(self.EXCEPTION_ALERT_KEY)
        return self._exception_alert_values(value)

    def _exception_alert_values(self, value) -> dict[str, Any]:
        if not isinstance(value, dict):
            value = {}
        # 哪怕数据库没配置也会返回这个
        return {
            "wechat_enable": bool(value.get("wechat_enable", False)),
            "wechat_user": str(value.get("wechat_user") or ""),
            "repeat_interval_minutes": self._normalize_exception_alert_interval(
                value.get("repeat_interval_minutes", self.DEFAULT_EXCEPTION_ALERT_INTERVAL_MINUTES)
            ),
        }

    def save_exception_alert(self, payload: dict[str, Any], *, expected_values: dict | None = None) -> dict[str, Any]:
        """写操作，API更新路由调用的是这个方法"""
        value = {
            "wechat_enable": bool(payload.get("wechat_enable", False)),
            "wechat_user": str(payload.get("wechat_user") or "").strip(),
            "repeat_interval_minutes": self._normalize_exception_alert_interval(
                payload.get("repeat_interval_minutes", self.DEFAULT_EXCEPTION_ALERT_INTERVAL_MINUTES)
            ),
        }
        if value["wechat_enable"] and not value["wechat_user"]:
            raise ValueError("wechat_user 不能为空")
        # 写数据库
        with session_scope() as session:
            row = session.get(AiSystemConfig, self.EXCEPTION_ALERT_KEY, with_for_update=True)
            require_configuration_values(self._exception_alert_values(row.value if row else None), expected_values)
            if row is None:
                session.add(AiSystemConfig(key=self.EXCEPTION_ALERT_KEY, value=value))
            else:
                row.value = value
        return value

    def _normalize_exception_alert_interval(self, raw_value: Any) -> int:
        """负责告警间隔的校验"""
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
        """从数据库获取值"""
        session = get_session()
        try:
            row = session.query(AiSystemConfig).filter_by(key=key).first()
            return row.value if row is not None else None
        finally:
            session.close()

    @staticmethod
    def _set_value(key: str, value):
        """供 SIP 等配置服务复用的事务写入入口。"""
        with session_scope() as session:
            row = session.get(AiSystemConfig, key, with_for_update=True)
            if row is None:
                session.add(AiSystemConfig(key=key, value=value))
            else:
                row.value = value

system_config_service = SystemConfigService()
