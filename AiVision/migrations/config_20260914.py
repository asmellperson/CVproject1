"""统一检测配置的一次性离线迁移。

不读取应用连接串，不在应用启动时调用。默认只检查；--apply 才写库。
新 IOU 参数由 --iou-values 显式逐行指定，不读取旧 IOU 值或替换非法数据。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path

from sqlalchemy import Boolean, MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.schema import CreateIndex, CreateTable

from AiVision.core.schema import assert_table_matches
from AiVision.features import all_specs


REVISION = "config_20260914"
REMOVED = {
    "blocks": {"blur_kernel", "diff_threshold", "diff_threshold_env", "env_threshold"},
    "detect_door": {"blur_kernel"},
    "detect_face": {"YAW_THRESHOLD", "IOU_THR"},
    "detect_human": {"IOU_THR"},
    "detect_human_haoda": {"IOU_THR"},
    "detect_phone": set(),
}
DWELL = {"detect_face", "detect_human", "detect_human_haoda"}
IOU_FIELDS = {"DETECTION_IOU_THR", "TRACK_IOU_THR"}
INTEGER_CHANGES = {"detect_face": "MAX_LOST", "detect_phone": "MIN_CONSECUTIVE_HITS"}


def specs():
    from AiVision.platform.alarm_device import orm as alarm_orm  # noqa: F401
    from AiVision.platform.camera import orm as camera_orm  # noqa: F401
    registry = all_specs()
    if not set(REMOVED) <= set(registry):
        raise ValueError("检测模块注册不完整，停止迁移")
    return {name: registry[name] for name in REMOVED}


def _integer(value, location):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value != int(value):
        raise ValueError(f"{location}: 必须是整数，禁止截断")
    return int(value)


def preflight(connection, iou_values: dict):
    """只读：核对前版本列集合、引用/触发器和每行最终配置；全通过才允许写库。"""
    if connection.dialect.name not in {"mysql", "sqlite"}:
        raise ValueError("仅支持 MySQL 8.0.16+ 和 SQLite 隔离测试数据库")
    if connection.dialect.name == "mysql" and connection.dialect.server_version_info < (8, 0, 16):
        raise ValueError("需要 MySQL 8.0.16+，确保 CHECK 约束实际生效")
    if connection.dialect.name == "mysql":
        sql_modes = set(connection.exec_driver_sql("SELECT @@SESSION.sql_mode").scalar_one().split(","))
        if not sql_modes.intersection({"STRICT_ALL_TABLES", "STRICT_TRANS_TABLES"}):
            raise ValueError("MySQL 必须启用严格 SQL 模式，禁止静默截断或自动填充")
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    targets = specs()
    selected = {spec.orm_class.__tablename__ for spec in targets.values()}
    if not selected <= table_names:
        raise ValueError(f"缺少前版本表: {sorted(selected - table_names)}")
    if set(iou_values) - DWELL:
        raise ValueError("IOU 文件含未定义功能名")
    for table_name in table_names:
        for fk in inspector.get_foreign_keys(table_name):
            if fk["referred_table"] in selected:
                raise ValueError(f"{table_name} 引用待迁移配置表，须先处理外部外键")
    if connection.dialect.name == "sqlite":
        triggers = connection.execute(text("SELECT tbl_name FROM sqlite_master WHERE type='trigger'")).scalars()
    else:
        triggers = connection.execute(text(
            "SELECT EVENT_OBJECT_TABLE FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()"
        )).scalars()
    if selected.intersection(triggers):
        raise ValueError("配置表存在触发器，须先人工审查")

    result = {}
    for name, spec in targets.items():
        target = spec.orm_class.__table__
        for suffix in ("__cfg_stage", "__cfg_backup"):
            if target.name + suffix in table_names:
                raise ValueError(f"{target.name + suffix} 已存在；可能是上次迁移遗留，禁止覆盖")
        actual = Table(target.name, MetaData(), autoload_with=connection)
        added = IOU_FIELDS if name in DWELL else set()
        expected = (set(target.columns.keys()) - added) | REMOVED[name]
        if set(actual.columns.keys()) != expected:
            raise ValueError(f"{target.name}: 不是预期的前版本结构或已经迁移，停止")
        rows = []
        source_rows = connection.execute(select(actual)).mappings().all()
        configured_ids = set(iou_values.get(name, {}))
        row_ids = {str(row["id"]) for row in source_rows}
        if name in DWELL and configured_ids != row_ids:
            raise ValueError(f"{name}: IOU 文件必须准确覆盖配置行 ID: {sorted(row_ids)}")
        for source in source_rows:
            row = {key: value for key, value in source.items() if key not in REMOVED[name]}
            if name in DWELL:
                explicit = iou_values[name][str(row["id"])]
                if set(explicit) != IOU_FIELDS:
                    raise ValueError(f"{name} id={row['id']}: 必须且只能提供两个新 IOU 字段")
                row.update(explicit)
            if name in INTEGER_CHANGES:
                field = INTEGER_CHANGES[name]
                row[field] = _integer(row[field], f"{name} id={row['id']}.{field}")
            # MySQL 反射把 BOOLEAN 返回为 TINYINT；只接受数据库布尔域 0/1。
            for column in target.columns:
                if isinstance(column.type, Boolean):
                    if row[column.name] not in (False, True, 0, 1) or row[column.name] is None:
                        raise ValueError(f"{name} id={row['id']}.{column.name}: 不是合法布尔值")
                    row[column.name] = bool(row[column.name])
            # 所有保留值逐项验证，包括 NULL、范围、非整数和无效 JSON。
            instance = spec.orm_class(**row)
            try:
                spec.config_schema.model_validate({
                    "enable": instance.enable,
                    "value": instance.to_value_dict(),
                    "alarm": instance.to_alarm_dict(),
                })
            except ValueError as exc:
                raise ValueError(f"{name} id={row['id']}: 配置不合法: {exc}") from exc
            rows.append(row)
        result[name] = rows
    return result


def migrate(engine, iou_values: dict, *, apply=False):
    """检查所有行后复制到最终 ORM 表；保留主键、业务字段及全部告警绑定。"""
    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE" if apply else "BEGIN")
        rows = preflight(connection, iou_values)
        counts = {name: len(values) for name, values in rows.items()}
        if not apply:
            connection.rollback()
            return counts
        targets = specs()
        if connection.dialect.name == "sqlite":
            # SQLite DDL 处于显式事务内；任一步骤失败全部回滚。
            try:
                for name, spec in targets.items():
                    target = spec.orm_class.__table__
                    connection.exec_driver_sql(f'DROP TABLE "{target.name}"')
                    target.create(connection)
                    if rows[name]:
                        connection.execute(target.insert(), rows[name])
                    assert_table_matches(connection, target)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        else:
            # MySQL DDL 自动提交；先建立并核验全部 staging 表，再原子交换表名。
            # 失败保留 staging 供排查，原表不变；交换成功保留 backup 供离线回滚。
            renames = []
            for name, spec in targets.items():
                target = spec.orm_class.__table__
                next_id = connection.execute(text(
                    "SELECT AUTO_INCREMENT FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table_name"
                ), {"table_name": target.name}).scalar_one()
                metadata = MetaData()
                for dependency in target.metadata.sorted_tables:
                    dependency.to_metadata(metadata)
                stage = target.to_metadata(metadata, name=target.name + "__cfg_stage")
                stage.create(connection)
                if rows[name]:
                    connection.execute(stage.insert(), rows[name])
                connection.commit()
                if next_id is not None:
                    connection.exec_driver_sql(f"ALTER TABLE `{stage.name}` AUTO_INCREMENT = {int(next_id)}")
                assert_table_matches(connection, target, actual_name=stage.name)
                stored = connection.execute(select(stage)).mappings().all()
                if len(stored) != len(rows[name]):
                    raise ValueError(f"{name}: 迁移行数不一致")
                renames.append(f"`{target.name}` TO `{target.name}__cfg_backup`, `{stage.name}` TO `{target.name}`")
            connection.exec_driver_sql("RENAME TABLE " + ", ".join(renames))
            connection.commit()
            for spec in targets.values():
                assert_table_matches(connection, spec.orm_class.__table__)
        return counts


def write_schema(path: Path):
    """从最终 ORM 生成空库建表 SQL，包含配置表依赖及所有当前注册表。"""
    from sqlalchemy.dialects import mysql
    from AiVision.core.db import Base
    from AiVision.core import system_config  # noqa: F401
    from AiVision.platform.violation import orm as violation_orm  # noqa: F401
    specs()  # 注册配置表引用的摄像头与喇叭依赖
    dialect = mysql.dialect()
    statements = ["-- Generated by python -m AiVision.migrations.config_20260914 --write-schema; MySQL 8.0.16+."]
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect)).strip()
        # MySQL 方言的表选项由集合生成；排序后让生成文件可稳定审查。
        body, options = ddl.rsplit("\n)", 1)
        option_items = re.findall(r"[A-Z_]+=(?:'(?:[^'\\]|\\.)*'|[^\s]+)", options)
        statements.append(body + "\n)" + " ".join(sorted(option_items)) + ";")
        statements.extend(str(CreateIndex(index).compile(dialect=dialect)) + ";" for index in sorted(table.indexes, key=lambda item: item.name))
    path.write_text("\n".join(line.rstrip() for line in "\n\n".join(statements).splitlines()) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-env", default="MIGRATION_DATABASE_URL")
    parser.add_argument("--iou-values", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--write-schema", type=Path)
    args = parser.parse_args()
    if args.write_schema:
        write_schema(args.write_schema)
        return
    url = os.environ.get(args.database_url_env)
    if not url:
        parser.error(f"请显式设置 {args.database_url_env}；不读取应用数据库连接配置")
    iou_values = json.loads(args.iou_values.read_text()) if args.iou_values else {}
    engine = create_engine(url, hide_parameters=True)
    try:
        counts = migrate(engine, iou_values, apply=args.apply)
        print(json.dumps({"revision": REVISION, "applied": args.apply, "rows": counts}, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
