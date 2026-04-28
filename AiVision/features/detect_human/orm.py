"""features/detect_human/orm.py"""
from sqlalchemy import Column, Integer, Float, JSON
from features._base.orm import FeatureConfigBase


class HumanConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_human"

    CONF_THRESHOLD = Column(Float, default=0.3)
    IOU_THR = Column(Float, default=0.3)
    MAX_LOST = Column(Integer, default=5)
    MAX_TIME = Column(Float, default=10.0)
    roi_pos = Column(JSON, nullable=True)
    region = Column(JSON, nullable=True)
    MIN_BOX_AREA = Column(Integer, default=0)
    ASPECT_RATIO_RANGE = Column(JSON, nullable=True)
