"""本地海康人员资料的 SQLAlchemy ORM。"""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, LargeBinary, String, Text, TIMESTAMP, UniqueConstraint, text

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
    is_allowed = Column(
        Boolean, nullable=False, default=False, server_default=text("0"), comment="是否允许通行",
    )
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"),
    )
    last_synced_at = Column(TIMESTAMP, nullable=False, comment="最近一次实际写入同步时间")


class FaceEmbedding(Base):
    """每位人员当前的一份特征，不重复保存人员资料。"""

    __tablename__ = "ai_face_embedding"
    __table_args__ = {"comment": "人员人脸特征", "mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("ai_face_person.id", ondelete="CASCADE"), nullable=False, unique=True)
    embedding = Column(LargeBinary, nullable=False, comment="小端 float32 特征字节")
    embedding_dim = Column(Integer, nullable=False)
    model_name = Column(String(64), nullable=False)
    photo_signature = Column(String(64), nullable=False, comment="原始照片地址与服务器索引的 SHA256")
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"),
    )
