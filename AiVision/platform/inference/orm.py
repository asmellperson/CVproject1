"""
platform/inference/orm.py
推理模型配置表 — 与旧表 ai_model 一致。
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, TIMESTAMP, text
from core.db import Base


class AiModel(Base):
    __tablename__ = "ai_model"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    type = Column(String(50), nullable=False, comment="yolo / mediapipe / other")
    path = Column(String(500), nullable=False, comment="模型文件路径")
    import_path = Column(
        String(255), nullable=True,
        comment="Worker 类导入路径,如 platform.inference.workers.yolo_detector.YoloDetectorWorker",
    )
    description = Column(
        Text, nullable=True,
        comment="说明 / 配置 JSON(可包含 class_filter, type_label, conf, iou)",
    )
    enable = Column(Boolean, default=True, index=True)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    def __repr__(self):
        return f"<AiModel id={self.id} name={self.name!r}>"
