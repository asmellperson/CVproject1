"""普通摄像头事业部内排序的离线迁移；默认只检查，停写后显式 --apply。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import Column, Index, MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import Connection, Engine

from AiVision.cameras.orm import AiCameraConfig
from AiVision.core.schema import assert_table_matches

REVISION = "camera_order_20260916"
TABLE = AiCameraConfig.__tablename__


def preflight(connection: Connection) -> list[dict]:
    """只读核对前版本结构，按现有归属及主键生成连续顺序，不推断事业部。"""
    inspector = inspect(connection)
    if connection.dialect.name not in {"mysql", "sqlite"}:
        raise ValueError("仅支持 MySQL 和 SQLite")
    if TABLE not in inspector.get_table_names():
        raise ValueError("缺少摄像头表")
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if columns != set(AiCameraConfig.__table__.columns.keys()) - {"sort_order"}:
        raise ValueError("摄像头表不是预期前版本或已经迁移，请核对部署版本")
    previous = Table(TABLE, MetaData(), *[
        Column(column.name, column.type, primary_key=column.primary_key,
               nullable=column.nullable, server_default=column.server_default)
        for column in AiCameraConfig.__table__.columns if column.name != "sort_order"
    ])
    for index in AiCameraConfig.__table__.indexes:
        if "sort_order" not in index.columns:
            Index(index.name, *(previous.c[column.name] for column in index.columns), unique=index.unique)
    assert_table_matches(connection, previous)
    if connection.dialect.name == "mysql":
        engine = connection.execute(text(
            "SELECT ENGINE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table"
        ), {"table": TABLE}).scalar_one()
        if engine != "InnoDB":
            raise ValueError("摄像头表必须使用 InnoDB")
        triggers = connection.execute(text(
            "SELECT EVENT_OBJECT_TABLE FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()"
        )).scalars()
    else:
        triggers = connection.execute(text("SELECT tbl_name FROM sqlite_master WHERE type='trigger'")).scalars()
    if TABLE in triggers:
        raise ValueError("摄像头表存在触发器，须先人工审查")
    table = Table(TABLE, MetaData(), autoload_with=connection)
    rows = connection.execute(select(table.c.id, table.c.department)
                              .order_by(table.c.department, table.c.id)).mappings()
    positions: dict[str | None, int] = {}
    plan = []
    for row in rows:
        department = row["department"]
        position = positions.get(department, 0)
        plan.append({"id": row["id"], "department": department, "sort_order": position})
        positions[department] = position + 1
    return plan


def run(engine: Engine, *, action: str = "check", backup: Path | None = None) -> dict:
    """检查、应用或核验事业部内摄像头排序迁移。

    默认 check 只读；apply 要求独占创建备份文件，并在写入前再次核对源数据。
    MySQL DDL 会隐式提交，调用方须保持停写，失败后依据备份核查而不能假定
    事务已完全回滚。verify 检查目标结构及各事业部顺序连续性。
    """
    if action not in {"check", "apply", "verify"}:
        raise ValueError("未知迁移动作")
    with engine.connect() as connection:
        if action == "verify":
            assert_table_matches(connection, AiCameraConfig.__table__)
            table = AiCameraConfig.__table__
            rows = connection.execute(select(table.c.department, table.c.sort_order, table.c.id)
                                      .order_by(table.c.department, table.c.sort_order, table.c.id))
            positions: dict[str | None, int] = {}
            for department, position, _camera_id in rows:
                expected = positions.get(department, 0)
                if position != expected:
                    raise ValueError("摄像头顺序不连续，请在恢复写入前核查迁移")
                positions[department] = expected + 1
            return {"revision": REVISION, "result": "verified"}
        plan = preflight(connection)
        if action == "check":
            return {"revision": REVISION, "cameras": len(plan), "result": "checked"}
        if backup is None:
            raise ValueError("apply 必须提供不存在的 --backup 文件")
        snapshot = {"revision": REVISION, "database": engine.url.render_as_string(hide_password=True), "rows": plan}
        # MySQL DDL 会自动提交；必须在停写期保留备份，失败后不得直接启动新代码。
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(snapshot, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        connection.commit()
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        if preflight(connection) != plan:
            raise ValueError("摄像头集合或归属发生变化，请停止全部写入后重新检查")
        connection.exec_driver_sql(
            "ALTER TABLE ai_camera_config ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            + (" COMMENT '事业部内摄像头展示排序'" if connection.dialect.name == "mysql" else "")
        )
        connection.exec_driver_sql("CREATE INDEX ix_ai_camera_config_sort_order ON ai_camera_config (sort_order)")
        # 只回填新增列，保留原有归属、物理开关和所有 Feature 配置。
        if plan:
            connection.execute(text("UPDATE ai_camera_config SET sort_order=:sort_order WHERE id=:id"), plan)
        assert_table_matches(connection, AiCameraConfig.__table__)
        table = AiCameraConfig.__table__
        rows = connection.execute(select(table.c.id, table.c.department, table.c.sort_order)
                                  .order_by(table.c.department, table.c.id)).mappings().all()
        if [dict(row) for row in rows] != plan:
            raise ValueError("摄像头归属或排序回填核验失败，请保持停写并核查备份")
        connection.commit()
        return {"revision": REVISION, "cameras": len(plan), "result": "applied"}


def main() -> None:
    """解析离线迁移动作，写入必须显式声明停写并提供专用数据库环境变量。"""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    for action in ("check", "apply", "verify"):
        actions.add_argument(f"--{action}", dest="action", action="store_const", const=action)
    parser.set_defaults(action="check")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--offline", action="store_true", help="确认服务和全部数据库写入均已停止")
    args = parser.parse_args()
    if args.action == "apply" and not args.offline:
        parser.error("写操作必须显式提供 --offline")
    url = os.environ.get("CAMERA_ORDER_MIGRATION_DATABASE_URL")
    if not url:
        parser.error("必须显式设置 CAMERA_ORDER_MIGRATION_DATABASE_URL")
    engine = create_engine(url, echo=False)
    try:
        print(json.dumps(run(engine, action=args.action, backup=args.backup), ensure_ascii=False))
    except ValueError as exc:
        parser.exit(1, f"迁移停止：{exc}\n")
    except Exception as exc:
        parser.exit(1, f"迁移停止：{type(exc).__name__}；保持停写，核对备份及数据库结构后再处理。\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
