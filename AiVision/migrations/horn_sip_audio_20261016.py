"""喇叭事业部、SIP 配置和音频表；默认只读检查，应用前须停止服务。"""
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
        needs_department = "department" not in columns
        department_index = next(index for index in AiHornConfig.__table__.indexes
                                if [column.name for column in index.columns] == ["department"])
        needs_index = department_index.name not in {index["name"] for index in inspector.get_indexes(AiHornConfig.__tablename__)}
        expected = AiHornConfig.__table__.to_metadata(MetaData())
        if needs_column:
            expected._columns.remove(expected.c.sip_config)
        if needs_index:
            expected.indexes = {index for index in expected.indexes if index.name != department_index.name}
        if needs_department:
            expected._columns.remove(expected.c.department)
        assert_table_matches(connection, expected)
        needs_audio_table = not inspector.has_table(AiHornAudio.__tablename__)
        if not needs_audio_table:
            assert_table_matches(connection, AiHornAudio.__table__)
        return {"needs_sip_column": needs_column, "needs_audio_table": needs_audio_table,
                "needs_department_column": needs_department, "needs_department_index": needs_index}


def apply(engine) -> dict:
    """只做可重复的新增列和新增表，不推导或转换既有音频 ID。"""
    from AiVision.alarms.devices.orm import AiHornAudio, AiHornConfig

    plan = check(engine)
    with engine.begin() as connection:
        if plan["needs_sip_column"]:
            connection.exec_driver_sql("ALTER TABLE ai_horn_config ADD COLUMN sip_config JSON NULL")
        if plan["needs_department_column"]:
            connection.exec_driver_sql("ALTER TABLE ai_horn_config ADD COLUMN department VARCHAR(100) NULL")
        if plan["needs_department_index"]:
            for index in AiHornConfig.__table__.indexes:
                if [column.name for column in index.columns] == ["department"]:
                    index.create(connection)
        AiHornAudio.__table__.create(connection, checkfirst=True)
        assert_table_matches(connection, AiHornConfig.__table__)
        assert_table_matches(connection, AiHornAudio.__table__)
    return check(engine)


def assign_legacy_device(engine, url: str, department: str) -> int:
    """只归属明确指定地址的旧设备，跨事业部已有绑定须由管理员先整理。"""
    from sqlalchemy.orm import Session
    from AiVision.alarms.devices.orm import AiHornConfig
    from AiVision.alarms.devices.references import collect_references
    from AiVision.alarms.devices.schema import HornConnectionTest
    from AiVision.departments import require_department

    url = HornConnectionTest(url=url).url
    department = require_department(department)
    with Session(engine) as session, session.begin():
        horns = [horn for horn in session.query(AiHornConfig).with_for_update().all()
                 if horn.url.rstrip("/") == url]
        if not horns:
            raise ValueError("未找到指定地址的喇叭，请在前端待分配列表中核对设备地址")
        for horn in horns:
            if horn.department not in {None, department}:
                raise ValueError("该设备已有其他事业部归属，请在前端核对后调整")
            if any(item.department != department for _, item in collect_references(session, horn.id)):
                raise ValueError("设备存在其他事业部的报警绑定，请在前端查看引用并整理后分配")
            horn.department = department
        return len(horns)


def main() -> None:
    """使用部署环境连接，只在显式 apply/offline 时改变数据库结构。"""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--apply", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--legacy-department")
    parser.add_argument("--legacy-device-url")
    args = parser.parse_args()
    if args.apply and not args.offline:
        parser.error("请先停止服务，再提供 --apply --offline")
    if bool(args.legacy_department) != bool(args.legacy_device_url) or (args.legacy_department and not args.apply):
        parser.error("设备归属须同时提供 --apply --legacy-department 和 --legacy-device-url")
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from AiVision.core.db import get_engine
    engine = get_engine()
    try:
        result = apply(engine) if args.apply else check(engine)
        if args.legacy_department:
            result["assigned_devices"] = assign_legacy_device(engine, args.legacy_device_url, args.legacy_department)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
