"""
core/db.py
SQLAlchemy 引擎、会话、Base 声明。

所有 ORM 类都继承自这里的 Base。
"""
from __future__ import annotations
import contextlib
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.schema import CreateColumn
from core.settings import settings
from core.logger import logger

Base = declarative_base()

_engine = None
_session_factory: sessionmaker | None = None


def _scalar_default(column):
    default = column.default
    if default is None or default.is_callable:
        return None
    value = default.arg
    if isinstance(value, (str, int, float, bool)):
        return value
    return None


def get_engine():
    global _engine
    if _engine is None:
        if settings.db.auto_create:
            _ensure_database_exists()
        _engine = create_engine(
            settings.db.sqlalchemy_url,
            pool_size=20,
            max_overflow=10,
            pool_recycle=3600,
            pool_pre_ping=True,
            echo=False,
        )
        logger.info(f"[DB] 已连接到 {settings.db.name}@{settings.db.url}")
    return _engine


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_factory


def get_session() -> Session:
    """获取新会话。调用方必须在 finally 中关闭。"""
    return get_session_factory()()


@contextlib.contextmanager
def session_scope():
    """事务作用域 — 提交或回滚后自动关闭。

    用法:
        with session_scope() as s:
            s.add(obj)
            # 自动 commit;若抛错则 rollback
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all_tables():
    """根据所有已注册 ORM 创建表。需在 import 完所有 ORM 后调用。"""
    Base.metadata.create_all(bind=get_engine())
    logger.info("[DB] 数据库表已创建/验证")


def ensure_schema_compatible():
    """补齐当前 ORM 需要但正式库旧表缺失的列。

    SQLAlchemy 的 create_all 只会创建不存在的表,不会修改已有表。正式库从旧版
    AiVision 切换到当前代码时,可能缺少后续新增字段,这里做 additive-only 修补。
    """
    # 确保所有 ORM 已注册进 Base.metadata。
    from features import all_specs  # noqa: F401
    from platform.alarm_device import orm as _alarm_device_orm  # noqa: F401
    from platform.camera import orm as _camera_orm  # noqa: F401
    from platform.inference import orm as _inference_orm  # noqa: F401
    from platform.violation import orm as _violation_orm  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    patched = 0
    with engine.begin() as conn:
        existing_tables = set(inspector.get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
                conn.execute(text(f"ALTER TABLE `{table.name}` ADD COLUMN {ddl}"))
                default_value = _scalar_default(column)
                if default_value is not None:
                    conn.execute(
                        text(f"UPDATE `{table.name}` SET `{column.name}` = :default WHERE `{column.name}` IS NULL"),
                        {"default": default_value},
                    )
                patched += 1
                logger.info(f"[DB] 已补齐字段 {table.name}.{column.name}")

    if patched:
        logger.info(f"[DB] Schema 兼容修补完成,新增 {patched} 个字段")
    else:
        logger.info("[DB] Schema 兼容检查通过,无需补字段")


def _ensure_database_exists():
    """AUTO_CREATE_DB=true 时,如数据库不存在则创建。"""
    server_url = (
        f"mysql+pymysql://{settings.db.user}:{settings.db.password}"
        f"@{settings.db.url}:{settings.db.port}?charset={settings.db.charset}"
    )
    temp_engine = create_engine(server_url, echo=False)
    try:
        with temp_engine.connect() as conn:
            result = conn.execute(text(f"SHOW DATABASES LIKE '{settings.db.name}'"))
            if result.fetchone() is None:
                conn.execute(text(
                    f"CREATE DATABASE {settings.db.name} "
                    f"CHARACTER SET {settings.db.charset} COLLATE utf8mb4_unicode_ci"
                ))
                conn.commit()
                logger.info(f"[DB] 自动创建数据库: {settings.db.name}")
    finally:
        temp_engine.dispose()


def dispose():
    """优雅关闭"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("[DB] 数据库连接池已释放")
