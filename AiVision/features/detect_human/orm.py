"""features/detect_human/orm.py"""
from sqlalchemy import Column, Integer, Float, JSON
from features._base.orm import FeatureConfigBase


class HumanConfigFieldsMixin:
    """人员违规逗留检测配置字段，供各公司独立配置表复用。"""

    CONF_THRESHOLD = Column(Float, default=0.3)
    IOU_THR = Column(Float, default=0.3)
    MAX_LOST = Column(Integer, default=5)
    MAX_TIME = Column(Float, default=10.0)
    roi_pos = Column(JSON, nullable=True)
    region = Column(JSON, nullable=True)
    MIN_BOX_AREA = Column(Integer, default=0)
    ASPECT_RATIO_RANGE = Column(JSON, nullable=True)
    CENTER_DIST_THR = Column(Float, default=0.65)
    AREA_RATIO_THR = Column(Float, default=0.55)
    MATCH_SCORE_THR = Column(Float, default=0.35)
    TRACK_SMOOTH_ALPHA = Column(Float, default=0.7)


class HumanConfigORM(HumanConfigFieldsMixin, FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_human"
