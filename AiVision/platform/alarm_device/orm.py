"""platform/alarm_device/orm.py — 喇叭设备配置表"""
from sqlalchemy import Column, Integer, String, Boolean, Text, TIMESTAMP, text
from core.db import Base


class AiHornConfig(Base):
    __tablename__ = "ai_horn_config"
    __table_args__ = {
        "comment": "喇叭设备配置表",
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
    }

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    url = Column(String(500), nullable=False)
    username = Column(String(100), nullable=False, default="admin")
    password = Column(String(200), nullable=False, default="admin")
    enable = Column(Boolean, default=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    def __repr__(self):
        return f"<AiHornConfig id={self.id} name={self.name!r}>"
