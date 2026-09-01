# 文件说明：实现配置相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
core/system_config.py
系统级运行配置，用于保存系统异常告警等跨模块配置。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Column, JSON, String

from core.db import Base, session_scope, get_session


# 功能：定义 `AiSystemConfig` 类，封装配置相关的状态、约束与操作
# 参数：无。
# 返回：AiSystemConfig；返回新建的 `AiSystemConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/system_config.py` 的 `SystemConfigService::_set_value` 实例化本符号
#   - 内部调用：`Column`、`String`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AiSystemConfig(Base):
    __tablename__ = "ai_system_config"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=True)


# 功能：定义 `SystemConfigService` 类，封装配置相关的状态、约束与操作
# 参数：无。
# 返回：SystemConfigService；返回新建的 `SystemConfigService` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_system_config.py` 的 `test_exception_alert_defaults_to_one_hour_repeat_interval`
#         实例化本符号；`AiVision/tests/test_system_config.py` 的 `test_exception_alert_saves_repeat_interval`
#         实例化本符号；`AiVision/tests/test_system_config.py` 的 `test_exception_alert_rejects_invalid_repeat_interval`
#         实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class SystemConfigService:
    EXCEPTION_ALERT_KEY = "exception_alert"
    DEFAULT_EXCEPTION_ALERT_INTERVAL_MINUTES = 60
    MIN_EXCEPTION_ALERT_INTERVAL_MINUTES = 5
    MAX_EXCEPTION_ALERT_INTERVAL_MINUTES = 24 * 60

    # 功能：读取或查询 `get_exception_alert` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._get_value`、`isinstance`、`bool`、`value.get`、`str`、`self._normalize_exception_alert_interval`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：更新或保存 `save_exception_alert` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_system_config.py` 的 `test_exception_alert_saves_repeat_interval`
    #         调用本符号；`AiVision/tests/test_system_config.py` 的 `test_exception_alert_rejects_invalid_repeat_interval`
    #         调用本符号；`AiVision/api/v2/runtime.py` 的 `update_exception_alert` 调用本符号
    #   - 内部调用：`bool`、`payload.get`、`str(payload.get('wechat_user') or
    #          '').strip`、`str`、`self._normalize_exception_alert_interval`、`ValueError`、`self._set_value`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；校验或执行失败时会主动抛出异常。
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

    # 功能：转换或规范化 `_normalize_exception_alert_interval` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `raw_value`（Any）：`raw_value` 对应的业务输入值
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/system_config.py` 的 `SystemConfigService::get_exception_alert` 调用本符号；`AiVision/core/system_config.py` 的
    #         `SystemConfigService::save_exception_alert` 调用本符号
    #   - 内部调用：`int`、`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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

    # 功能：读取或查询 `_get_value` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/system_config.py` 的 `SystemConfigService::get_exception_alert` 调用本符号
    #   - 内部调用：`get_session`、`session.query(AiSystemConfig).filter_by(key=key).first`、`session.query(AiSystemConfig).filter_by`、`session.query`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _get_value(self, key: str):
        session = get_session()
        try:
            row = session.query(AiSystemConfig).filter_by(key=key).first()
            return row.value if row is not None else None
        finally:
            session.close()

    # 功能：更新或保存 `_set_value` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `key`（str）：用于查询、分组或缓存的键
    #   - `value`（未显式标注）：待转换、校验或写入的值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/core/system_config.py` 的 `SystemConfigService::save_exception_alert` 调用本符号
    #   - 内部调用：`session_scope`、`session.query(AiSystemConfig).filter_by(key=key).first`、`session.query(AiSystemConfig).filter_by`、`session.query`、`session.add`、`AiSystemConfig`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    @staticmethod
    def _set_value(key: str, value):
        with session_scope() as session:
            row = session.query(AiSystemConfig).filter_by(key=key).first()
            if row is None:
                session.add(AiSystemConfig(key=key, value=value))
            else:
                row.value = value


system_config_service = SystemConfigService()
