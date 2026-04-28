"""features/detect_phone/orm.py"""
from sqlalchemy import Column, Float, JSON
from features._base.orm import FeatureConfigBase


class PhoneConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_phone"

    roi_pos = Column(JSON, nullable=True)
    CONF_THRESHOLD = Column(Float, default=0.7)
    IOU_THR = Column(Float, default=0.5)
