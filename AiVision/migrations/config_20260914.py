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

from sqlalchemy import Boolean, Integer, MetaData, Table, cast, create_engine, inspect, select, text
from sqlalchemy.schema import CreateIndex, CreateTable

from AiVision.core.schema import assert_table_matches
from AiVision.features import all_specs
from AiVision.migrations.value_changes import apply_row_changes, check_row_ids


REVISION = "config_20260914"
REMOVED = {
    "blocks": {"blur_kernel", "diff_threshold", "diff_threshold_env", "env_threshold"},
    "detect_door": {"blur_kernel"},
    "detect_face": {"YAW_THRESHOLD", "IOU_THR"},
    "detect_human": {"IOU_THR", "region"},
    "detect_human_haoda": {"IOU_THR", "region"},
    "detect_phone": set(),
}
DWELL = {"detect_face", "detect_human", "detect_human_haoda"}
IOU_FIELDS = {"DETECTION_IOU_THR", "TRACK_IOU_THR"}
_legacy_human_orm = None
INTEGER_CHANGES = {"detect_face": "MAX_LOST", "detect_phone": "MIN_CONSECUTIVE_HITS"}


def specs():
    global _legacy_human_orm
    from AiVision.alarms.devices import orm as alarm_orm  # noqa: F401
    from AiVision.cameras import orm as camera_orm  # noqa: F401
    registry = all_specs()
    # 冻结旧版离线迁移契约；正式 Feature 注册表不注册历史功能。
    from dataclasses import replace
    from AiVision.core.db import Base
    from AiVision.features._base.orm import FeatureConfigBase
    legacy_name = "detect_human_haoda"
    legacy_table = "ai_camera_config_" + legacy_name
    if legacy_table not in Base.metadata.tables:
        table = registry["detect_human"].orm_class.__table__.to_metadata(Base.metadata, name=legacy_table)
        for index in table.indexes:
            index.name = index.name.replace("detect_human", legacy_name)
        for constraint in table.constraints:
            if constraint.name:
                constraint.name = constraint.name.replace("detect_human", legacy_name)
    if _legacy_human_orm is None:
        _legacy_human_orm = type("LegacyHumanConfigORM", (FeatureConfigBase,), {
            "__tablename__": legacy_table, "__table__": Base.metadata.tables[legacy_table],
            **{column.name: column for column in Base.metadata.tables[legacy_table].columns},
        })
    registry[legacy_name] = replace(registry["detect_human"], name=legacy_name, orm_class=_legacy_human_orm,
                                    departments=("haoda_company",))
    if not set(REMOVED) <= set(registry):
        raise ValueError("检测模块注册不完整，停止迁移")
    return {name: registry[name] for name in REMOVED}


def _integer(value, location):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value != int(value):
        raise ValueError(f"{location}: 必须是整数，禁止截断")
    return int(value)


def preflight(connection, iou_values: dict, *, value_changes: dict | None = None, staged=False):
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
    value_changes = {} if value_changes is None else value_changes
    if not isinstance(value_changes, dict) or set(value_changes) - set(targets):
        raise ValueError("赋值计划包含未定义功能")
    selected = {spec.orm_class.__tablename__ for spec in targets.values()}
    if not selected <= table_names:
        raise ValueError(f"缺少前版本表: {sorted(selected - table_names)}")
    if set(iou_values) - DWELL:
        raise ValueError("IOU 文件含未定义功能名")
    if connection.dialect.name == "mysql":
        incoming = connection.execute(text(
            "SELECT TABLE_NAME, REFERENCED_TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE REFERENCED_TABLE_SCHEMA=DATABASE()"
        ))
        for table_name, referenced in incoming:
            if referenced in selected:
                raise ValueError(f"{table_name} 引用待迁移配置表，须先处理外部外键")
    else:
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
        for suffix in (("__cfg_backup",) if staged else ("__cfg_stage", "__cfg_backup")):
            if target.name + suffix in table_names:
                raise ValueError(f"{target.name + suffix} 已存在；可能是上次迁移遗留，禁止覆盖")
        actual = Table(target.name, MetaData(), autoload_with=connection)
        added = IOU_FIELDS if name in DWELL else set()
        expected = (set(target.columns.keys()) - added) | REMOVED[name]
        if set(actual.columns.keys()) != expected:
            raise ValueError(f"{target.name}: 不是预期的前版本结构或已经迁移，停止")
        rows = []
        # SQLite 的 BOOLEAN 反射会把非法 2 读成 True，必须读取原始数值再校验。
        source_columns = [cast(c, Integer).label(c.name) if isinstance(c.type, Boolean) else c for c in actual.columns]
        source_rows = connection.execute(select(*source_columns)).mappings().all()
        configured_ids = set(iou_values.get(name, {}))
        row_ids = {str(row["id"]) for row in source_rows}
        if name in DWELL and configured_ids != row_ids:
            raise ValueError(f"{name}: IOU 文件必须准确覆盖配置行 ID: {sorted(row_ids)}")
        changes = value_changes.get(name, {})
        check_row_ids(changes, row_ids)
        for source in source_rows:
            allowed = {"env_threshold"} if name == "detect_door" else {"ASPECT_RATIO_RANGE"} if name in {"detect_human", "detect_human_haoda"} else set()
            assigned = apply_row_changes(source, changes, allowed_fields=allowed)
            row = {key: value for key, value in assigned.items() if key not in REMOVED[name]}
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
        # 外键与唯一约束在创建 staging 前检查，避免复制中途才发现孤立配置。
        for fk in target.foreign_key_constraints:
            column, = fk.columns
            element, = fk.elements
            valid_ids = set(connection.execute(select(element.column)).scalars())
            if any(row[column.name] is not None and row[column.name] not in valid_ids for row in rows):
                raise ValueError(f"{name}.{column.name}: 存在无效外键引用")
        camera_ids = [row["camera_id"] for row in rows]
        if len(camera_ids) != len(set(camera_ids)):
            raise ValueError(f"{name}: camera_id 重复")
        result[name] = rows
    return result


def migrate(engine, iou_values: dict, *, value_changes: dict | None = None, apply=False):
    """检查所有行后复制到最终 ORM 表；保留主键、业务字段及全部告警绑定。"""
    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE" if apply else "BEGIN")
        rows = preflight(connection, iou_values, value_changes=value_changes)
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
            stages = {}
            for name, spec in targets.items():
                target = spec.orm_class.__table__
                metadata = MetaData()
                for dependency in target.metadata.sorted_tables:
                    dependency.to_metadata(metadata)
                stage = target.to_metadata(metadata, name=target.name + "__cfg_stage")
                for constraint in stage.constraints:
                    if constraint.name:
                        constraint.name = constraint.name + "__cfg"
                stage.create(connection)
                stages[name] = stage
            connection.commit()
            # 将预检查到交换之间的配置写入排除；只锁本次配置表及其摄像头/喇叭依赖。
            locks = {stage.name: "WRITE" for stage in stages.values()}
            for spec in targets.values():
                target = spec.orm_class.__table__
                locks[target.name] = "WRITE"
                for fk in target.foreign_key_constraints:
                    locks.setdefault(fk.referred_table.name, "READ")
            connection.exec_driver_sql("SET SESSION lock_wait_timeout=15")
            connection.exec_driver_sql("LOCK TABLES " + ", ".join(f"`{name}` {mode}" for name, mode in sorted(locks.items())))
            try:
                rows = preflight(connection, iou_values, value_changes=value_changes, staged=True)
                renames = []
                for name, spec in targets.items():
                    target, stage = spec.orm_class.__table__, stages[name]
                    next_id = connection.execute(text(
                        "SELECT AUTO_INCREMENT FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table_name"
                    ), {"table_name": target.name}).scalar_one()
                    if rows[name]:
                        connection.execute(stage.insert(), rows[name])
                    connection.commit()
                    if next_id is not None:
                        connection.exec_driver_sql(f"ALTER TABLE `{stage.name}` AUTO_INCREMENT = {int(next_id)}")
                    assert_table_matches(connection, target, actual_name=stage.name)
                    stored = [dict(row) for row in connection.execute(select(stage)).mappings()]
                    if sorted(stored, key=lambda row: row["id"]) != sorted(rows[name], key=lambda row: row["id"]):
                        raise ValueError(f"{name}: 迁移后保留列的数据不一致")
                    renames.append(f"`{target.name}` TO `{target.name}__cfg_backup`, `{stage.name}` TO `{target.name}`")
                connection.exec_driver_sql("RENAME TABLE " + ", ".join(renames))
                connection.commit()
                for spec in targets.values():
                    assert_table_matches(connection, spec.orm_class.__table__)
                counts = {name: len(values) for name, values in rows.items()}
            finally:
                connection.exec_driver_sql("UNLOCK TABLES")
        return counts


def write_schema(path: Path):
    """从最终 ORM 生成空库建表 SQL，包含配置表依赖及所有当前注册表。"""
    from sqlalchemy.dialects import mysql
    from AiVision.core.db import Base
    from AiVision.core import system_config  # noqa: F401
    from AiVision.alarms.records import orm as violation_orm  # noqa: F401
    specs()  # 注册配置表引用的摄像头与喇叭依赖
    dialect = mysql.dialect()
    statements = ["-- Generated by python -m AiVision.migrations.config_20260914 --write-schema; MySQL 8.0.16+."]
    for table in Base.metadata.sorted_tables:
        if table.name == "ai_camera_config_detect_human_haoda":
            continue  # 当前版本空库只创建统一表；历史表仅供上一版离线迁移读取。
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
    parser.add_argument("--value-changes", type=Path, help="按功能及行 ID 提供 expected 原值与 values 新值")
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
    value_changes = json.loads(args.value_changes.read_text()) if args.value_changes else {}
    engine = create_engine(url, hide_parameters=True)
    try:
        counts = migrate(engine, iou_values, value_changes=value_changes, apply=args.apply)
        print(json.dumps({"revision": REVISION, "applied": args.apply, "rows": counts}, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
