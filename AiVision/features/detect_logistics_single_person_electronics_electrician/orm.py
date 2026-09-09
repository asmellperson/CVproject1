"""features/detect_logistics_single_person_electronics_electrician/orm.py"""
from sqlalchemy import Column, Float, Integer, JSON

from AiVision.features._base.orm import FeatureConfigBase

class LogisticsSinglePersonElectronicsElectricianConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_logistics_single_person_ee"

    CONF_THRESHOLD = Column(Float, default=0.3)
    IOU_THR = Column(Float, default=0.3)
    roi_pos = Column(JSON, nullable=True)
    region = Column(JSON, nullable=True)
    MIN_BOX_AREA = Column(Integer, default=0)
    ASPECT_RATIO_RANGE = Column(JSON, nullable=True)
    empty_grace_seconds = Column(Float, default=2.0)
    multi_grace_seconds = Column(Float, default=1.0)
