"""
platform/camera/orm.py
摄像头主配置表 ORM。

字段与旧表 ai_camera_config 一致 — 不改表结构。
"""
from __future__ import annotations
from sqlalchemy import Column, Integer, String, Boolean, JSON, TIMESTAMP, Text, text

from core.db import Base


class AiCameraConfig(Base):
    __tablename__ = "ai_camera_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    url = Column(String(500), nullable=False)
    shm_name = Column(String(100), nullable=False, unique=True, index=True,
                      comment="共享内存标识,全系统唯一")
    fps = Column(Integer, default=5)
    max_restart = Column(Integer, default=10, comment="摄像头断流最大自动重启次数")

    # 旧的 function_config JSON 字段保留 — 仅作历史兼容,新代码不读不写
    function_config = Column(JSON, nullable=True)
    enable = Column(Boolean, default=True)

    import_time = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
    import_message = Column(Text)
    shape = Column(JSON, nullable=True, default=[1080, 1920, 3], comment="默认分辨率 [H,W,C]")

    def __repr__(self):
        return f"<AiCameraConfig id={self.id} name={self.name!r} enable={self.enable}>"
