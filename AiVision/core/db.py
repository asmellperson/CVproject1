"""共享 SQLAlchemy Base、延迟创建的连接池与 Session 生命周期。

所有业务 ORM 复用同一份 metadata，实际表注册和启动核验由 runtime/bootstrap.py 完成。
get_session() 的调用方负责关闭；写操作可用 session_scope() 统一提交、回滚和释放。
Session 不应跨线程共享，flush 也不代表事务已提交。
"""
from __future__ import annotations
import contextlib
import re
from sqlalchemy import create_engine, text       # create_engine:创建数据库连接引擎，inspect：查看数据库表、列，text：执行原生SQL
from sqlalchemy.orm import declarative_base, sessionmaker, Session # declarative_base:ORM模型共同的父类，sessionmaker：创建session的工厂，Session：一次数据库操作的会话
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

def get_engine():
    """
    获取全局唯一SQLAlchemy Engine，第一次调用时才创建（单例，延迟创建）。

    连接池配置说明:
        pool_size=20      : 保持的常驻连接数，适配中等并发推理场景。
        max_overflow=10   : 超出 pool_size 后最多临时扩展的连接数。
        pool_timeout      : 连接池用尽时等待的最长秒数。
        pool_recycle=3600 : 连接存活超 1 小时后强制回收，防止 MySQL 的 wait_timeout 断连。
        pool_pre_ping=True: 取连接前发送 ping，自动剔除已失效的连接。
        connect_args      : 驱动的建连、读取和写入超时，防止底层 socket 无限等待。

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
            # 连接池耗尽、建连或服务端迟迟不回包时必须让调用方恢复，不能仅依赖上层逻辑计时。
            pool_timeout=settings.db.pool_timeout_seconds,
            pool_recycle=3600,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": settings.db.connect_timeout_seconds,
                "read_timeout": settings.db.read_timeout_seconds,
                "write_timeout": settings.db.write_timeout_seconds,
            },
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
    # 建库阶段同样可能遇到网络或数据库故障，不能绕过正式 Engine 的物理超时约束。
    temp_engine = create_engine(
        server_url,
        pool_timeout=settings.db.pool_timeout_seconds,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": settings.db.connect_timeout_seconds,
            "read_timeout": settings.db.read_timeout_seconds,
            "write_timeout": settings.db.write_timeout_seconds,
        },
        echo=False,
    )
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
    """释放当前 Engine 的连接池并清空 Engine/Session 工厂引用，允许之后重新创建。

    业务线程和在用 Session 应由所属模块先关闭；本方法不等待所有业务完成，
    也不能代替摄像头、推理、写入器等运行资源各自的 stop()。
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()            # 当前 Engine 的连接池不要再继续用了，释放其中的连接资源。
        _engine = None
        _session_factory = None
        logger.info("[DB] 数据库连接池已释放")
