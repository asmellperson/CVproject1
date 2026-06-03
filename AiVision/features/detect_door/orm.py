"""features/detect_door/orm.py"""
from sqlalchemy import Column, Integer, Float, JSON
from features._base.orm import FeatureConfigBase


class DoorConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_door"

    roi_pos = Column(JSON, nullable=True)
    threshold = Column(Float, default=0.5)
    blur_kernel = Column(Integer, default=5)
    diff_threshold = Column(Integer, default=5)
    diff_threshold_env = Column(Integer, default=10)
    env_threshold = Column(Float, default=10.0)
    first_alarm = Column(Integer, default=60, comment="首次告警需持续秒数")
    stable_confirm_seconds = Column(Float, default=1.0)
    stable_confirm_hits = Column(Integer, default=3)
    background_update_alpha = Column(Float, default=0.05)
    global_motion_threshold = Column(Float, default=0.22)
    min_local_change_ratio = Column(Float, default=0.01)
