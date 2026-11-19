"""摄像头独立保存围栏规则与通行授权。"""
from sqlalchemy import Column, Float, ForeignKey, Integer, JSON, String, TIMESTAMP, text

from AiVision.core.db import Base
from AiVision.features._shared.orm import FeatureConfigBase
from .schema import FenceValue

_DEFAULT = FenceValue()


class FenceConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_security_fence"
    roi_pos = Column(JSON, nullable=False, default=list)
    forbidden_start = Column(String(5), nullable=False, default=_DEFAULT.forbidden_start)
    forbidden_end = Column(String(5), nullable=False, default=_DEFAULT.forbidden_end)
    timezone = Column(String(64), nullable=False, default=_DEFAULT.timezone)
    cap_interval = Column(Float, nullable=False, default=_DEFAULT.cap_interval)
    threshold = Column(Float, nullable=False, default=_DEFAULT.threshold)
    detection_threshold = Column(
        Float,
        nullable=False,
        default=_DEFAULT.detection_threshold,
        server_default=text(str(_DEFAULT.detection_threshold)),
    )
    similarity_threshold = Column(Float, nullable=False, default=_DEFAULT.similarity_threshold)
    unknown_similarity_threshold = Column(Float, nullable=False, default=_DEFAULT.unknown_similarity_threshold)
    confirmation_frames = Column(Integer, nullable=False, default=_DEFAULT.confirmation_frames)
    min_face_size = Column(Integer, nullable=False, default=_DEFAULT.min_face_size)
    min_face_sharpness = Column(Float, nullable=False, default=_DEFAULT.min_face_sharpness)
    max_face_asymmetry = Column(Float, nullable=False, default=_DEFAULT.max_face_asymmetry)
    tracking_overlap_threshold = Column(Float, nullable=False, default=_DEFAULT.tracking_overlap_threshold)
    tracking_gap_seconds = Column(Float, nullable=False, default=_DEFAULT.tracking_gap_seconds)


class FencePersonAuthorization(Base):
    """一行代表人员在指定摄像头获准通过围栏，与人脸识别授权独立。"""
    __tablename__ = "ai_security_fence_person_authorization"
    __table_args__ = {"comment": "摄像头警戒围栏通行白名单", "mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    camera_id = Column(Integer, ForeignKey("ai_camera_config.id", ondelete="CASCADE"), primary_key=True,
                       comment="授权摄像头")
    person_id = Column(Integer, ForeignKey("ai_face_person.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
