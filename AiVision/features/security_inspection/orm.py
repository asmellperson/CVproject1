"""摄像头配置和全部安检会话的持久化。"""

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text

from AiVision.core.db import Base
from AiVision.features._shared.orm import FeatureConfigBase
from .schema import InspectionValue

_DEFAULTS = InspectionValue().model_dump()


class InspectionCameraConfig(FeatureConfigBase):
    __tablename__ = "ai_camera_config_security_inspection"

    staff_rois = Column(JSON, nullable=False, default=dict)
    conf = Column(Float, nullable=False, default=_DEFAULTS["conf"])
    iou = Column(Float, nullable=False, default=_DEFAULTS["iou"])
    imgsz = Column(Integer, nullable=False, default=_DEFAULTS["imgsz"])
    pair_start_hold_frames = Column(Integer, nullable=False, default=_DEFAULTS["pair_start_hold_frames"])
    fingerprint_lost_seconds = Column(Float, nullable=False, default=_DEFAULTS["fingerprint_lost_seconds"])
    no_interact_seconds = Column(Float, nullable=False, default=_DEFAULTS["no_interact_seconds"])
    max_session_seconds = Column(Float, nullable=False, default=_DEFAULTS["max_session_seconds"])
    keyframe_interval_sec = Column(Float, nullable=False, default=_DEFAULTS["keyframe_interval_sec"])
    keyframes_per_session = Column(Integer, nullable=False, default=_DEFAULTS["keyframes_per_session"])
    roi_crop_padding = Column(Integer, nullable=False, default=_DEFAULTS["roi_crop_padding"])
    fp_match_threshold = Column(Float, nullable=False, default=_DEFAULTS["fp_match_threshold"])
    interact_distance_max_ratio = Column(Float, nullable=False, default=_DEFAULTS["interact_distance_max_ratio"])
    interact_motion_min_pixels = Column(Float, nullable=False, default=_DEFAULTS["interact_motion_min_pixels"])
    roi_enter_overlap_ratio = Column(Float, nullable=False, default=_DEFAULTS["roi_enter_overlap_ratio"])
    roi_hold_overlap_ratio = Column(Float, nullable=False, default=_DEFAULTS["roi_hold_overlap_ratio"])


class InspectionSession(Base):
    __tablename__ = "ai_security_inspection_session"
    __table_args__ = (Index("ix_inspection_department_time", "department", "started_at"),)

    session_id = Column(String(128), primary_key=True)
    camera_id = Column(Integer, ForeignKey("ai_camera_config.id", ondelete="SET NULL"), nullable=True, index=True)
    camera_name = Column(String(100), nullable=False)
    department = Column(String(100), nullable=False)
    roi_name = Column(String(100), nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False)
    verdict = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    latency_sec = Column(Float, nullable=True)
