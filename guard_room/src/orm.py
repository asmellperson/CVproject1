"""SQLAlchemy ORM models for Guard Room sites and grouped cameras."""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from .db import Base


class GuardRoomSite(Base):
    """A named guard room / monitoring area under the guard behavior feature."""

    __tablename__ = "guard_room_site"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True, comment="保安室名称")
    enabled = Column(Boolean, nullable=False, default=True, index=True, comment="是否启用")
    sort_order = Column(Integer, nullable=False, default=0, comment="显示排序")
    description = Column(Text, nullable=True, comment="备注")
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    cameras = relationship(
        "GuardRoomCamera",
        back_populates="site",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GuardRoomCamera.sort_order",
    )
    config = relationship(
        "GuardRoomSiteConfig",
        back_populates="site",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class GuardRoomCamera(Base):
    """A camera that belongs to one guard room site."""

    __tablename__ = "guard_room_camera"
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_guard_room_camera_site_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(
        Integer,
        ForeignKey("guard_room_site.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属保安室ID",
    )
    name = Column(String(100), nullable=False, comment="摄像头名称")
    rtsp_url = Column(String(500), nullable=False, comment="RTSP地址")
    enabled = Column(Boolean, nullable=False, default=True, index=True, comment="是否启用")
    sort_order = Column(Integer, nullable=False, default=0, comment="显示/拼接排序")
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    site = relationship("GuardRoomSite", back_populates="cameras")


class GuardRoomSiteConfig(Base):
    """Per-site configuration sections compatible with ``AppConfig``."""

    __tablename__ = "guard_room_site_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(
        Integer,
        ForeignKey("guard_room_site.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="所属保安室ID",
    )
    video_json = Column(JSON, nullable=False, comment="视频运行参数，不含摄像头RTSP列表")
    models_json = Column(JSON, nullable=False, comment="模型配置")
    room_json = Column(JSON, nullable=False, comment="画面/房间配置")
    rules_json = Column(JSON, nullable=False, comment="行为规则配置")
    classes_json = Column(JSON, nullable=False, comment="类别映射配置")
    runtime_json = Column(JSON, nullable=False, comment="运行时配置")
    wechat_json = Column(JSON, nullable=False, comment="企业微信配置")
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    site = relationship("GuardRoomSite", back_populates="config")
