"""按摄像头保存 AGV 检测及 HTTP 通信配置。"""
from sqlalchemy import JSON, CheckConstraint, Column, Float, Integer

from AiVision.features._shared.orm import CameraFeatureConfigBase

from .schema import AgvPersonCheckValueSchema, HttpConfigSchema

_DEFAULTS = AgvPersonCheckValueSchema().model_dump()


class AgvPersonCheckConfigORM(CameraFeatureConfigBase):
    __tablename__ = "ai_camera_config_agv_person_check"
    __table_args__ = (
        CheckConstraint("sample_count >= 2 AND sample_count <= 30", name="ck_agv_person_check_sample_count"),
    )

    roi_pos = Column(JSON, nullable=False, default=list)
    confidence_threshold = Column(Float, nullable=False, default=_DEFAULTS["confidence_threshold"])
    iou_threshold = Column(Float, nullable=False, default=_DEFAULTS["iou_threshold"])
    sample_count = Column(Integer, nullable=False, default=_DEFAULTS["sample_count"])
    cap_interval = Column(Float, nullable=False, default=_DEFAULTS["cap_interval"])
    request_timeout_seconds = Column(Float, nullable=False, default=_DEFAULTS["request_timeout_seconds"])
    inference_timeout_seconds = Column(Float, nullable=False, default=_DEFAULTS["inference_timeout_seconds"])
    frame_max_age_seconds = Column(Float, nullable=False, default=_DEFAULTS["frame_max_age_seconds"])
    http = Column(JSON, nullable=False, default=lambda: HttpConfigSchema().model_dump())
