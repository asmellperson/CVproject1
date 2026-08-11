"""Database helpers for Guard Room metadata.

The guard-room runtime still consumes ``AppConfig`` objects. These helpers only
store dynamic business data such as guard rooms, grouped cameras, and per-room
configuration in SQL.
"""
from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

Base = declarative_base()

_engine = None
_session_factory: sessionmaker | None = None
_database_url_override: str | None = None
_MODULE_ROOT = Path(__file__).resolve().parents[1]


def _database_url() -> str:
    explicit = _database_url_override or os.getenv("GUARD_ROOM_DATABASE_URL")
    if explicit:
        return explicit

    mysql_host = os.getenv("MYSQL_DB_URL")
    mysql_user = os.getenv("MYSQL_DB_USER")
    mysql_password = os.getenv("MYSQL_DB_PASSWORD")
    mysql_name = os.getenv("MYSQL_DB_NAME")
    if mysql_host and mysql_user and mysql_password and mysql_name:
        port = os.getenv("MYSQL_DB_PORT", "3306")
        charset = os.getenv("MYSQL_DB_CHARSET", "utf8mb4")
        return f"mysql+pymysql://{mysql_user}:{mysql_password}@{mysql_host}:{port}/{mysql_name}?charset={charset}"

    return f"sqlite:///{_MODULE_ROOT / 'guard_room.db'}"


def get_engine():
    """Return the process-wide SQLAlchemy engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(_database_url(), pool_pre_ping=True, future=True)
    return _engine


def get_session_factory() -> sessionmaker:
    """Return the process-wide SQLAlchemy session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
    return _session_factory


def get_session() -> Session:
    """Create a new database session. Caller must close it."""
    return get_session_factory()()


@contextlib.contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transaction-scoped session."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all_tables() -> None:
    """Create guard-room tables if they do not already exist."""
    from . import orm as _guard_room_orm  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


def dispose() -> None:
    """Dispose the global engine and reset cached handles."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def configure_for_tests(database_url: str) -> None:
    """Point the module at a test database and reset global handles."""
    global _database_url_override
    _database_url_override = database_url
    dispose()
    create_all_tables()


def ping() -> bool:
    """Return True when the configured database accepts a trivial query."""
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
