"""摄像头配置和全部安检会话的持久化。"""

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text
from sqlalchemy.dialects.mysql import MEDIUMBLOB

from AiVision.core.db import Base
from AiVision.features._shared.orm import FeatureConfigBase
from .schema import InspectionValue

_DEFAULTS = InspectionValue().model_dump()


class InspectionCameraConfig(FeatureConfigBase):
    """持久化逐摄像头的安检工位、交互识别和采样配置。"""
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
    """保存全部会话的成功、失败或取消记录；摄像头删除后保留历史快照。"""
    __tablename__ = "ai_security_inspection_session"
    __table_args__ = (
        Index("ix_inspection_department_time", "department", "started_at"),
        Index("ix_inspection_started_at", "started_at"),
    )

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


class InspectionSessionImage(Base):
    """每条不合规会话的 JPEG 证据；与会话一起提交、过期后随会话删除。"""
    __tablename__ = "ai_security_inspection_session_image"

    session_id = Column(
        String(128), ForeignKey("ai_security_inspection_session.session_id", ondelete="CASCADE"), primary_key=True,
    )
    image_data = Column(LargeBinary().with_variant(MEDIUMBLOB(), "mysql"), nullable=False)
    media_type = Column(String(32), nullable=False)
