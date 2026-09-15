"""features/face_dwell/orm.py"""
from sqlalchemy import CheckConstraint, Column, Integer, Float, JSON
from AiVision.features._shared import defaults
from AiVision.features._shared.orm import FeatureConfigBase
from .schema import FaceValueSchema

_VALUE_DEFAULTS = FaceValueSchema().model_dump()

class FaceConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_face"
    __table_args__ = (
        CheckConstraint("DETECTION_IOU_THR BETWEEN 0 AND 1", name="ck_detect_face_0"),
        CheckConstraint("TRACK_IOU_THR BETWEEN 0 AND 1", name="ck_detect_face_1"),
        CheckConstraint("MAX_LOST >= 0", name="ck_detect_face_2"),
    )

    roi_pos = Column(JSON, nullable=False, default=list)
    FACE_SCORE_THR = Column(Float, default=_VALUE_DEFAULTS["FACE_SCORE_THR"])
    # 复用基类的 cap_interval / alarm_interval
    # 跟踪相关字段(从 detect_human 借的设计)
    MAX_TIME = Column(Float, default=defaults.MAX_TIME, comment="逗留时间阈值(秒)")
    DETECTION_IOU_THR = Column(Float, nullable=False, default=defaults.DETECTION_IOU_THR, server_default=str(defaults.DETECTION_IOU_THR))
    TRACK_IOU_THR = Column(Float, nullable=False, default=defaults.TRACK_IOU_THR, server_default=str(defaults.TRACK_IOU_THR))
    MAX_LOST = Column(Integer, nullable=False, default=defaults.MAX_LOST, server_default=str(defaults.MAX_LOST), comment="允许连续丢失的跟踪更新次数")
