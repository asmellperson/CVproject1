"""本地海康人员资料的 SQLAlchemy ORM。"""
from sqlalchemy import Boolean, Column, Integer, String, Text, TIMESTAMP, UniqueConstraint, text

from AiVision.core.db import Base


class FacePerson(Base):
    __tablename__ = "ai_face_person"
    __table_args__ = (
        UniqueConstraint("hik_source", "hik_person_id", name="uq_face_person_hik_source_person"),
        {"comment": "海康人员资料库", "mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    hik_source = Column(String(16), nullable=False, comment="海康来源 one / two")
    hik_person_id = Column(String(64), nullable=False, comment="海康 personId")
    person_name = Column(String(255), nullable=True, comment="海康 personName")
    person_code = Column(String(64), nullable=True, comment="海康 personCode")
    job_no = Column(String(64), nullable=True, comment="海康 jobNo")
    org_index_code = Column(String(64), nullable=True, comment="海康 orgIndexCode")
    pic_uri = Column(Text, nullable=True, comment="原始 personPhoto.picUri")
    server_index_code = Column(String(64), nullable=True, comment="原始 personPhoto.serverIndexCode")
    is_active = Column(Boolean, nullable=False, default=True, comment="最近完整同步中是否存在")
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"),
    )
    last_synced_at = Column(TIMESTAMP, nullable=False, comment="最近一次实际写入同步时间")
