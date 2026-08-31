# 文件说明：定义`db` 模块的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：实现 `_database_url` 对应的`db` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/db.py` 的 `get_engine` 调用本符号
#   - 内部调用：`os.getenv`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：Return the process-wide SQLAlchemy engine；输入与输出详见下方说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`create_engine`、`_database_url`。
# 副作用/注意事项：会修改全局或闭包状态。
def get_engine():
    """Return the process-wide SQLAlchemy engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(_database_url(), pool_pre_ping=True, future=True)
    return _engine


# 功能：Return the process-wide SQLAlchemy session factory；输入与输出详见下方说明
# 参数：无。
# 返回：sessionmaker；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`sessionmaker`、`get_engine`。
# 副作用/注意事项：会修改全局或闭包状态。
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


# 功能：Create a new database session. Caller must close it；输入与输出详见下方说明
# 参数：无。
# 返回：Session；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`get_session_factory()`、`get_session_factory`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_session() -> Session:
    """Create a new database session. Caller must close it."""
    return get_session_factory()()


# 功能：Provide a transaction-scoped session；输入与输出详见下方说明
# 参数：无。
# 返回：Iterator[Session]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`get_session`、`session.commit`、`session.rollback`、`session.close`。
# 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
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


# 功能：Create guard-room tables if they do not already exist；输入与输出详见下方说明
# 参数：无。
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Base.metadata.create_all`、`get_engine`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def create_all_tables() -> None:
    """Create guard-room tables if they do not already exist."""
    from . import orm as _guard_room_orm  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


# 功能：Dispose the global engine and reset cached handles；输入与输出详见下方说明
# 参数：无。
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_engine.dispose`。
# 副作用/注意事项：会修改全局或闭包状态。
def dispose() -> None:
    """Dispose the global engine and reset cached handles."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


# 功能：Point the module at a test database and reset global handles；输入与输出详见下方说明
# 参数：
#   - `database_url`（str）：`database_url` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`dispose`、`create_all_tables`。
# 副作用/注意事项：会修改全局或闭包状态。
def configure_for_tests(database_url: str) -> None:
    """Point the module at a test database and reset global handles."""
    global _database_url_override
    _database_url_override = database_url
    dispose()
    create_all_tables()


# 功能：Return True when the configured database accepts a trivial query；输入与输出详见下方说明
# 参数：无。
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`get_engine().connect`、`get_engine`、`conn.execute`、`text`。
# 副作用/注意事项：可能读取或修改数据库事务。
def ping() -> bool:
    """Return True when the configured database accepts a trivial query."""
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
