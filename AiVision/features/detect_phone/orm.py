"""features/detect_phone/orm.py"""
from sqlalchemy import CheckConstraint, Boolean, Column, Integer, Float, JSON
from AiVision.features._base import defaults
from AiVision.features._base.orm import FeatureConfigBase
from .schema import PhoneValueSchema

_VALUE_DEFAULTS = PhoneValueSchema().model_dump()

class PhoneConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_phone"
    __table_args__ = (
        CheckConstraint("MIN_CONSECUTIVE_HITS >= 1", name="ck_detect_phone_0"),
    )

    roi_pos = Column(JSON, nullable=False, default=list)
    CONF_THRESHOLD = Column(Float, default=_VALUE_DEFAULTS["CONF_THRESHOLD"])
    IOU_THR = Column(Float, default=_VALUE_DEFAULTS["IOU_THR"])
    MIN_CONFIRM_SECONDS = Column(Float, default=_VALUE_DEFAULTS["MIN_CONFIRM_SECONDS"])
    MIN_CONSECUTIVE_HITS = Column(Integer, nullable=False, default=defaults.MIN_CONSECUTIVE_HITS, server_default=str(defaults.MIN_CONSECUTIVE_HITS), comment="连续命中次数，最小为1")
    MAX_MISSED_SECONDS = Column(Float, default=_VALUE_DEFAULTS["MAX_MISSED_SECONDS"])
    TRACK_TTL_SECONDS = Column(Float, default=_VALUE_DEFAULTS["TRACK_TTL_SECONDS"])
    TRACK_IOU_THRESHOLD = Column(Float, default=_VALUE_DEFAULTS["TRACK_IOU_THRESHOLD"])
    PERSON_CONF_THRESHOLD = Column(Float, default=_VALUE_DEFAULTS["PERSON_CONF_THRESHOLD"])
    PERSON_IOU_THR = Column(Float, default=_VALUE_DEFAULTS["PERSON_IOU_THR"])
    REQUIRE_PERSON_ASSOCIATION = Column(Boolean, default=_VALUE_DEFAULTS["REQUIRE_PERSON_ASSOCIATION"])
    PERSON_EXPAND_RATIO = Column(Float, default=_VALUE_DEFAULTS["PERSON_EXPAND_RATIO"])
    HAND_REGION_MAX_Y_RATIO = Column(Float, default=_VALUE_DEFAULTS["HAND_REGION_MAX_Y_RATIO"])
    MIN_PERSON_PHONE_OVERLAP = Column(Float, default=_VALUE_DEFAULTS["MIN_PERSON_PHONE_OVERLAP"])
