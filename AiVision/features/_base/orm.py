"""
features/_base/orm.py
功能配置 ORM 基类

_CommonFieldMixmin: 声明id，摄像头id、enable、cap_interval 、 alarm_interval、created_at 、updated_at等普通公共字段
_AlarmFieldMixin: 声明sql_enable、horn_enable、horn_id 、horn_event_id、wechat_enable、wechat_user等告警字段

用 SQLAlchemy mixin + 抽象基类把这些字段抽出来。
每个 features/{name}/orm.py 只需要定义自己的特有字段。
"""
from __future__ import annotations
from sqlalchemy import (
    Column, Integer, Boolean, Float, String, TIMESTAMP, ForeignKey, text
)
from sqlalchemy.orm import declared_attr
from AiVision.core.db import Base

class _AlarmFieldsMixin:
    """所有功能配置表共享的告警字段。"""
    # Feature触发告警后，要不要保存数据库告警记录
    sql_enable = Column(Boolean, default=False, comment="SQL告警启用")
    # 要不要触发喇叭告警
    horn_enable = Column(Boolean, default=False, comment="喇叭告警启用")

    # declared_attr 会让 SQLAlchemy 在每个真实 ORM 子类生成自己那份 Column
    @declared_attr
    def horn_id(cls):
        return Column(
            Integer,
            ForeignKey("ai_horn_config.id", ondelete="SET NULL"),    # ondelete="SET NULL"：删除一个喇叭设备不应该把整条记录删掉
            nullable=True,
            comment="喇叭设备ID",
        )

    horn_event_id = Column(Integer, nullable=True, comment="告警音ID")
    # 要不要发企业微信
    wechat_enable = Column(Boolean, default=False, comment="微信告警启用")
    wechat_user = Column(String(255), nullable=True, comment="微信用户列表")

class _CommonFieldsMixin:
    """所有功能配置表共享的通用字段(ID、camera_id、enable、采集/告警间隔、时间戳)。"""

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 这台摄像头是否启用了当前Feature（有一点区别：AiCameraConfig.enable：这台物理摄像头整体是否启用。FeatureConfig.enable：这台摄像头上的某一个检测功能是否启用）
    enable = Column(Boolean, default=False, comment="是否启用")
    cap_interval = Column(Float, default=0.1, comment="采集间隔(秒)")
    alarm_interval = Column(Float, default=5.0, comment="告警间隔(秒)")
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    @declared_attr
    def camera_id(cls):
        return Column(
            Integer,
            ForeignKey("ai_camera_config.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,                           # 同一个功能表里，一台摄像头最多只能有一条配置
            index=True,
            comment="摄像头ID",
        )

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
    # FeatureConfigBase自己不是数据库表，这种表只给子类继承
    __abstract__ = True

    # ----------------- 做ORM <-> API数据转换 --------------------
    def to_alarm_dict(self) -> dict:
        """提取告警配置为前端需要的嵌套结构（ORM平铺字段转换API嵌套结构）"""
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

    def apply_alarm_dict(self, alarm: dict):
        """从前端嵌套结构反向写回 ORM 字段（与to_alarm_dict相反）"""
        sql = alarm.get("sql", {}) or {}
        horn = alarm.get("horn", {}) or {}
        wechat = alarm.get("wechat", {}) or {}
        self.sql_enable = sql.get("enable", False)
        self.horn_enable = horn.get("enable", False)
        horn_parm = horn.get("parm") or {}
        if "horn_id" in horn_parm:
            self.horn_id = horn_parm["horn_id"]
        if "horn_event_id" in horn_parm:
            self.horn_event_id = horn_parm["horn_event_id"]
        self.wechat_enable = wechat.get("enable", False)
        self.wechat_user = (wechat.get("parm") or {}).get("user", "")

    # 这些是非告警、非元数据的列名（哪些字段不属于Feature自己的检测参数） — 提取 value 字典时排除
    _NON_VALUE_COLUMNS: frozenset[str] = frozenset({
        "id", "camera_id", "enable",
        "sql_enable", "horn_enable", "horn_id", "horn_event_id",
        "wechat_enable", "wechat_user",
        "created_at", "updated_at",
    })

    def to_value_dict(self) -> dict:
        """提取功能特有参数(roi_pos, threshold, ...)"""
        return {
            col.name: getattr(self, col.name)
            for col in self.__table__.columns      # 遍历表的所有字段
            if col.name not in self._NON_VALUE_COLUMNS
        }

    def apply_value_dict(self, value: dict):
        """从前端 value 字典写回 ORM(只写已知字段)"""
        for key, val in (value or {}).items():
            if hasattr(self, key) and key not in self._NON_VALUE_COLUMNS:    # hasattr安全限制
                setattr(self, key, val)
