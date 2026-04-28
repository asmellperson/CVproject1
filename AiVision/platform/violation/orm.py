"""platform/violation/orm.py"""
from sqlalchemy import Column, String, SmallInteger, DateTime, text
from sqlalchemy.dialects.mysql import BIGINT
from core.db import Base


class AiViolationImage(Base):
    __tablename__ = "ai_violation_image"
    __table_args__ = {
        "comment": "AI违规图片存储表",
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
    }

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    image_path = Column(String(500), nullable=False, comment="违规图片存储路径")
    violation_type = Column(SmallInteger, nullable=False, comment="违规类型枚举")
    camera_no = Column(String(100), nullable=True, comment="摄像头标识 shm_name")
    create_time = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    def __repr__(self):
        return f"<AiViolationImage id={self.id} type={self.violation_type}>"
