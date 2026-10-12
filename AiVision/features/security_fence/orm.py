"""逐摄像头围栏规则；白名单只引用共享人员库 ID。"""
from sqlalchemy import Column, Float, Integer, JSON, String, select
from sqlalchemy.orm import object_session

from AiVision.features._shared.orm import FeatureConfigBase
from AiVision.features.face_recognition.library.orm import FacePerson
from .schema import FenceValue

_DEFAULT = FenceValue()


class FenceConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_security_fence"
    roi_pos = Column(JSON, nullable=False, default=list)
    forbidden_start = Column(String(5), nullable=False, default=_DEFAULT.forbidden_start)
    forbidden_end = Column(String(5), nullable=False, default=_DEFAULT.forbidden_end)
    timezone = Column(String(64), nullable=False, default=_DEFAULT.timezone)
    allowed_person_ids = Column(JSON, nullable=False, default=list)
    cap_interval = Column(Float, nullable=False, default=_DEFAULT.cap_interval)
    threshold = Column(Float, nullable=False, default=_DEFAULT.threshold)
    detection_threshold = Column(Float, nullable=False, default=_DEFAULT.detection_threshold)
    similarity_threshold = Column(Float, nullable=False, default=_DEFAULT.similarity_threshold)
    unknown_similarity_threshold = Column(Float, nullable=False, default=_DEFAULT.unknown_similarity_threshold)
    confirmation_frames = Column(Integer, nullable=False, default=_DEFAULT.confirmation_frames)
    min_face_size = Column(Integer, nullable=False, default=_DEFAULT.min_face_size)
    min_face_sharpness = Column(Float, nullable=False, default=_DEFAULT.min_face_sharpness)
    max_face_asymmetry = Column(Float, nullable=False, default=_DEFAULT.max_face_asymmetry)
    tracking_overlap_threshold = Column(Float, nullable=False, default=_DEFAULT.tracking_overlap_threshold)
    tracking_gap_seconds = Column(Float, nullable=False, default=_DEFAULT.tracking_gap_seconds)

    def apply_config_dict(self, config: dict):
        ids = config["value"]["allowed_person_ids"]
        session = object_session(self)
        if ids and session is None:
            raise RuntimeError("围栏配置必须在数据库事务中保存")
        found = set(session.scalars(select(FacePerson.id).where(FacePerson.id.in_(ids)))) if ids else set()
        if found != set(ids):
            raise ValueError("白名单中存在已删除或不存在的人员，请重新选择")
        super().apply_config_dict(config)
