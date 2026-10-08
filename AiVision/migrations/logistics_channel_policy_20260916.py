"""物流检测策略上收通道的离线迁移；冲突必须人工处理，运行时不读取旧字段。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import Boolean, Column, Integer, Table, cast, create_engine, inspect, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import CreateColumn

from AiVision.cameras.orm import AiCameraConfig
from AiVision.core.schema import assert_table_matches
from AiVision.departments.department_registry import require_department
from AiVision.features.logistics_channel.constants import require_logistics_feature
from AiVision.migrations.logistics_feature_20260914 import target_tables as source_tables
from AiVision.features.logistics_channel.orm import (
    LogisticsChannel,
    LogisticsChannelCamera,
    LogisticsSinglePersonConfigORM,
)
from AiVision.features.logistics_channel.schema import (
    LogisticsChannelConfigResponse,
    LogisticsChannelConfigUpdate,
    LogisticsCameraRoiUpdate,
)

REVISION = "logistics_channel_policy_20260916"
CHANNEL_FIELDS = ("model_iou_threshold", "min_box_area", "min_aspect_ratio", "max_aspect_ratio", "cap_interval")
REMOVED_FIELDS = ("IOU_THR", "MIN_BOX_AREA", "ASPECT_RATIO_RANGE", "cap_interval")


class ChannelPolicyConflict(ValueError):
    """提供所有冲突通道及各成员原值，禁止默选某路策略。"""

    def __init__(self, conflicts: list[dict]):
        """保留所有成员参数冲突详情，供人工确定最终策略后重新迁移。"""
        self.conflicts = conflicts
        super().__init__("通道成员检测参数不一致，必须在部署前明确处理：" + json.dumps(conflicts, ensure_ascii=False))


def _rows(connection: Connection, table: Table) -> list[dict]:
    """按主键读取并严格验证原始布尔值，生成可比较的数据快照。"""
    columns = [
        cast(column, Integer).label(column.name) if isinstance(column.type, Boolean) else column
        for column in table.columns
    ]
    rows = [dict(row) for row in connection.execute(select(*columns).order_by(table.c.id)).mappings()]
    for row in rows:
        for column in table.columns:
            if isinstance(column.type, Boolean):
                if row[column.name] not in (0, 1):
                    raise ValueError(f"{table.name} id={row['id']}.{column.name}: 必须为 0 或 1")
                row[column.name] = bool(row[column.name])
    return rows


def preflight(connection: Connection) -> dict:
    """只读核验表结构、引用和成员策略，全部一致才生成通道级转换计划。

    不在冲突成员中任意选取策略；发现差异会汇总后抛出 ChannelPolicyConflict。
    """
    if connection.dialect.name not in {"mysql", "sqlite"}:
        raise ValueError("仅支持 MySQL 和 SQLite")
    channel_table, camera_table = source_tables()
    for table in (channel_table, camera_table, LogisticsChannelCamera.__table__):
        assert_table_matches(connection, table)
    inspector = inspect(connection)
    if connection.dialect.name == "mysql":
        if connection.dialect.server_version_info < (8, 0, 16):
            raise ValueError("需要 MySQL 8.0.16+")
        modes = connection.exec_driver_sql("SELECT @@SESSION.sql_mode").scalar_one().split(",")
        if not {"STRICT_TRANS_TABLES", "STRICT_ALL_TABLES"}.intersection(modes):
            raise ValueError("MySQL 必须启用严格 SQL 模式")
        for table in (channel_table, camera_table):
            engine = connection.execute(
                text("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:name"),
                {"name": table.name},
            ).scalar_one()
            if engine != "InnoDB":
                raise ValueError(f"{table.name} 必须为 InnoDB")
        triggers = connection.execute(
            text("SELECT EVENT_OBJECT_TABLE FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()")
        ).scalars()
    else:
        triggers = connection.execute(text("SELECT tbl_name FROM sqlite_master WHERE type='trigger'")).scalars()
    if {channel_table.name, camera_table.name}.intersection(triggers):
        raise ValueError("待迁移表存在触发器，必须先人工审查")
    if connection.dialect.name == "mysql":
        # 锁表期间只读取外键元数据，避免 SHOW CREATE TABLE 访问未锁定的无关业务表。
        incoming_foreign_keys = connection.execute(
            text(
                "SELECT DISTINCT TABLE_NAME, REFERENCED_TABLE_NAME "
                "FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_SCHEMA=DATABASE() "
                "AND REFERENCED_TABLE_NAME IN (:camera_table, :channel_table)"
            ),
            {"camera_table": camera_table.name, "channel_table": channel_table.name},
        ).all()
    else:
        incoming_foreign_keys = [
            (name, foreign_key["referred_table"])
            for name in inspector.get_table_names()
            for foreign_key in inspector.get_foreign_keys(name)
        ]
    for name, referred_table in incoming_foreign_keys:
        if referred_table == camera_table.name:
            raise ValueError(f"{name} 引用待缩减的摄像头配置表，必须先人工审查")
        if referred_table == channel_table.name and name != LogisticsChannelCamera.__tablename__:
            raise ValueError(f"{name} 存在未声明的通道外键，必须先人工审查")
    channels = _rows(connection, channel_table)
    cameras = _rows(connection, camera_table)
    members = _rows(connection, LogisticsChannelCamera.__table__)
    by_camera = {row["camera_id"]: row for row in cameras}
    by_channel = {row["id"]: row for row in channels}
    camera_departments = dict(connection.execute(select(AiCameraConfig.id, AiCameraConfig.department)).all())
    for camera in cameras:
        LogisticsCameraRoiUpdate(roi_pos=camera["roi_pos"])
    channel_members: dict[int, list[int]] = {channel_id: [] for channel_id in by_channel}
    assigned = set()
    for member in members:
        channel_id, camera_id = member["channel_id"], member["camera_id"]
        if channel_id not in by_channel or camera_id not in by_camera or camera_id not in camera_departments:
            raise ValueError(f"成员 id={member['id']}: 缺少通道、摄像头或配置")
        channel = by_channel[channel_id]
        identity = (channel["feature_name"], camera_id)
        if identity in assigned or camera_departments[camera_id] != channel["department"]:
            raise ValueError(f"成员 id={member['id']}: 重复绑定或摄像头事业部与通道不一致")
        assigned.add(identity)
        channel_members[channel_id].append(camera_id)
    defaults = LogisticsChannelConfigUpdate().model_dump()
    converted, conflicts = [], []
    for channel in channels:
        require_department(channel["department"])
        require_logistics_feature(channel["feature_name"])
        policies = {}
        for camera_id in channel_members[channel["id"]]:
            row = by_camera[camera_id]
            aspect = row["ASPECT_RATIO_RANGE"]
            if not isinstance(aspect, list) or len(aspect) != 2:
                raise ValueError(
                    f"channel_id={channel['id']} camera_id={camera_id}: ASPECT_RATIO_RANGE 必须是两个明确数值"
                )
            values = dict(
                model_iou_threshold=row["IOU_THR"],
                min_box_area=row["MIN_BOX_AREA"],
                min_aspect_ratio=aspect[0],
                max_aspect_ratio=aspect[1],
                cap_interval=row["cap_interval"],
            )
            try:
                LogisticsChannelConfigUpdate(**values)
            except ValueError as exc:
                raise ValueError(f"channel_id={channel['id']} camera_id={camera_id}: 检测策略不合法：{exc}") from exc
            policies[camera_id] = values
        differences = {
            field: [{"camera_id": camera_id, "value": values[field]} for camera_id, values in policies.items()]
            for field in CHANNEL_FIELDS
            if len({values[field] for values in policies.values()}) > 1
        }
        if differences:
            conflicts.append({"channel_id": channel["id"], "channel_name": channel["name"], "fields": differences})
            continue
        # 只有全部成员一致才提取共同值；没有成员时使用正式默认值。
        values = {
            field: next(iter({policy[field] for policy in policies.values()})) if policies else defaults[field]
            for field in CHANNEL_FIELDS
        }
        final = {**channel, **values}
        LogisticsChannelConfigResponse.model_validate(SimpleNamespace(**final))
        converted.append(final)
    if conflicts:
        raise ChannelPolicyConflict(conflicts)
    return {"channels": channels, "camera_configs": cameras, "members": members, "converted_channels": converted}


def _verify(connection: Connection, plan: dict) -> None:
    """逐表核对目标结构及完整数据，SQLite 额外检查外键完整性。"""
    for table, expected in (
        (LogisticsChannel.__table__, plan["converted_channels"]),
        (
            LogisticsSinglePersonConfigORM.__table__,
            [{key: value for key, value in row.items() if key not in REMOVED_FIELDS} for row in plan["camera_configs"]],
        ),
        (LogisticsChannelCamera.__table__, plan["members"]),
    ):
        assert_table_matches(connection, table)
        if _rows(connection, table) != expected:
            raise ValueError(f"{table.name}: 迁移后数据不一致，请保持停写并核查备份")
    if connection.dialect.name == "sqlite" and connection.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise ValueError("迁移后外键核验失败")


def migrate(engine: Engine, *, apply: bool = False, backup: Path | None = None) -> dict:
    """默认预检；显式应用时先保存独占备份，再把一致的成员策略写入通道。

    MySQL 使用锁表并重新核对源快照，DDL 不具备整批回滚保证；SQLite 在
    独占事务内重建目标表。结束时释放锁并恢复原有外键检查设置。
    """
    with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() if sqlite else None
        if sqlite and apply:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        locked = False
        try:
            plan = preflight(connection)
            if not apply:
                return {"revision": REVISION, "channels": len(plan["channels"]), "applied": False}
            if backup is None:
                raise ValueError("写操作必须提供不存在的 --backup 文件")
            descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump({"revision": REVISION, **plan}, output, ensure_ascii=False, indent=2, default=str)
                output.flush()
                os.fsync(output.fileno())
            if not sqlite:
                # MySQL DDL 会隐式提交；部署期间必须停写并保留完整前版本数据备份。
                connection.commit()
                connection.exec_driver_sql("SET SESSION lock_wait_timeout=15")
                connection.exec_driver_sql(
                    "LOCK TABLES ai_logistics_channel WRITE, ai_camera_config_detect_logistics_single_person WRITE, ai_logistics_channel_camera READ, ai_camera_config READ"
                )
                locked = True
                if preflight(connection) != plan:
                    raise ValueError("迁移检查后数据发生变化，请停止全部写入后重新检查")
                quote = connection.dialect.identifier_preparer.quote
                additions = [
                    str(
                        CreateColumn(Column(field, LogisticsChannel.__table__.c[field].type, nullable=True)).compile(
                            dialect=connection.dialect
                        )
                    )
                    for field in CHANNEL_FIELDS
                ]
                connection.exec_driver_sql(
                    "ALTER TABLE ai_logistics_channel " + ", ".join("ADD COLUMN " + column for column in additions)
                )
                if plan["converted_channels"]:
                    connection.execute(
                        text(
                            "UPDATE ai_logistics_channel SET "
                            + ", ".join(f"{quote(field)}=:{field}" for field in CHANNEL_FIELDS)
                            + " WHERE id=:id"
                        ),
                        plan["converted_channels"],
                    )
                modifications = [
                    str(CreateColumn(LogisticsChannel.__table__.c[field]).compile(dialect=connection.dialect))
                    for field in CHANNEL_FIELDS
                ]
                connection.exec_driver_sql(
                    "ALTER TABLE ai_logistics_channel "
                    + ", ".join("MODIFY COLUMN " + column for column in modifications)
                )
                connection.exec_driver_sql(
                    "ALTER TABLE ai_camera_config_detect_logistics_single_person "
                    + ", ".join("DROP COLUMN " + quote(field) for field in REMOVED_FIELDS)
                )
            else:
                for table, rows in (
                    (LogisticsChannel.__table__, plan["converted_channels"]),
                    (
                        LogisticsSinglePersonConfigORM.__table__,
                        [
                            {key: value for key, value in row.items() if key not in REMOVED_FIELDS}
                            for row in plan["camera_configs"]
                        ],
                    ),
                ):
                    connection.exec_driver_sql(f'DROP TABLE "{table.name}"')
                    table.create(connection)
                    if rows:
                        connection.execute(table.insert(), rows)
            _verify(connection, plan)
            connection.commit()
            return {"revision": REVISION, "channels": len(plan["channels"]), "applied": True}
        finally:
            connection.rollback()
            if locked:
                connection.exec_driver_sql("UNLOCK TABLES")
            if sqlite and apply:
                connection.exec_driver_sql(f"PRAGMA foreign_keys={int(foreign_keys)}")


def main() -> None:
    """要求专用连接环境变量，应用迁移须显式声明离线并提供备份路径。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--offline", action="store_true", help="确认已停止全部检测服务和配置写入")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.apply and not args.offline:
        parser.error("写操作必须显式提供 --offline")
    url = os.environ.get("LOGISTICS_POLICY_MIGRATION_DATABASE_URL")
    if not url:
        parser.error("必须显式设置 LOGISTICS_POLICY_MIGRATION_DATABASE_URL")
    engine = create_engine(url, hide_parameters=True)
    try:
        print(json.dumps(migrate(engine, apply=args.apply, backup=args.backup), ensure_ascii=False))
    except ValueError as exc:
        parser.exit(1, f"迁移停止：{exc}\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
