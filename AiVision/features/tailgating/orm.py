"""逐摄像头保存通行规则；部门归属统一由摄像头外键确定。"""
from sqlalchemy import Column, Float, Integer, JSON

from AiVision.features._shared.orm import FeatureConfigBase
from .schema import TailgatingValue

_DEFAULT = TailgatingValue()


class TailgatingConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_tailgating"
    roi_pos = Column(JSON, nullable=False, default=list)
    line_points = Column(JSON, nullable=False, default=list)
    direction = Column(Integer, nullable=False, default=_DEFAULT.direction)
    overlap_seconds = Column(Float, nullable=False, default=_DEFAULT.overlap_seconds)
    crossing_window_seconds = Column(Float, nullable=False, default=_DEFAULT.crossing_window_seconds)
    max_frame_gap_seconds = Column(Float, nullable=False, default=_DEFAULT.max_frame_gap_seconds)
    foot_ratio = Column(Float, nullable=False, default=_DEFAULT.foot_ratio)
    threshold = Column(Float, nullable=False, default=_DEFAULT.threshold)
    cap_interval = Column(Float, nullable=False, default=_DEFAULT.cap_interval)
    alarm_interval = Column(Float, nullable=False, default=_DEFAULT.alarm_interval)
