# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
features/_base/orm.py
功能配置 ORM 基类 — 消除 5 个功能配置表的字段重复。

旧代码里 AiCameraConfigBlocks / AiCameraConfigDetectFace / ... 这 5 个表
都有完全相同的告警字段(sql_enable, horn_enable, horn_id, ...) — 一字不差地重复了 5 遍。

新架构用 SQLAlchemy mixin + 抽象基类把这些字段抽出来。
每个 features/{name}/orm.py 只需要定义自己的特有字段。
"""
from __future__ import annotations
from sqlalchemy import (
    Column, Integer, Boolean, Float, String, TIMESTAMP, ForeignKey, text
)
from sqlalchemy.orm import declared_attr
from core.db import Base


# 功能：所有功能配置表共享的告警字段；输入与输出详见下方说明
# 参数：无。
# 返回：_AlarmFieldsMixin；返回新建的 `_AlarmFieldsMixin` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Column`、`String`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class _AlarmFieldsMixin:
    """所有功能配置表共享的告警字段。"""

    sql_enable = Column(Boolean, default=False, comment="SQL告警启用")
    horn_enable = Column(Boolean, default=False, comment="喇叭告警启用")

    # 功能：实现 `horn_id` 对应的数据库模型逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Column`、`ForeignKey`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @declared_attr
    def horn_id(cls):
        return Column(
            Integer,
            ForeignKey("ai_horn_config.id", ondelete="SET NULL"),
            nullable=True,
            comment="喇叭设备ID",
        )

    horn_event_id = Column(Integer, nullable=True, comment="告警音ID")
    wechat_enable = Column(Boolean, default=False, comment="微信告警启用")
    wechat_user = Column(String(255), nullable=True, comment="微信用户列表")


# 功能：所有功能配置表共享的通用字段(ID、camera_id、enable、采集/告警间隔、时间戳)；输入与输出详见下方说明
# 参数：无。
# 返回：_CommonFieldsMixin；返回新建的 `_CommonFieldsMixin` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Column`、`text`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class _CommonFieldsMixin:
    """所有功能配置表共享的通用字段(ID、camera_id、enable、采集/告警间隔、时间戳)。"""

    id = Column(Integer, primary_key=True, autoincrement=True)
    enable = Column(Boolean, default=False, comment="是否启用")
    cap_interval = Column(Float, default=0.1, comment="采集间隔(秒)")
    alarm_interval = Column(Float, default=5.0, comment="告警间隔(秒)")
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    # 功能：实现 `camera_id` 对应的数据库模型逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Column`、`ForeignKey`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @declared_attr
    def camera_id(cls):
        return Column(
            Integer,
            ForeignKey("ai_camera_config.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
            comment="摄像头ID",
        )


# 功能：所有功能配置表的抽象基类；输入与输出详见下方说明
# 参数：无。
# 返回：FeatureConfigBase；返回新建的 `FeatureConfigBase` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`frozenset`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FeatureConfigBase(_CommonFieldsMixin, _AlarmFieldsMixin, Base):
    """所有功能配置表的抽象基类。
    
    子类只需要:
    1. 设置 __tablename__
    2. 添加自己的特有字段(如 blocks 的 threshold,face 的 FACE_SCORE_THR)
    3. 不需要重复定义 enable/sql_enable/camera_id/created_at 等
    
    示例:
        class BlocksConfigORM(FeatureConfigBase):
            __tablename__ = "ai_camera_config_blocks"
            roi_pos = Column(JSON, nullable=True)
            threshold = Column(Float, default=0.1)
            blur_kernel = Column(Integer, default=5)
            ...
    """
    __abstract__ = True

    # 通用工具方法

    # 功能：提取告警配置为前端需要的嵌套结构；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/config_manager.py` 的 `FeatureConfigManager::get_config` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def to_alarm_dict(self) -> dict:
        """提取告警配置为前端需要的嵌套结构"""
        return {
            "sql": {"enable": self.sql_enable, "parm": {}},
            "horn": {
                "enable": self.horn_enable,
                "parm": {
                    "horn_id": self.horn_id,
                    "horn_event_id": self.horn_event_id,
                },
            },
            "wechat": {
                "enable": self.wechat_enable,
                "parm": {"user": self.wechat_user or ""},
            },
        }

    # 功能：从前端嵌套结构反向写回 ORM 字段；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `alarm`（dict）：`alarm` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/config_manager.py` 的 `FeatureConfigManager::save_config` 调用本符号
    #   - 内部调用：`alarm.get`、`sql.get`、`horn.get`、`(horn.get('parm') or {}).get`、`wechat.get`、`(wechat.get('parm') or {}).get`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能发起网络请求或发送外部消息。
    def apply_alarm_dict(self, alarm: dict):
        """从前端嵌套结构反向写回 ORM 字段"""
        sql = alarm.get("sql", {}) or {}
        horn = alarm.get("horn", {}) or {}
        wechat = alarm.get("wechat", {}) or {}
        self.sql_enable = sql.get("enable", False)
        self.horn_enable = horn.get("enable", False)
        self.horn_id = (horn.get("parm") or {}).get("horn_id")
        self.horn_event_id = (horn.get("parm") or {}).get("horn_event_id")
        self.wechat_enable = wechat.get("enable", False)
        self.wechat_user = (wechat.get("parm") or {}).get("user", "")

    # 这些是非告警、非元数据的列名 — 提取 value 字典时排除
    _NON_VALUE_COLUMNS: frozenset[str] = frozenset({
        "id", "camera_id", "enable",
        "sql_enable", "horn_enable", "horn_id", "horn_event_id",
        "wechat_enable", "wechat_user",
        "created_at", "updated_at",
    })

    # 功能：提取功能特有参数(roi_pos, threshold, ...)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/config_manager.py` 的 `FeatureConfigManager::get_config` 调用本符号
    #   - 内部调用：`getattr`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def to_value_dict(self) -> dict:
        """提取功能特有参数(roi_pos, threshold, ...)"""
        return {
            col.name: getattr(self, col.name)
            for col in self.__table__.columns
            if col.name not in self._NON_VALUE_COLUMNS
        }

    # 功能：从前端 value 字典写回 ORM(只写已知字段)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `value`（dict）：待转换、校验或写入的值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/config_manager.py` 的 `FeatureConfigManager::save_config` 调用本符号
    #   - 内部调用：`(value or {}).items`、`hasattr`、`setattr`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def apply_value_dict(self, value: dict):
        """从前端 value 字典写回 ORM(只写已知字段)"""
        for key, val in (value or {}).items():
            if hasattr(self, key) and key not in self._NON_VALUE_COLUMNS:
                setattr(self, key, val)
