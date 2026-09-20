"""共享 MySQL 中的账号和访问审计表。"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, Enum, Integer, JSON, String
from sqlalchemy.dialects.mysql import DATETIME

from AiVision.core.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuthUser(Base):
    __tablename__ = "auth_users"
    __table_args__ = (
        CheckConstraint("auth_version >= 1", name="ck_auth_user_version"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_bin",
        },
    )

    employee_id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False, unique=True)
    role = Column(Enum("admin", "viewer"), nullable=False)
    departments = Column(JSON, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    password_hash = Column(String(255), nullable=False)
    auth_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DATETIME(fsp=6), nullable=False, default=utc_now)
    updated_at = Column(
        DATETIME(fsp=6), nullable=False, default=utc_now, onupdate=utc_now
    )


class AccessViewer(Base):
    __tablename__ = "auth_access_viewers"
    __table_args__ = (
        CheckConstraint("visit_count >= 1", name="ck_auth_access_visit_count"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_bin",
        },
    )

    employee_id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    role = Column(String(16), nullable=False)
    department = Column(String(100), nullable=True)
    first_seen_at = Column(DATETIME(fsp=6), nullable=False)
    last_seen_at = Column(DATETIME(fsp=6), nullable=False, index=True)
    visit_count = Column(Integer, nullable=False, default=1)
