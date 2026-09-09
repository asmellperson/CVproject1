"""features/detect_face/orm.py"""
from sqlalchemy import Column, Float, JSON
from AiVision.features._base.orm import FeatureConfigBase

class FaceConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_face"

    roi_pos = Column(JSON, nullable=True)
    FACE_SCORE_THR = Column(Float, default=0.6)
    YAW_THRESHOLD = Column(JSON, nullable=True)
    # 复用基类的 cap_interval / alarm_interval
    # 跟踪相关字段(从 detect_human 借的设计)
    MAX_TIME = Column(Float, default=10.0, comment="逗留时间阈值(秒)")
    IOU_THR = Column(Float, default=0.3)
    MAX_LOST = Column(Float, default=5)
