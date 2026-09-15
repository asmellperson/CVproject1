"""分别存储摄像头检测参数、物流通道配置与通道成员关系。"""
from __future__ import annotations

from sqlalchemy import (
    Boolean, Column, Float, ForeignKey, Integer, JSON, String, TIMESTAMP,
    Time, UniqueConstraint, text,
)
from sqlalchemy.orm import relationship

from AiVision.core.db import Base
from AiVision.features._shared.orm import CameraFeatureConfigBase
from AiVision.cameras.orm import AiCameraConfig
from AiVision.features._shared import defaults
from .constants import (
    DEFAULT_DETECTION_END, DEFAULT_DETECTION_START,
    DEFAULT_PERSON_CONFIDENCE_THRESHOLD, DEFAULT_EMPTY_GRACE_SECONDS,
    DEFAULT_MULTI_GRACE_SECONDS,
    DEFAULT_MODEL_IOU, DEFAULT_MIN_BOX_AREA, DEFAULT_ASPECT_RATIO_RANGE,
    DEFAULT_CAP_INTERVAL,
)


class LogisticsSinglePersonConfigORM(CameraFeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_logistics_single_person"

    cap_interval = Column(Float, default=DEFAULT_CAP_INTERVAL)
    IOU_THR = Column(Float, default=DEFAULT_MODEL_IOU)
    roi_pos = Column(JSON, nullable=False, default=list)
    MIN_BOX_AREA = Column(Integer, default=DEFAULT_MIN_BOX_AREA)
    ASPECT_RATIO_RANGE = Column(JSON, nullable=True, default=lambda: list(DEFAULT_ASPECT_RATIO_RANGE))


class LogisticsChannel(Base):
    """一个物流业务功能下的多摄像头检测通道。"""
    __tablename__ = "ai_logistics_channel"
    __table_args__ = (
        # 同一个 Feature、同一个事业部下，不能存在两个同名的物流通道
        UniqueConstraint("feature_name", "department", "name", name="uq_logistics_channel_feature_department_name"),
        {
            "comment": "物流通道配置表",
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
        },
    )
    # 功能名保留为运行时命名空间，事业部由通道明确声明
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="通道名称")
    feature_name = Column(String(128), nullable=False, index=True, comment="物流检测功能名")
    department = Column(String(100), nullable=False, index=True, comment="物流通道所属事业部")
    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用")
    # 排序，主要是前端展示顺序
    sort_order = Column(Integer, nullable=False, default=0, comment="展示排序")
    # 检测开始，默认早上八点
    detection_start = Column(Time, nullable=False, default=DEFAULT_DETECTION_START, comment="检测开始时间")
    # 默认晚上八点以后就不检测了
    detection_end = Column(Time, nullable=False, default=DEFAULT_DETECTION_END, comment="检测结束时间")
    # 人员置信度
    confidence_threshold = Column(
        Float,
        nullable=False,
        default=DEFAULT_PERSON_CONFIDENCE_THRESHOLD,
        comment="人体检测置信度阈值",
    )
    empty_grace_seconds = Column(Float, nullable=False, default=DEFAULT_EMPTY_GRACE_SECONDS, comment="无人告警宽限秒数")
    multi_grace_seconds = Column(Float, nullable=False, default=DEFAULT_MULTI_GRACE_SECONDS, comment="多人告警宽限秒数")
    # 报警间隔默认五秒
    alarm_interval = Column(Float, nullable=False, default=defaults.ALARM_INTERVAL, comment="告警间隔秒数")
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

    # 一个物流通道下面有哪些摄像头。channel.cameras与member.channel双向关联
    cameras = relationship(
        "LogisticsChannelCamera",
        back_populates="channel",
        cascade="all, delete-orphan",                   # 删除物流通道时，它下面的摄像头也要一起删除（不删除摄像头本身）
        passive_deletes=True,
        order_by="LogisticsChannelCamera.sort_order, LogisticsChannelCamera.id",
    )

class LogisticsChannelCamera(Base):
    """物流通道与摄像头的成员关系。"""
    __tablename__ = "ai_logistics_channel_camera"
    __table_args__ = (
        # 唯一约束，一个摄像头不能再同一个channel里重复添加两次（但是没有禁止一台摄像头同时在不同的通道）
        UniqueConstraint("channel_id", "camera_id", name="uq_logistics_channel_camera"),
        {
            "comment": "物流通道摄像头成员表",
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
        },
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 外键1：这条成员属于哪个channel
    channel_id = Column(
        Integer,
        ForeignKey("ai_logistics_channel.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="物流通道ID",
    )
    # 外键2： 绑定的是哪一台摄像头
    camera_id = Column(
        Integer,
        ForeignKey("ai_camera_config.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="摄像头ID",
    )
    # 物流实际有三层开关：1、摄像头资源是否启用，2、物流通道是否启用，3、这台摄像头是否在这个通道里
    enabled = Column(Boolean, nullable=False, default=True, comment="是否在通道内启用")
    # 摄像头在通道里面的排列顺序
    sort_order = Column(Integer, nullable=False, default=0, comment="通道内排序")
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
    # member.channel可以拿到摄像头对应的物流通道
    channel = relationship("LogisticsChannel", back_populates="cameras", passive_deletes=True)
    # member.camera可以拿到真实的摄像头ORM
    camera = relationship(AiCameraConfig, passive_deletes=True)
