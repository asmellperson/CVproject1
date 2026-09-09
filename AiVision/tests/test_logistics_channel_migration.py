"""旧表保留、字段完整复制、冲突隔离及重复启动的兼容迁移回归。"""
from datetime import datetime
import re

import pytest
from sqlalchemy import MetaData, Table, create_engine, event, inspect, select, text
from sqlalchemy.schema import CreateTable

from AiVision.core.db import Base
from AiVision.features import all_specs
from AiVision.platform.logistics_channel.constants import LOGISTICS_FEATURE_NAME
from AiVision.platform.logistics_channel.migration import (
    LEGACY_CONFIG_TABLES, LEGACY_FEATURE_DEPARTMENTS,
    migrate_camera_feature_configs, migrate_channel_alarm_features, prepare_logistics_schema,
)
from AiVision.platform.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera
from AiVision.tests.test_logistics_channel_service import service_db, _seed_camera


def legacy_tables(engine):
    metadata = MetaData()
    canonical = Table(LEGACY_CONFIG_TABLES["general_electric"], metadata, autoload_with=engine)
    tables = {"general_electric": canonical}
    for department, name in LEGACY_CONFIG_TABLES.items():
        if department == "general_electric":
            continue
        table = Table(name, metadata, *(column._copy() for column in canonical.columns))
        table.create(engine)
        tables[department] = table
    return tables


def test_legacy_channel_schema_preserves_ids_members_all_business_fields_and_repeats():
    engine = create_engine("sqlite://")
    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, sql, params, context, many: statements.append(sql))
    others = [table for table in Base.metadata.sorted_tables if table.name not in {
        "ai_logistics_channel", "ai_logistics_channel_camera",
    }]
    Base.metadata.create_all(engine, tables=others)
    ddl = str(CreateTable(LogisticsChannel.__table__).compile(dialect=engine.dialect))
    ddl = re.sub(r"\s*department VARCHAR\(100\) NOT NULL,", "", ddl)
    ddl = ddl.replace("uq_logistics_channel_feature_department_name UNIQUE (feature_name, department, name)",
                      "uq_logistics_channel_feature_name UNIQUE (feature_name, name)")
    with engine.begin() as connection:
        connection.execute(text(ddl))
    LogisticsChannelCamera.__table__.create(engine)
    old = Table("ai_logistics_channel", MetaData(), autoload_with=engine)
    timestamp = datetime(2025, 1, 2, 3, 4, 5)
    with engine.begin() as connection:
        for index, feature in enumerate(LEGACY_FEATURE_DEPARTMENTS, 1):
            connection.execute(text("INSERT INTO ai_camera_config (id, name, shm_name, url) VALUES (:id, :name, :name, 'rtsp://example.invalid/stream')"), {"id": index, "name": f"camera-{index}"})
            connection.execute(old.insert().values(
                id=index, name="同名通道", feature_name=feature, enabled=False, sort_order=index,
                detection_start=datetime.strptime("09:13:00", "%H:%M:%S").time(),
                detection_end=datetime.strptime("18:47:00", "%H:%M:%S").time(),
                confidence_threshold=0.73, empty_grace_seconds=7.5, multi_grace_seconds=3.2,
                alarm_interval=19, sql_enable=True, horn_enable=False, horn_event_id=5,
                wechat_enable=True, wechat_user="test-user", created_at=timestamp, updated_at=timestamp,
            ))
            connection.execute(LogisticsChannelCamera.__table__.insert().values(id=index, channel_id=index, camera_id=index, enabled=True, sort_order=8))
        before = [dict(row) for row in connection.execute(select(old).order_by(old.c.id)).mappings()]
    prepare_logistics_schema(engine)
    prepare_logistics_schema(engine)
    with engine.connect() as connection:
        after = [dict(row) for row in connection.execute(select(LogisticsChannel.__table__).order_by(LogisticsChannel.id)).mappings()]
        for prior, current in zip(before, after):
            assert current == {**prior, "feature_name": LOGISTICS_FEATURE_NAME, "department": LEGACY_FEATURE_DEPARTMENTS[prior["feature_name"]]}
        assert connection.execute(select(LogisticsChannelCamera.id)).scalars().all() == [1, 2, 3, 4]
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    assert inspect(engine).has_table("ai_logistics_channel_before_department")
    assert not inspect(engine).get_columns("ai_logistics_channel")[3]["nullable"]
    assert not any("DROP TABLE" in sql.upper() for sql in statements)


def test_all_legacy_config_fields_migrate_and_rerun_never_overwrites_new_edits(service_db):
    tables = legacy_tables(service_db.engine)
    canonical = tables["general_electric"]
    timestamp = datetime(2025, 2, 3, 4, 5, 6)
    camera_ids = []
    for department in LEGACY_CONFIG_TABLES:
        camera_id = _seed_camera(service_db, department, department=department)
        camera_ids.append(camera_id)
        values = dict(camera_id=camera_id, enable=True, CONF_THRESHOLD=0.81, IOU_THR=0.62,
                      roi_pos=[[[1, 2], [20, 2], [20, 30]]], region=[1, 2, 30, 40],
                      MIN_BOX_AREA=123, ASPECT_RATIO_RANGE=[0.4, 4.2], empty_grace_seconds=9,
                      multi_grace_seconds=8, cap_interval=0.7, alarm_interval=31,
                      sql_enable=True, horn_enable=False, horn_event_id=7,
                      wechat_enable=True, wechat_user="test-recipient", created_at=timestamp, updated_at=timestamp)
        with service_db.engine.begin() as connection:
            if department == "general_electric":
                connection.execute(canonical.update().where(canonical.c.camera_id == camera_id).values(**values))
            else:
                connection.execute(tables[department].insert().values(**values))
    first = migrate_camera_feature_configs(service_db.engine)
    assert first.failed == 0 and first.created == 4
    with service_db.engine.begin() as connection:
        for camera_id, department in zip(camera_ids, LEGACY_CONFIG_TABLES):
            result = dict(connection.execute(select(canonical).where(canonical.c.camera_id == camera_id)).mappings().one())
            source = dict(connection.execute(select(tables[department]).where(tables[department].c.camera_id == camera_id)).mappings().one())
            assert {key: value for key, value in result.items() if key != "id"} == {key: value for key, value in source.items() if key != "id"}
        connection.execute(canonical.update().values(CONF_THRESHOLD=0.95))
    second = migrate_camera_feature_configs(service_db.engine)
    assert second.created == 0 and second.skipped == 4 and second.failed == 0
    with service_db.engine.connect() as connection:
        assert connection.execute(select(canonical.c.CONF_THRESHOLD)).scalars().all() == [0.95] * 4
    assert all(inspect(service_db.engine).has_table(name) for name in LEGACY_CONFIG_TABLES.values())


@pytest.mark.parametrize("enabled", [False, True])
def test_conflicting_camera_department_never_guesses_or_overwrites(service_db, enabled):
    tables = legacy_tables(service_db.engine)
    camera_id = _seed_camera(service_db, "ambiguous", department=None)
    canonical = tables["general_electric"]
    with service_db.engine.begin() as connection:
        for department in ("electronics_electrician", "electrical_components"):
            connection.execute(tables[department].insert().values(camera_id=camera_id, enable=enabled, CONF_THRESHOLD=0.8))
        before = dict(connection.execute(select(canonical)).mappings().one())
    for _ in range(2):
        result = migrate_camera_feature_configs(service_db.engine)
        assert result.failed == 1 and f"camera_id={camera_id}" in result.errors[0]
        with service_db.engine.connect() as connection:
            assert dict(connection.execute(select(canonical)).mappings().one()) == before


def test_camera_department_selects_correct_source_when_multiple_legacy_rows_exist(service_db):
    tables = legacy_tables(service_db.engine)
    camera_id = _seed_camera(service_db, "select-source", department="electrical_components")
    with service_db.engine.begin() as connection:
        connection.execute(tables["electronics_electrician"].insert().values(camera_id=camera_id, enable=True, CONF_THRESHOLD=0.91))
        connection.execute(tables["electrical_components"].insert().values(camera_id=camera_id, enable=True, CONF_THRESHOLD=0.47))
    assert migrate_camera_feature_configs(service_db.engine).failed == 0
    with service_db.engine.connect() as connection:
        assert connection.execute(select(tables["general_electric"].c.CONF_THRESHOLD)).scalar_one() == 0.47


def test_new_camera_after_migration_can_restart_with_legacy_tables_retained(service_db):
    legacy_tables(service_db.engine)
    assert migrate_camera_feature_configs(service_db.engine).failed == 0
    camera_id = _seed_camera(service_db, "new-camera", department="electronics_electrician")
    result = migrate_camera_feature_configs(service_db.engine)
    assert result.failed == 0 and result.created == 1
    with service_db.factory() as session:
        assert session.query(all_specs()[LOGISTICS_FEATURE_NAME].orm_class).filter_by(camera_id=camera_id).count() == 1
    with service_db.engine.connect() as connection:
        assert connection.execute(text("SELECT source_table FROM ai_logistics_camera_migration WHERE camera_id=:camera_id"), {"camera_id": camera_id}).scalar_one() == LEGACY_CONFIG_TABLES["general_electric"]


def test_historical_channel_alarms_remain_visible_and_preserve_payload(service_db):
    from AiVision.platform.violation.orm import AiAlarmEvent

    table = AiAlarmEvent.__table__
    table.create(service_db.engine, checkfirst=True)
    timestamp = datetime(2025, 3, 4, 5, 6, 7)
    with service_db.engine.begin() as connection:
        for index, (feature, department) in enumerate(LEGACY_FEATURE_DEPARTMENTS.items(), 1):
            connection.execute(table.insert().values(
                id=index, image_path=f"/test/{index}.jpg", video_path=f"/test/{index}.mp4",
                violation_type=6, feature_name=feature, department=department,
                subject_type="logistics_channel", subject_id=str(index), subject_name="旧通道",
                reason="multiple", event_metadata={"counts": [2, 1]}, create_time=timestamp,
            ))
        before = [dict(row) for row in connection.execute(select(table).order_by(table.c.id)).mappings()]
    migrate_channel_alarm_features(service_db.engine)
    migrate_channel_alarm_features(service_db.engine)
    with service_db.engine.connect() as connection:
        after = [dict(row) for row in connection.execute(select(table).order_by(table.c.id)).mappings()]
    assert after == [{**row, "feature_name": LOGISTICS_FEATURE_NAME} for row in before]
