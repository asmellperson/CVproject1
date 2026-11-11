"""部门管理员角色枚举升级；默认只读检查，停止服务后显式应用。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import Enum, MetaData, create_engine, inspect
from sqlalchemy.schema import CreateColumn

from AiVision.core.schema import assert_table_matches


OLD_ROLES = ["admin", "viewer"]


def check(engine) -> dict:
    """只接受旧角色枚举或目标结构，其他差异应先核实，不读取任何账号凭据。"""
    from auth.orm import AuthUser
    with engine.connect() as connection:
        inspector = inspect(connection)
        if not inspector.has_table(AuthUser.__tablename__):
            return {"state": "absent", "needs_upgrade": False}
        if connection.dialect.name != "mysql":
            raise ValueError("角色枚举升级仅适用于 MySQL")
        columns = {column["name"]: column for column in inspector.get_columns(AuthUser.__tablename__)}
        roles = getattr(columns.get("role", {}).get("type"), "enums", None)
        target = AuthUser.__table__.to_metadata(MetaData())
        needs_upgrade = roles == OLD_ROLES
        if needs_upgrade:
            target.c.role.type = Enum(*OLD_ROLES)
        assert_table_matches(connection, target)
        return {"state": "upgrade_required" if needs_upgrade else "ready", "needs_upgrade": needs_upgrade}


def apply(engine) -> dict:
    """在枚举末尾追加新角色，保留已有枚举顺序、账号与权限。"""
    plan = check(engine)
    if plan["needs_upgrade"]:
        from auth.orm import AuthUser
        column = CreateColumn(AuthUser.__table__.c.role).compile(dialect=engine.dialect)
        quote = engine.dialect.identifier_preparer.quote
        with engine.begin() as connection:
            connection.exec_driver_sql(f"ALTER TABLE {quote(AuthUser.__tablename__)} MODIFY COLUMN {column}")
    return check(engine)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--apply", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.offline:
        parser.error("请先停止服务，再提供 --apply --offline")
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from AiVision.core.settings import settings
    # 迁移检查不经过自动建库入口，缺库或连接失败时直接报告错误。
    engine = create_engine(settings.db.sqlalchemy_url)
    try:
        print(json.dumps(apply(engine) if args.apply else check(engine), ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
