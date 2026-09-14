"""物流配置归属的一次性离线结构迁移，默认只读检查。

只从显式环境变量读取测试/发布数据库地址，不使用应用数据库配置。
执行前必须备份并停止配置写入与检测；--apply 才删除废弃列。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import Boolean, Column, DefaultClause, Float, ForeignKey, Integer, JSON, MetaData, String, Table, cast, create_engine, inspect, select, text
from sqlalchemy.schema import CreateColumn

from AiVision.core.schema import assert_table_matches
from AiVision.migrations.value_changes import apply_row_changes, check_row_ids
from AiVision.features.detect_logistics_single_person import SPEC
from AiVision.features.detect_logistics_single_person.constants import MAX_CAMERAS_PER_CHANNEL
from AiVision.features.detect_logistics_single_person.orm import (
    LogisticsChannel, LogisticsChannelCamera, LogisticsSinglePersonConfigORM,
)
from AiVision.features.detect_logistics_single_person.schema import (
    LogisticsChannelConfigResponse, LogisticsChannelCreate,
)
from AiVision.platform.alarm_device.orm import AiHornConfig
from AiVision.platform.camera.orm import AiCameraConfig


REVISION = "logistics_feature_20260914"
REMOVED_COLUMNS = {
    "CONF_THRESHOLD", "empty_grace_seconds", "multi_grace_seconds", "alarm_interval",
    "sql_enable", "horn_enable", "horn_id", "horn_event_id", "wechat_enable", "wechat_user",
    "region",
}


def source_table():
    """仅供离线前置检查：迁移前唯一允许的摄像头表结构。"""
    metadata = MetaData()
    for table in SPEC.orm_class.metadata.sorted_tables:
        table.to_metadata(metadata)
    source = metadata.tables[SPEC.orm_class.__tablename__]
    source.c.roi_pos.server_default = DefaultClause(text("(json_array())"))
    for name in sorted(REMOVED_COLUMNS):
        if name == "region":
            column = Column(name, JSON)
        elif name in {"sql_enable", "horn_enable", "wechat_enable"}:
            column = Column(name, Boolean)
        elif name == "wechat_user":
            column = Column(name, String(255))
        elif name == "horn_id":
            column = Column(name, Integer, ForeignKey("ai_horn_config.id", ondelete="SET NULL"))
        elif name == "horn_event_id":
            column = Column(name, Integer)
        else:
            column = Column(name, Float)
        source.append_column(column)
    return source


def _validated_row(row, model):
    result = dict(row)
    # MySQL BOOLEAN 反射为 TINYINT；只接受数据库布尔域 0/1，不更改业务值。
    for column in model.__table__.columns:
        if isinstance(column.type, Boolean):
            value = result[column.name]
            if value is None or value not in (0, 1):
                raise ValueError(f"{model.__tablename__} id={row['id']}.{column.name}: 非法布尔值")
            result[column.name] = bool(value)
    return result


def _read_rows(connection, table):
    # 读取布尔列的原始数值，避免 SQLAlchemy 将非法 2 自动映射成 True。
    columns = [cast(c, Integer).label(c.name) if isinstance(c.type, Boolean) else c for c in table.columns]
    return connection.execute(select(*columns)).mappings()


def preflight(connection, *, value_changes=None):
    """验证结构、所有保留配置及成员归属；任何错误均在 DDL 前失败。"""
    dialect = connection.dialect.name
    if dialect not in {"mysql", "sqlite"}:
        raise ValueError("仅支持 MySQL 8.0.16+ 和 SQLite 隔离测试库")
    if dialect == "mysql":
        if connection.dialect.server_version_info < (8, 0, 16):
            raise ValueError("需要 MySQL 8.0.16+")
        modes = connection.exec_driver_sql("SELECT @@SESSION.sql_mode").scalar_one().split(",")
        if not {"STRICT_ALL_TABLES", "STRICT_TRANS_TABLES"}.intersection(modes):
            raise ValueError("MySQL 必须启用严格 SQL 模式")
    inspector = inspect(connection)
    table = LogisticsSinglePersonConfigORM.__table__
    required = {table.name, LogisticsChannel.__tablename__, LogisticsChannelCamera.__tablename__,
                AiCameraConfig.__tablename__, AiHornConfig.__tablename__}
    present = set(inspector.get_table_names())
    if not required <= present:
        raise ValueError(f"缺少前版本表: {sorted(required - present)}")
    expected_source = source_table()
    assert_table_matches(connection, expected_source)
    for model in (LogisticsChannel, LogisticsChannelCamera):
        assert_table_matches(connection, model.__table__)
    if dialect == "mysql":
        incoming = connection.execute(text(
            "SELECT TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE REFERENCED_TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME=:name"
        ), {"name": table.name}).scalars().all()
        if incoming:
            raise ValueError(f"{incoming} 引用摄像头功能配置表，须先审查外部外键")
    else:
        for name in present:
            for fk in inspector.get_foreign_keys(name):
                if fk["referred_table"] == table.name:
                    raise ValueError(f"{name} 引用摄像头功能配置表，须先审查外部外键")
    if dialect == "sqlite":
        triggers = connection.execute(text("SELECT tbl_name FROM sqlite_master WHERE type='trigger'")).scalars()
    else:
        triggers = connection.execute(text(
            "SELECT EVENT_OBJECT_TABLE FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()"
        )).scalars()
    if table.name in set(triggers):
        raise ValueError("摄像头配置表存在触发器，须先审查")

    actual = Table(table.name, MetaData(), autoload_with=connection)
    cameras = {row.id: row.department for row in connection.execute(select(AiCameraConfig.id, AiCameraConfig.department))}
    rows = []
    configured = set()
    source_rows = list(_read_rows(connection, actual))
    changes = {} if value_changes is None else value_changes
    check_row_ids(changes, [row["id"] for row in source_rows])
    for source in source_rows:
        source = apply_row_changes(source, changes, allowed_fields={"ASPECT_RATIO_RANGE"})
        row = _validated_row({key: source[key] for key in table.columns.keys()}, SPEC.orm_class)
        if row["camera_id"] not in cameras or row["camera_id"] in configured:
            raise ValueError(f"摄像头配置 id={row['id']}: 无效或重复 camera_id")
        configured.add(row["camera_id"])
        instance = SPEC.orm_class(**row)
        try:
            SPEC.config_schema.model_validate(instance.to_config_dict())
        except ValueError as exc:
            raise ValueError(f"摄像头配置 id={row['id']}: {exc}") from exc
        rows.append(row)

    channels = {}
    horns = {row.id: row.enable for row in connection.execute(select(AiHornConfig.id, AiHornConfig.enable))}
    for source in _read_rows(connection, LogisticsChannel.__table__):
        row = _validated_row(source, LogisticsChannel)
        channel = LogisticsChannel(**row)
        if channel.feature_name != SPEC.name or channel.department not in SPEC.departments:
            raise ValueError(f"通道 id={channel.id}: 功能或事业部不合法")
        LogisticsChannelCreate(name=channel.name, department=channel.department)
        LogisticsChannelConfigResponse.model_validate(channel)
        if channel.horn_id is not None and channel.horn_id not in horns:
            raise ValueError(f"通道 id={channel.id}: 喇叭绑定不存在")
        if channel.horn_enable and not horns[channel.horn_id]:
            raise ValueError(f"通道 id={channel.id}: 已启用告警绑定到停用喇叭")
        channels[channel.id] = channel

    assigned = set()
    counts = {}
    for source in _read_rows(connection, LogisticsChannelCamera.__table__):
        row = _validated_row(source, LogisticsChannelCamera)
        channel = channels.get(row["channel_id"])
        if channel is None or row["camera_id"] not in cameras:
            raise ValueError(f"成员 id={row['id']}: 通道或摄像头不存在")
        if cameras[row["camera_id"]] != channel.department:
            raise ValueError(f"成员 id={row['id']}: 摄像头与通道事业部不一致")
        if row["camera_id"] not in configured or row["camera_id"] in assigned:
            raise ValueError(f"成员 id={row['id']}: 缺少摄像头配置或摄像头重复归属")
        assigned.add(row["camera_id"])
        counts[channel.id] = counts.get(channel.id, 0) + 1
        if counts[channel.id] > MAX_CAMERAS_PER_CHANNEL:
            raise ValueError(f"通道 id={channel.id}: 超过最大摄像头数量")
    return rows


def migrate(engine, *, value_changes=None, apply=False):
    """MySQL 原表一次 ALTER 删除列；SQLite 测试库在事务中重建该配置表。"""
    target = LogisticsSinglePersonConfigORM.__table__
    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE" if apply else "BEGIN")
        rows = preflight(connection, value_changes=value_changes)
        if not apply:
            connection.rollback()
            return len(rows)
        locked = connection.dialect.name == "mysql"
        if locked:
            quote = connection.dialect.identifier_preparer.quote
            tables = [target.name, AiCameraConfig.__tablename__, AiHornConfig.__tablename__,
                      LogisticsChannel.__tablename__, LogisticsChannelCamera.__tablename__]
            connection.exec_driver_sql("SET SESSION lock_wait_timeout=15")
            connection.exec_driver_sql("LOCK TABLES " + ", ".join(
                f"{quote(name)} {'WRITE' if name == target.name else 'READ'}" for name in tables))
        try:
            if connection.dialect.name == "mysql":
                rows = preflight(connection, value_changes=value_changes)
                quote = connection.dialect.identifier_preparer.quote
                operations = []
                for fk in inspect(connection).get_foreign_keys(target.name):
                    if set(fk["constrained_columns"]) & REMOVED_COLUMNS:
                        operations.append(f"DROP FOREIGN KEY {quote(fk['name'])}")
                operations.extend(f"DROP COLUMN {quote(name)}" for name in sorted(REMOVED_COLUMNS))
                operations.append("MODIFY COLUMN " + str(CreateColumn(target.c.roi_pos).compile(dialect=connection.dialect)))
                connection.exec_driver_sql(f"ALTER TABLE {quote(target.name)} " + ", ".join(operations))
                # 保留配置时间戳，避免 ORM 的 onupdate 将离线赋值伪装成新的业务修改。
                for row in rows:
                    if value_changes and str(row["id"]) in value_changes:
                        connection.execute(target.update().where(target.c.id == row["id"]).values(
                            **value_changes[str(row["id"])]["values"], updated_at=row["updated_at"]))
            else:
                connection.exec_driver_sql(f'DROP TABLE "{target.name}"')
                target.create(connection)
                if rows:
                    connection.execute(target.insert(), rows)
            for model in (LogisticsSinglePersonConfigORM, LogisticsChannel, LogisticsChannelCamera):
                assert_table_matches(connection, model.__table__)
            saved = connection.execute(select(target)).mappings().all()
            if sorted([dict(row) for row in saved], key=lambda row: row["id"]) != sorted(rows, key=lambda row: row["id"]):
                raise ValueError("迁移后保留列的数据不一致")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if locked:
                connection.exec_driver_sql("UNLOCK TABLES")
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-env", default="MIGRATION_DATABASE_URL")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--value-changes", type=Path, help="按行 ID 指定 expected 原值与 values 新值")
    args = parser.parse_args()
    url = os.environ.get(args.database_url_env)
    if not url:
        parser.error(f"请显式设置 {args.database_url_env}，不读取应用连接配置")
    engine = create_engine(url, hide_parameters=True)
    try:
        changes = json.loads(args.value_changes.read_text()) if args.value_changes else {}
        count = migrate(engine, value_changes=changes, apply=args.apply)
        print(json.dumps({"revision": REVISION, "applied": args.apply, "camera_configs": count}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
