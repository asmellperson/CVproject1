"""
core/db.py
SQLAlchemy 引擎、会话、Base 声明。
所有 ORM 类都继承自这里的 Base。
"""
from __future__ import annotations
import contextlib
import re
from sqlalchemy import create_engine, inspect, text       # create_engine:创建数据库连接引擎，inspect：查看数据库表、列，text：执行原生SQL
from sqlalchemy.orm import declarative_base, sessionmaker, Session # declarative_base:ORM模型共同的父类，sessionmaker：创建session的工厂，Session：一次数据库操作的会话
from sqlalchemy.schema import CreateColumn          # 根据ORM Column生成SQL列定义
from AiVision.core.settings import settings
from AiVision.core.logger import logger

# 所有Aivision ORM模型共同的父类，
# Base.metadata：SQLAIchemy收集到的数据库结构总目录
Base = declarative_base()

_engine = None                  # 全局SQLAIchemy Engine单例（engine是数据库连接池以及SQL执行入口）
_session_factory: sessionmaker | None = None           # Session创建工厂
_DATABASE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_]{1,64}")
_DATABASE_CHARSET_COLLATIONS = {
    "utf8mb4": "utf8mb4_unicode_ci",
}

def _scalar_default(column) -> object | None:
    """
    提取 SQLAlchemy Column 的标量默认值，用于补列后的存量数据回填。

    仅处理可直接用于 SQL 参数的简单类型（str / int / float / bool）；
    可调用默认值（如 lambda、func.now()）无法在 Python 侧静态求值，返回 None。
    Args:
        column: SQLAlchemy Column 对象。
    Returns:
        标量默认值；无默认值或默认值为可调用时返回 None。
    """
    default = column.default
    if default is None or default.is_callable:
        return None
    value = default.arg
    if isinstance(value, (str, int, float, bool)):
        return value
    return None

def get_engine():
    """
    获取全局唯一SQLAlchemy Engine，第一次调用时才创建（单例，延迟创建）。

    连接池配置说明:
        pool_size=20      : 保持的常驻连接数，适配中等并发推理场景。
        max_overflow=10   : 超出 pool_size 后最多临时扩展的连接数。
        pool_recycle=3600 : 连接存活超 1 小时后强制回收，防止 MySQL 的 wait_timeout 断连。
        pool_pre_ping=True: 取连接前发送 ping，自动剔除已失效的连接。

    auto_create:
        settings.db.auto_create 为 True 时，在创建引擎前先确保数据库存在
        （见 _ensure_database_exists）。
    """
    global _engine
    if _engine is None:
        # 在setting.py里，如果AUTO_CREATE_DB环境变量为true，则先创建数据库，然后在创建Engine
        if settings.db.auto_create:
            _ensure_database_exists()  # 库不存在时自动 CREATE DATABASE
        _engine = create_engine(
            settings.db.sqlalchemy_url,          # mysql+pymysql://user:password@host:3306/database?charset=utf8mb4
            pool_size=20, 
            max_overflow=10,
            pool_recycle=3600,
            pool_pre_ping=True,
            echo=False,  # 生产环境关闭 SQL 日志，调试时可临时改为 True
        )
        logger.info(f"[DB] 已连接到 {settings.db.name}@{settings.db.url}")
    return _engine

def get_session_factory() -> sessionmaker:
    """
    获取全局 Session 工厂（单例，延迟创建）。

    配置说明:
        autocommit=False   : 所有写操作须显式 commit，防止意外提交。
        autoflush=False    : 禁止隐式 flush，避免在循环中产生意外 SQL。
        expire_on_commit=False : commit 后对象属性不失效，
                                 允许在 session 关闭后继续读取已提交对象的字段。
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autocommit=False,             # 修改数据库后不会自动提交
            autoflush=False,              # 不要因为查询等操作帮我flush
            expire_on_commit=False,       # commit后，已经加载到ORM对象里的字段继续可以使用
        )
    return _session_factory

def get_session() -> Session:
    """
    创建并返回一个新的数据库会话。
    Note:
        调用方负责生命周期管理，必须在 finally 块中调用 session.close()，
        否则连接不会归还连接池。
        需要自动事务管理时，优先使用 session_scope()。
    """
    return get_session_factory()()        

@contextlib.contextmanager
def session_scope():
    """
    提供自动事务管理的上下文管理器。自动管理Session + commit + rollback +close

    正常退出时自动 commit；with 块内抛出异常时自动 rollback 并重新抛出；
    无论成功与否，finally 中关闭会话并将连接归还连接池。

    用法:
        with session_scope() as s:
            s.add(obj)
            # 退出 with 块时自动 commit；抛错则自动 rollback
    """
    session = get_session()
    try:
        yield session     # 暂时把session交给with里面的代码使用。等里面代码结束以后在回来继续执行
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def create_all_tables():
    """
    根据所有已注册 ORM 模型在数据库中创建对应的表（不存在时创建，已存在时跳过）。

    Note:
        须在所有 ORM 模块完成 import（即 Base.metadata 已收集到全部表定义）后调用，
        否则部分表会被遗漏。若需同时处理旧库缺列问题，应改用 ensure_schema_compatible()。
    """
    Base.metadata.create_all(bind=get_engine())
    logger.info("[DB] 数据库表已创建/验证")


def ensure_schema_compatible():
    """
    Additive-only Schema 修补 — 补齐旧库中缺失的列，不删除或修改已有列。

    背景:
        SQLAlchemy 的 create_all() 只创建不存在的表，不会对已有表做 ALTER。
        从旧版 AiVision 迁移时，正式库可能缺少后续版本新增的字段，
        本函数通过 ALTER TABLE ADD COLUMN 逐列补齐，并对存量数据回填标量默认值。

    执行顺序:
        1. 强制 import 所有 ORM 模块，确保 Base.metadata 收集完整。
        2. create_all() 创建全新表（已有表跳过）。
        3. inspect() 对比每张表的现有列与 ORM 定义，逐列执行 ADD COLUMN。
        4. 若该列有标量默认值，对 IS NULL 的存量行执行 UPDATE 回填。

    Note:
        仅做 additive 修补，不处理列类型变更、列删除、索引变更等场景。
        生产环境若有破坏性变更，需手动执行迁移脚本。
    """
    # 强制 import，确保所有 ORM 类注册进 Base.metadata（这些import其实没有使用，目的是为了注册ORM模型到Base.metadata）
    # noqa: F401: 这个import 没有直接使用不要警告
    from AiVision.features import all_specs  # noqa: F401
    from AiVision.core import system_config as _system_config_orm       # noqa: F401
    from AiVision.platform.alarm_device import orm as _alarm_device_orm  # noqa: F401
    from AiVision.platform.camera import orm as _camera_orm              # noqa: F401
    from AiVision.platform.logistics_channel import orm as _logistics_channel_orm  # noqa: F401
    from AiVision.platform.violation import orm as _violation_orm        # noqa: F401

    # 先创建完全不存在的新表
    engine = get_engine()
    Base.metadata.create_all(bind=engine)  # 创建全新表，已存在的表跳过
    # 创建一个数据库结构检查器
    inspector = inspect(engine)
    patched = 0  # 本次新增的列数，用于最终日志汇报

    with engine.begin() as conn:  # engine.begin() 自动管理事务，异常时回滚
        # 获取现有表
        existing_tables = set(inspector.get_table_names())
        # 遍历所有ORM表（将代码里的表结构和数据库真实表结构进行比较）
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # 新表已由 create_all() 创建，跳过
            # 获取数据库现有列
            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            # 已存在直接跳过（绝不修改现有字段）
            for column in table.columns:
                if column.name in existing_columns:
                    continue  # 列已存在，跳过

                # 生成 ADD COLUMN DDL 并执行
                ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
                conn.execute(text(f"ALTER TABLE `{table.name}` ADD COLUMN {ddl}"))

                # 有标量默认值时，对存量 NULL 行回填，保证历史数据的一致性
                default_value = _scalar_default(column)
                if default_value is not None:
                    conn.execute(
                        text(
                            f"UPDATE `{table.name}` SET `{column.name}` = :default "
                            f"WHERE `{column.name}` IS NULL"
                        ),
                        {"default": default_value},
                    )
                # 以上：1、新代码新增ORM字段，旧数据库没有，自动自动 ALTER TABLE ADD COLUMN，如果有简单默认值给历史数据回填

                patched += 1
                logger.info(f"[DB] 已补齐字段 {table.name}.{column.name}")   # 统计本次启动一共补了多少列
    # Schema检查日志
    if patched:
        logger.info(f"[DB] Schema 兼容修补完成，新增 {patched} 个字段")
    else:
        logger.info("[DB] Schema 兼容检查通过，无需补字段")


def _ensure_database_exists():
    """
    当 settings.db.auto_create 为 True 时，若目标数据库不存在则自动创建。

    实现方式:
        用不含数据库名的 server-level 连接执行 SHOW DATABASES + CREATE DATABASE，
        避免因库不存在导致 SQLAlchemy 引擎初始化失败。
        临时引擎用完后立即 dispose()，不复用全局 _engine。
    """
    database_name = settings.db.name
    charset = settings.db.charset
    if not isinstance(database_name, str) or _DATABASE_NAME_PATTERN.fullmatch(database_name) is None:
        raise ValueError("MYSQL_DB_NAME 只能包含字母、数字和下划线，且长度必须为 1 到 64 个字符")
    collation = _DATABASE_CHARSET_COLLATIONS.get(charset)
    if collation is None:
        raise ValueError(f"不支持的 MYSQL_DB_CHARSET: {charset!r}；当前仅支持 utf8mb4")

    # 构造不含库名的 server-level 连接 URL
    server_url = (
        f"mysql+pymysql://{settings.db.user}:{settings.db.password}"
        f"@{settings.db.url}:{settings.db.port}?charset={charset}"
    )
    # 临时engine
    temp_engine = create_engine(server_url, echo=False)
    try:
        # 检查数据库是否存在，不存在就创建
        with temp_engine.connect() as conn:
            result = conn.execute(
                text("SHOW DATABASES LIKE :database_name"),
                {"database_name": database_name},
            )
            if result.fetchone() is None:
                conn.execute(text(
                    f"CREATE DATABASE `{database_name}` "
                    f"CHARACTER SET {charset} COLLATE {collation}"
                ))
                conn.commit()
                logger.info(f"[DB] 自动创建数据库: {database_name}")
    finally:
        temp_engine.dispose()  # 释放临时连接，不污染全局连接池

def dispose():
    """
    优雅关闭全局数据库连接池。

    等待所有连接归还后关闭连接池，并将全局单例重置为 None，
    允许下次调用 get_engine() 时重新初始化（如测试场景的 teardown）。
    进程退出时由 Orchestrator 调用，确保连接资源被正确释放。
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()            # 当前 Engine 的连接池不要再继续用了，释放其中的连接资源。
        _engine = None
        _session_factory = None
        logger.info("[DB] 数据库连接池已释放")
