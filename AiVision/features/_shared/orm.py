"""
features/_shared/orm.py
功能配置 ORM 基类

_CommonFieldsMixin: 摄像头功能开关、标识与时间戳。
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
from AiVision.features._shared import defaults

class _AlarmFieldsMixin:
    """由摄像头直接发起告警的功能共享字段。"""
    alarm_interval = Column(Float, default=defaults.ALARM_INTERVAL, comment="告警间隔(秒)")
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
    """摄像头功能配置共享字段，不包含告警职责。"""

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 这台摄像头是否启用了当前Feature（有一点区别：AiCameraConfig.enable：这台物理摄像头整体是否启用。FeatureConfig.enable：这台摄像头上的某一个检测功能是否启用）
    enable = Column(Boolean, default=False, comment="是否启用")
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

class CameraFeatureConfigBase(_CommonFieldsMixin, Base):
    """摄像头检测参数的持久化与序列化，不要求配置告警。"""

    __abstract__ = True
    _NON_VALUE_COLUMNS = frozenset({"id", "camera_id", "enable", "created_at", "updated_at"})

    def to_value_dict(self) -> dict:
        return {
            col.name: getattr(self, col.name)
            for col in self.__table__.columns
            if col.name not in self._NON_VALUE_COLUMNS
        }

    def apply_value_dict(self, value: dict):
        """写入入口已校验的检测参数；未知列直接报错。"""
        allowed = set(self.__table__.columns.keys()) - self._NON_VALUE_COLUMNS
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"未定义配置字段: {sorted(unknown)}")
        for key, val in value.items():
            setattr(self, key, val)

    def to_config_dict(self) -> dict:
        return {"enable": self.enable, "value": self.to_value_dict()}

    def apply_config_dict(self, config: dict):
        self.enable = config["enable"]
        self.apply_value_dict(config["value"])


class FeatureConfigBase(_AlarmFieldsMixin, CameraFeatureConfigBase):
    """具备摄像头级告警的功能配置基类；物流使用 CameraFeatureConfigBase。
    
    子类只需要:
    1. 设置 __tablename__
    2. 添加自己的特有字段(如 blocks 的 threshold,face 的 FACE_SCORE_THR)
    3. 不需要重复定义 enable/sql_enable/camera_id/created_at 等
    
    示例:
        class BlocksConfigORM(FeatureConfigBase):
            __tablename__ = "ai_camera_config_blocks"
            roi_pos = Column(JSON, nullable=False, default=list)
            threshold = Column(Float, default=0.1)
            ...
    """
    # FeatureConfigBase自己不是数据库表，这种表只给子类继承
    __abstract__ = True

    sort_order = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="功能内摄像头展示排序")
    cap_interval = Column(Float, default=defaults.CAP_INTERVAL, comment="采集间隔(秒)")

    def to_config_dict(self) -> dict:
        return {**super().to_config_dict(), "alarm": self.to_alarm_dict()}

    def apply_config_dict(self, config: dict):
        super().apply_config_dict(config)
        self.apply_alarm_dict(config["alarm"])

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
        "id", "camera_id", "enable", "sort_order",
        "sql_enable", "horn_enable", "horn_id", "horn_event_id",
        "wechat_enable", "wechat_user",
        "created_at", "updated_at",
    })
