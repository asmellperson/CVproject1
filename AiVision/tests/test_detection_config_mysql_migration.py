"""显式 MySQL 测试连接；每例只创建、操作和删除自身的随机独立测试库。"""
import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy import Column, Float, JSON, MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from AiVision.core.schema import assert_table_matches
from AiVision.migrations import config_20260914 as migration
from AiVision.cameras.orm import AiCameraConfig
from AiVision.platform.alarm_device.orm import AiHornConfig


@pytest.fixture
def mysql_configs():
    value = os.environ.get("CONFIG_TEST_MYSQL_URL")
    if not value:
        pytest.skip("需要 CONFIG_TEST_MYSQL_URL，测试会创建独立随机库")
    url = make_url(value)
    if url.database or url.get_backend_name() != "mysql":
        pytest.fail("测试地址须为 MySQL 且不指定已有数据库")
    name = "test_fuda_config_" + uuid.uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")
    engine = create_engine(url.set(database=name), hide_parameters=True)
    try:
        AiCameraConfig.__table__.create(engine)
        AiHornConfig.__table__.create(engine)
        metadata = MetaData()
        tables, iou, changes = {}, {}, {}
        for feature, spec in migration.specs().items():
            columns = []
            for column in spec.orm_class.__table__.columns:
                if feature in migration.DWELL and column.name in migration.IOU_FIELDS:
                    continue
                kind = Float if migration.INTEGER_CHANGES.get(feature) == column.name else column.type
                columns.append(Column(column.name, kind, primary_key=column.primary_key,
                                      nullable=not column.primary_key))
            columns.extend(Column(field, JSON if field in {"region", "YAW_THRESHOLD"} else Float)
                           for field in migration.REMOVED[feature])
            tables[feature] = Table(spec.orm_class.__tablename__, metadata, *columns)
        Table("unrelated_table", metadata, Column("value", Float))
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(AiCameraConfig.__table__.insert(), dict(id=1, name="camera", shm_name="test", url="test", department="general_electric"))
            for feature, spec in migration.specs().items():
                row = dict(spec.config_schema().value.model_dump(), id=1, camera_id=1, enable=False,
                           sql_enable=True, horn_enable=False, horn_id=None, horn_event_id=9,
                           wechat_enable=True, wechat_user="test-recipient",
                           created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 2))
                if feature in migration.DWELL:
                    for field in migration.IOU_FIELDS:
                        row.pop(field)
                    iou[feature] = {"1": {"DETECTION_IOU_THR": .2, "TRACK_IOU_THR": .8}}
                for field in migration.REMOVED[feature]:
                    row[field] = [] if field in {"region", "YAW_THRESHOLD"} else .3
                if feature == "detect_door":
                    row["env_threshold"] = 10
                    changes[feature] = {"1": {"expected": {"env_threshold": 10}, "values": {"env_threshold": None}}}
                connection.execute(tables[feature].insert(), row)
                connection.exec_driver_sql(f"ALTER TABLE `{tables[feature].name}` AUTO_INCREMENT=50")
        yield engine, tables, iou, changes
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f"DROP DATABASE `{name}`")
        admin.dispose()


def test_mysql_migration_preserves_values_backups_and_auto_increment(mysql_configs):
    engine, tables, iou, changes = mysql_configs
    assert migration.migrate(engine, iou, value_changes=changes, apply=True) == {name: 1 for name in tables}
    with engine.connect() as connection:
        for feature, spec in migration.specs().items():
            target = spec.orm_class.__table__
            assert_table_matches(connection, target)
            row = connection.execute(select(target)).mappings().one()
            assert row["updated_at"] == datetime(2026, 1, 2)
            assert row["sql_enable"] and row["wechat_user"] == "test-recipient"
            if feature in migration.DWELL:
                assert (row["DETECTION_IOU_THR"], row["TRACK_IOU_THR"]) == (.2, .8)
            if feature in migration.INTEGER_CHANGES:
                assert type(row[migration.INTEGER_CHANGES[feature]]) is int
            assert connection.exec_driver_sql(f"SELECT COUNT(*) FROM `{target.name}__cfg_backup`").scalar_one() == 1
            assert connection.execute(text("SELECT AUTO_INCREMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:name"), {"name": target.name}).scalar_one() == 50


def test_mysql_failure_before_swap_keeps_original_tables(mysql_configs, monkeypatch):
    engine, tables, iou, changes = mysql_configs
    original = migration.assert_table_matches
    def fail(connection, table, **kwargs):
        original(connection, table, **kwargs)
        if kwargs.get("actual_name"):
            raise ValueError("injected staging failure")
    monkeypatch.setattr(migration, "assert_table_matches", fail)
    with pytest.raises(ValueError, match="injected"):
        migration.migrate(engine, iou, value_changes=changes, apply=True)
    with engine.connect() as connection:
        for table in tables.values():
            assert connection.exec_driver_sql(f"SELECT COUNT(*) FROM `{table.name}`").scalar_one() == 1
        assert not any(name.endswith("__cfg_backup") for name in inspect(connection).get_table_names())
        assert connection.exec_driver_sql("SELECT env_threshold FROM ai_camera_config_detect_door").scalar_one() == 10


def test_mysql_rechecks_latest_rows_and_blocks_writers_during_copy(mysql_configs, monkeypatch):
    engine, tables, iou, changes = mysql_configs
    original_preflight = migration.preflight
    def change_after_preflight(connection, values, **kwargs):
        rows = original_preflight(connection, values, **kwargs)
        if not kwargs.get("staged"):
            with engine.begin() as writer:
                writer.exec_driver_sql("UPDATE ai_camera_config_blocks SET threshold=.7")
        return rows
    monkeypatch.setattr(migration, "preflight", change_after_preflight)
    original_assert = migration.assert_table_matches
    def check_lock(connection, table, **kwargs):
        original_assert(connection, table, **kwargs)
        if kwargs.get("actual_name") == "ai_camera_config_blocks__cfg_stage":
            with engine.connect() as writer:
                writer.exec_driver_sql("SET SESSION lock_wait_timeout=1")
                with pytest.raises(OperationalError) as error:
                    writer.exec_driver_sql("UPDATE ai_camera_config_blocks SET threshold=.9")
                assert error.value.orig.args[0] == 1205
                writer.rollback()
    monkeypatch.setattr(migration, "assert_table_matches", check_lock)
    migration.migrate(engine, iou, value_changes=changes, apply=True)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT threshold FROM ai_camera_config_blocks").scalar_one() == .7


def test_mysql_invalid_assignment_creates_no_staging(mysql_configs):
    engine, tables, iou, _ = mysql_configs
    with pytest.raises(ValueError):
        migration.migrate(engine, iou, apply=True)
    assert not any(name.endswith("__cfg_stage") for name in inspect(engine).get_table_names())
