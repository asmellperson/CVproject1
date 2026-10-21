"""喇叭和企业微信独立间隔；默认只读检查，停止服务后显式应用。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import MetaData, inspect
from sqlalchemy.schema import CreateColumn

from AiVision.core.schema import assert_table_matches


INTERVAL_COLUMNS = ("horn_interval", "wechat_interval")


def _tables():
    """按正式注册功能收集告警表，包含物流通道和保安室策略。"""
    from AiVision.features.registry import all_specs
    from AiVision.features._shared.orm import FeatureConfigBase
    from AiVision.features.logistics_channel.orm import LogisticsChannel
    from AiVision.features.guard_behavior.orm import GuardBehaviorAlarmPolicy

    models = [spec.orm_class for spec in all_specs().values()
              if issubclass(spec.orm_class, FeatureConfigBase)]
    return [model.__table__ for model in (*models, LogisticsChannel, GuardBehaviorAlarmPolicy)]


def check(engine) -> dict:
    """接受新增列缺失或已就绪的结构，拒绝其他差异，不读取设备凭据。"""
    tables = _tables()
    metadata = MetaData()
    for table in tables[0].metadata.tables.values():
        table.to_metadata(metadata)
    plan, absent = {}, []
    with engine.connect() as connection:
        inspector = inspect(connection)
        for table in tables:
            if not inspector.has_table(table.name):
                # 空库和尚未建立的正式功能表由正常启动流程创建。
                absent.append(table.name)
                continue
            columns = {column["name"] for column in inspector.get_columns(table.name)}
            missing = [name for name in INTERVAL_COLUMNS if name not in columns]
            expected = metadata.tables[table.name]
            for name in missing:
                expected._columns.remove(expected.c[name])
            assert_table_matches(connection, expected)
            plan[table.name] = missing
    return {"tables": plan, "absent_tables": absent}


def apply(engine) -> dict:
    """只添加可空的间隔列；空值沿用已有间隔，保留原配置与报警绑定。"""
    plan = check(engine)
    tables = {table.name: table for table in _tables()}
    quote = engine.dialect.identifier_preparer.quote
    with engine.begin() as connection:
        for name, columns in plan["tables"].items():
            for column in columns:
                definition = CreateColumn(tables[name].c[column]).compile(dialect=engine.dialect)
                connection.exec_driver_sql(f"ALTER TABLE {quote(name)} ADD COLUMN {definition}")
    return check(engine)


def main() -> None:
    """使用部署环境连接，只在显式 apply/offline 时改变数据库结构。"""
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
    from AiVision.core.db import get_engine
    engine = get_engine()
    try:
        print(json.dumps(apply(engine) if args.apply else check(engine), ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
