"""物流通道及其摄像头成员的 SQLAlchemy ORM。"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, TIMESTAMP, Time, UniqueConstraint, text
from sqlalchemy.orm import relationship

from core.db import Base
from platform.camera.orm import AiCameraConfig
from .constants import (
    DEFAULT_DETECTION_END,
    DEFAULT_DETECTION_START,
    DEFAULT_PERSON_CONFIDENCE_THRESHOLD,
)


class LogisticsChannel(Base):
    """一个物流业务功能下的多摄像头检测通道。"""

    __tablename__ = "ai_logistics_channel"
    __table_args__ = (
        UniqueConstraint("feature_name", "name", name="uq_logistics_channel_feature_name"),
        {
            "comment": "物流通道配置表",
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
        },
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="通道名称")
    feature_name = Column(String(128), nullable=False, index=True, comment="物流检测功能名")
    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用")
    sort_order = Column(Integer, nullable=False, default=0, comment="展示排序")
    detection_start = Column(Time, nullable=False, default=DEFAULT_DETECTION_START, comment="检测开始时间")
    detection_end = Column(Time, nullable=False, default=DEFAULT_DETECTION_END, comment="检测结束时间")
    confidence_threshold = Column(
        Float,
        nullable=False,
        default=DEFAULT_PERSON_CONFIDENCE_THRESHOLD,
        comment="人体检测置信度阈值",
    )
    empty_grace_seconds = Column(Float, nullable=False, default=2.0, comment="无人告警宽限秒数")
    multi_grace_seconds = Column(Float, nullable=False, default=1.0, comment="多人告警宽限秒数")
    alarm_interval = Column(Float, nullable=False, default=5.0, comment="告警间隔秒数")
    sql_enable = Column(Boolean, nullable=False, default=False, comment="SQL告警启用")
    horn_enable = Column(Boolean, nullable=False, default=False, comment="喇叭告警启用")
    horn_id = Column(
        Integer,
        ForeignKey("ai_horn_config.id", ondelete="SET NULL"),
        nullable=True,
        comment="喇叭设备ID",
    )
    horn_event_id = Column(Integer, nullable=True, comment="告警音ID")
    wechat_enable = Column(Boolean, nullable=False, default=False, comment="微信告警启用")
    wechat_user = Column(String(255), nullable=True, comment="微信用户列表")
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    cameras = relationship(
        "LogisticsChannelCamera",
        back_populates="channel",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LogisticsChannelCamera.sort_order, LogisticsChannelCamera.id",
    )


class LogisticsChannelCamera(Base):
    """物流通道与摄像头的成员关系。"""

    __tablename__ = "ai_logistics_channel_camera"
    __table_args__ = (
        UniqueConstraint("channel_id", "camera_id", name="uq_logistics_channel_camera"),
        {
            "comment": "物流通道摄像头成员表",
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
        },
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(
        Integer,
        ForeignKey("ai_logistics_channel.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="物流通道ID",
    )
    camera_id = Column(
        Integer,
        ForeignKey("ai_camera_config.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="摄像头ID",
    )
    enabled = Column(Boolean, nullable=False, default=True, comment="是否在通道内启用")
    sort_order = Column(Integer, nullable=False, default=0, comment="通道内排序")
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    channel = relationship("LogisticsChannel", back_populates="cameras", passive_deletes=True)
    camera = relationship(AiCameraConfig, passive_deletes=True)
