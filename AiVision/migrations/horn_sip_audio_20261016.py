"""喇叭 SIP 配置列和服务器音频表；默认只读检查，应用前须停止服务。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import MetaData, inspect

from AiVision.core.schema import assert_table_matches


def check(engine) -> dict:
    """接受升级前后两种精确结构，不改变已有设备、密码和报警绑定。"""
    from AiVision.alarms.devices.orm import AiHornAudio, AiHornConfig

    with engine.connect() as connection:
        inspector = inspect(connection)
        if not inspector.has_table(AiHornConfig.__tablename__):
            raise ValueError("喇叭配置表不存在；空库请使用项目正常启动流程初始化")
        columns = {column["name"] for column in inspector.get_columns(AiHornConfig.__tablename__)}
        needs_column = "sip_config" not in columns
        expected = AiHornConfig.__table__.to_metadata(MetaData())
        if needs_column:
            expected._columns.remove(expected.c.sip_config)
        assert_table_matches(connection, expected)
        needs_audio_table = not inspector.has_table(AiHornAudio.__tablename__)
        if not needs_audio_table:
            assert_table_matches(connection, AiHornAudio.__table__)
        return {"needs_sip_column": needs_column, "needs_audio_table": needs_audio_table}


def apply(engine) -> dict:
    """只做可重复的新增列和新增表，不推导或转换既有音频 ID。"""
    from AiVision.alarms.devices.orm import AiHornAudio, AiHornConfig

    plan = check(engine)
    with engine.begin() as connection:
        if plan["needs_sip_column"]:
            connection.exec_driver_sql("ALTER TABLE ai_horn_config ADD COLUMN sip_config JSON NULL")
        AiHornAudio.__table__.create(connection, checkfirst=True)
        assert_table_matches(connection, AiHornConfig.__table__)
        assert_table_matches(connection, AiHornAudio.__table__)
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
