"""复用公共摄像头功能配置，独立保存视觉理解事件。"""

from sqlalchemy import Column, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.mysql import DATETIME

from AiVision.core.db import Base
from AiVision.features._shared.orm import FeatureConfigBase
from .schema import VisualLanguageValue

_DEFAULTS = VisualLanguageValue().model_dump()


class VisualLanguageConfigORM(FeatureConfigBase):
    """保存摄像头 ROI、发送周期、图像编码与观察提示词配置。"""
    __tablename__ = "ai_camera_config_visual_language_detection"

    roi_pos = Column(JSON, nullable=False, default=list)
    cap_interval = Column(Float, nullable=False, default=_DEFAULTS["cap_interval"])
    jpeg_quality = Column(Integer, nullable=False, default=_DEFAULTS["jpeg_quality"])
    max_image_width = Column(Integer, nullable=False, default=_DEFAULTS["max_image_width"])
    max_tokens = Column(Integer, nullable=False, default=_DEFAULTS["max_tokens"])
    temperature = Column(Float, nullable=False, default=_DEFAULTS["temperature"])
    top_p = Column(Float, nullable=False, default=_DEFAULTS["top_p"])
    observation_prompt = Column(Text, nullable=False, default=_DEFAULTS["observation_prompt"])


class VisualLanguageEventORM(Base):
    """按摄像头和事业部保存观察、提问及错误事件，记录实际采集时刻。"""
    __tablename__ = "ai_visual_language_event"
    __table_args__ = (Index("ix_visual_language_camera_time", "department", "camera_id", "captured_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("ai_camera_config.id", ondelete="CASCADE"), nullable=False)
    department = Column(String(64), nullable=False)
    kind = Column(String(16), nullable=False)
    text = Column(Text, nullable=False)
    question = Column(Text, nullable=True)
    # 保留共享帧的采集精度，使提问响应和持久化时间线指向同一帧。
    captured_at = Column(DATETIME(fsp=6), nullable=False)
    latency_seconds = Column(Float, nullable=True)
