# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：A named guard room / monitoring area under the guard behavior feature；输入与输出详见下方说明
# 参数：无。
# 返回：GuardRoomSite；返回新建的 `GuardRoomSite` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_site` 实例化本符号
#   - 内部调用：`UniqueConstraint`、`Column`、`String`、`text`、`relationship`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class GuardRoomSite(Base):
    """A named guard room / monitoring area under the guard behavior feature."""

    __tablename__ = "guard_room_site"
    __table_args__ = (
        UniqueConstraint("department", "name", name="uq_guard_room_site_department_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    department = Column(String(100), nullable=False, default="general_electric", index=True, comment="所属部门")
    name = Column(String(100), nullable=False, index=True, comment="保安室名称")
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


# 功能：A camera that belongs to one guard room site；输入与输出详见下方说明
# 参数：无。
# 返回：GuardRoomCamera；返回新建的 `GuardRoomCamera` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_camera` 实例化本符号
#   - 内部调用：`UniqueConstraint`、`Column`、`ForeignKey`、`String`、`text`、`relationship`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：Per-site configuration sections compatible with ``AppConfig``；输入与输出详见下方说明
# 参数：无。
# 返回：GuardRoomSiteConfig；返回新建的 `GuardRoomSiteConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_site`
#         实例化本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::update_site_config`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_site_service.py` 的
#         `test_site_service_replaces_orphan_config_when_sqlite_reuses_site_id` 实例化本符号
#   - 内部调用：`Column`、`ForeignKey`、`text`、`relationship`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
