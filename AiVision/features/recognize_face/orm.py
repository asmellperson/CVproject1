"""识别参数与基础识别记录，不接入报警记录表。"""
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, JSON, String, TIMESTAMP, text

from AiVision.core.db import Base
from AiVision.features._base.orm import FeatureConfigBase
from AiVision.platform.face_library.constants import (
    DEFAULT_CAPTURE_INTERVAL, DEFAULT_DETECTION_THRESHOLD, DEFAULT_RECORD_COOLDOWN_SECONDS,
    DEFAULT_SIMILARITY_THRESHOLD,
)
from AiVision.platform.face_library.orm import FaceEmbedding, FacePerson  # noqa: F401


class FaceRecognitionConfig(FeatureConfigBase):
    __tablename__ = "ai_camera_config_recognize_face"

    roi_pos = Column(JSON, nullable=False, default=list)
    cap_interval = Column(Float, nullable=False, default=DEFAULT_CAPTURE_INTERVAL)
    detection_threshold = Column(
        Float, nullable=False, default=DEFAULT_DETECTION_THRESHOLD,
        server_default=text(str(DEFAULT_DETECTION_THRESHOLD)),
    )
    similarity_threshold = Column(Float, nullable=False, default=DEFAULT_SIMILARITY_THRESHOLD)
    record_cooldown_seconds = Column(Float, nullable=False, default=DEFAULT_RECORD_COOLDOWN_SECONDS)
    record_enabled = Column(Boolean, nullable=False, default=True)


class FaceRecognitionRecord(Base):
    __tablename__ = "ai_face_recognition_record"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, nullable=False, index=True)
    person_id = Column(Integer, ForeignKey("ai_face_person.id", ondelete="SET NULL"), nullable=True, index=True)
    person_name = Column(String(255), nullable=False)
    similarity = Column(Float, nullable=False)
    image_path = Column(String(512), nullable=True)
    recognized_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"), index=True)
