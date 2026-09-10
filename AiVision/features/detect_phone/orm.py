"""features/detect_phone/orm.py"""
from sqlalchemy import Boolean, Column, Float, JSON
from AiVision.features._base.orm import FeatureConfigBase

class PhoneConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_phone"

    roi_pos = Column(JSON, nullable=False, default=list)
    CONF_THRESHOLD = Column(Float, default=0.7)
    IOU_THR = Column(Float, default=0.5)
    MIN_CONFIRM_SECONDS = Column(Float, default=1.2)
    MIN_CONSECUTIVE_HITS = Column(Float, default=3)
    MAX_MISSED_SECONDS = Column(Float, default=0.6)
    TRACK_TTL_SECONDS = Column(Float, default=2.0)
    TRACK_IOU_THRESHOLD = Column(Float, default=0.2)
    PERSON_CONF_THRESHOLD = Column(Float, default=0.3)
    PERSON_IOU_THR = Column(Float, default=0.3)
    REQUIRE_PERSON_ASSOCIATION = Column(Boolean, default=True)
    PERSON_EXPAND_RATIO = Column(Float, default=0.18)
    HAND_REGION_MAX_Y_RATIO = Column(Float, default=0.85)
    MIN_PERSON_PHONE_OVERLAP = Column(Float, default=0.08)
