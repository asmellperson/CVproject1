"""保安室业务对象、成员及显式策略；物理摄像头仍由平台管理。"""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Double, ForeignKey, Integer, JSON,
    String, TIMESTAMP, UniqueConstraint, text,
)
from sqlalchemy.orm import relationship

from AiVision.alarms.devices.orm import AiHornConfig
from AiVision.cameras.orm import AiCameraConfig
from AiVision.core.db import Base
from AiVision.features._shared.orm import CameraFeatureConfigBase
from .constants import ALARM_POLICY_DEFAULTS, GUARD_ALARM_TYPES, SITE_POLICY_DEFAULTS, default_alarm_interval


class _Timestamps:
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"),
                        onupdate=text("CURRENT_TIMESTAMP"))


class GuardBehaviorSite(_Timestamps, Base):
    __tablename__ = "ai_guard_behavior_site"
    __table_args__ = (
        UniqueConstraint("department", "name", name="uq_guard_behavior_site_department_name"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    department = Column(String(100), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)

    cameras = relationship("GuardBehaviorSiteCamera", back_populates="site",
                           passive_deletes=True, cascade="all, delete-orphan",
                           order_by="GuardBehaviorSiteCamera.sort_order, GuardBehaviorSiteCamera.id")
    policy = relationship("GuardBehaviorSitePolicy", back_populates="site", uselist=False,
                          passive_deletes=True, cascade="all, delete-orphan")
    alarm_policies = relationship("GuardBehaviorAlarmPolicy", back_populates="site",
                                  passive_deletes=True, cascade="all, delete-orphan",
                                  order_by="GuardBehaviorAlarmPolicy.violation_type")


class GuardBehaviorSiteCamera(_Timestamps, Base):
    __tablename__ = "ai_guard_behavior_site_camera"
    __table_args__ = (
        UniqueConstraint("site_id", "camera_id", name="uq_guard_behavior_site_camera"),
        UniqueConstraint("camera_id", name="uq_guard_behavior_camera_owner"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("ai_guard_behavior_site.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    camera_id = Column(Integer, ForeignKey(AiCameraConfig.id, ondelete="CASCADE"), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)

    site = relationship(GuardBehaviorSite, back_populates="cameras")
    camera = relationship(AiCameraConfig)


class GuardBehaviorCameraConfig(CameraFeatureConfigBase):
    __tablename__ = "ai_camera_config_guard_behavior"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    vehicle_roi_pos = Column(JSON, nullable=False, default=list)


class GuardBehaviorSitePolicy(_Timestamps, Base):
    __tablename__ = "ai_guard_behavior_site_policy"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("ai_guard_behavior_site.id", ondelete="CASCADE"),
                     nullable=False, unique=True)
    cap_interval = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["cap_interval"])
    person_confidence_threshold = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["person_confidence_threshold"])
    phone_confidence_threshold = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["phone_confidence_threshold"])
    uniform_confidence_threshold = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["uniform_confidence_threshold"])
    vehicle_confidence_threshold = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["vehicle_confidence_threshold"])
    model_iou_threshold = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["model_iou_threshold"])
    person_phone_imgsz = Column(Integer, nullable=False, default=SITE_POLICY_DEFAULTS["person_phone_imgsz"])
    phone_crop_imgsz = Column(Integer, nullable=False, default=SITE_POLICY_DEFAULTS["phone_crop_imgsz"])
    pose_imgsz = Column(Integer, nullable=False, default=SITE_POLICY_DEFAULTS["pose_imgsz"])
    vehicle_imgsz = Column(Integer, nullable=False, default=SITE_POLICY_DEFAULTS["vehicle_imgsz"])
    guard_hold_seconds = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["guard_hold_seconds"])
    absent_alarm_seconds = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["absent_alarm_seconds"])
    phone_seconds = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["phone_seconds"])
    phone_window_seconds = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["phone_window_seconds"])
    phone_min_hits_in_window = Column(Integer, nullable=False, default=SITE_POLICY_DEFAULTS["phone_min_hits_in_window"])
    phone_grace_seconds = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["phone_grace_seconds"])
    phone_near_person_px = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["phone_near_person_px"])
    phone_near_head_px = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["phone_near_head_px"])
    prone_sleep_seconds = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["prone_sleep_seconds"])
    static_motion_threshold = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["static_motion_threshold"])
    prone_head_down_ratio_threshold = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["prone_head_down_ratio_threshold"])
    prone_bbox_height_ratio_threshold = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["prone_bbox_height_ratio_threshold"])
    prone_consecutive_frames = Column(Integer, nullable=False, default=SITE_POLICY_DEFAULTS["prone_consecutive_frames"])
    state_ttl_seconds = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["state_ttl_seconds"])
    vehicle_inspection_enabled = Column(Boolean, nullable=False, default=SITE_POLICY_DEFAULTS["vehicle_inspection_enabled"])
    vehicle_camera_id = Column(Integer, ForeignKey(AiCameraConfig.id, ondelete="SET NULL"),
                               nullable=True, default=SITE_POLICY_DEFAULTS["vehicle_camera_id"])
    vehicle_occlusion_seconds = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["vehicle_occlusion_seconds"])
    vehicle_near_px = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["vehicle_near_px"])
    vehicle_exit_direction = Column(String(10), nullable=False, default=SITE_POLICY_DEFAULTS["vehicle_exit_direction"])
    vehicle_direction_min_delta_ratio = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["vehicle_direction_min_delta_ratio"])
    vehicle_reassociate_seconds = Column(Double, nullable=False, default=SITE_POLICY_DEFAULTS["vehicle_reassociate_seconds"])

    site = relationship(GuardBehaviorSite, back_populates="policy")


class GuardBehaviorAlarmPolicy(_Timestamps, Base):
    __tablename__ = "ai_guard_behavior_alarm_policy"
    __table_args__ = (
        UniqueConstraint("site_id", "violation_type", name="uq_guard_behavior_site_alarm_type"),
        CheckConstraint(f"violation_type IN ({', '.join(map(str, GUARD_ALARM_TYPES))})",
                        name="ck_guard_behavior_alarm_type"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("ai_guard_behavior_site.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    violation_type = Column(Integer, nullable=False)
    alarm_interval = Column(Double, nullable=False, default=default_alarm_interval)
    sql_enable = Column(Boolean, nullable=False, default=ALARM_POLICY_DEFAULTS["sql_enable"])
    horn_enable = Column(Boolean, nullable=False, default=ALARM_POLICY_DEFAULTS["horn_enable"])
    horn_id = Column(Integer, ForeignKey(AiHornConfig.id, ondelete="SET NULL"),
                     nullable=True, default=ALARM_POLICY_DEFAULTS["horn_id"])
    horn_event_id = Column(Integer, nullable=True, default=ALARM_POLICY_DEFAULTS["horn_event_id"])
    wechat_enable = Column(Boolean, nullable=False, default=ALARM_POLICY_DEFAULTS["wechat_enable"])
    wechat_user = Column(String(255), nullable=False, default=ALARM_POLICY_DEFAULTS["wechat_user"])

    site = relationship(GuardBehaviorSite, back_populates="alarm_policies")
