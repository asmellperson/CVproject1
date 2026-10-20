"""对话和配置审计独立于原业务表，工具执行前后均保留可核对的状态。"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from AiVision.core.db import Base


class AssistantSession(Base):
    __tablename__ = "ai_assistant_session"
    id = Column(String(36), primary_key=True)
    employee_id = Column(String(100), nullable=False)
    department = Column(String(100), nullable=True)
    title = Column(String(100), nullable=False, default="新对话")
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now)
    __table_args__ = (Index("ix_assistant_session_owner", "employee_id", "updated_at"),)


class AssistantTurn(Base):
    __tablename__ = "ai_assistant_turn"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("ai_assistant_session.id", ondelete="CASCADE"), nullable=False)
    request_id = Column(String(36), nullable=False, unique=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="queued")
    progress = Column(String(255), nullable=False, default="等待处理")
    access_scope = Column(JSON, nullable=False)
    cancel_requested = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    __table_args__ = (Index("ix_assistant_turn_session", "session_id", "id"),)


class AssistantAction(Base):
    __tablename__ = "ai_assistant_action"
    id = Column(String(36), primary_key=True)
    turn_id = Column(BigInteger().with_variant(Integer, "sqlite"),
                     ForeignKey("ai_assistant_turn.id", ondelete="CASCADE"), nullable=False)
    resource_key = Column(String(200), nullable=False)
    operation_key = Column(String(64), nullable=False)
    resource = Column(JSON, nullable=False)
    status = Column(String(30), nullable=False)
    before = Column(JSON, nullable=False)
    after = Column(JSON, nullable=True)
    changes = Column(JSON, nullable=False)
    detail = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    __table_args__ = (UniqueConstraint("turn_id", "operation_key", name="uq_assistant_action_operation"),)
