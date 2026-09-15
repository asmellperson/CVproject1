"""离线迁移使用真实隔离 SQLite，验证结构、数据保留和失败原子性。"""
import pytest
from sqlalchemy import create_engine, event, inspect, select, text

from AiVision.core.schema import assert_table_matches
from AiVision.features.logistics_channel.spec import SPEC
from AiVision.features.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera
from AiVision.migrations import logistics_feature_20260914 as migration
from AiVision.cameras.orm import AiCameraConfig
from AiVision.alarms.devices.orm import AiHornConfig


@pytest.fixture
def source_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'logistics.sqlite'}")
    @event.listens_for(engine, 'connect')
    def foreign_keys(dbapi, _):
        dbapi.execute('PRAGMA foreign_keys=ON')
    source = migration.source_table()
    source.metadata.create_all(engine, tables=[source.metadata.tables[name] for name in (
        AiCameraConfig.__tablename__, AiHornConfig.__tablename__, source.name,
        LogisticsChannel.__tablename__, LogisticsChannelCamera.__tablename__,
    )])
    with engine.begin() as connection:
        connection.execute(AiCameraConfig.__table__.insert(), dict(id=1, name='camera', shm_name='cam', url='test', department='general_electric'))
        connection.execute(source.insert(), dict(
            id=1, camera_id=1, enable=True, **SPEC.config_schema().value.model_dump(),
            CONF_THRESHOLD=.99, empty_grace_seconds=999, multi_grace_seconds=998,
            alarm_interval=997, sql_enable=True, horn_enable=False,
            wechat_enable=True, wechat_user='discard-camera-value',
        ))
        connection.execute(LogisticsChannel.__table__.insert(), dict(
            id=1, name='channel', feature_name=SPEC.name, department='general_electric',
            confidence_threshold=0., empty_grace_seconds=0., multi_grace_seconds=0.,
            sql_enable=True, wechat_enable=True, wechat_user='keep-channel-value',
        ))
        connection.execute(LogisticsChannelCamera.__table__.insert(), dict(channel_id=1, camera_id=1))
    yield engine, source
    engine.dispose()


def test_real_migration_keeps_three_tables_and_all_authoritative_data(source_db):
    engine, source = source_db
    with engine.connect() as connection:
        before_channel = dict(connection.execute(select(LogisticsChannel.__table__)).mappings().one())
        before_member = dict(connection.execute(select(LogisticsChannelCamera.__table__)).mappings().one())
    assert migration.migrate(engine) == 1
    assert migration.REMOVED_COLUMNS <= {c['name'] for c in inspect(engine).get_columns(source.name)}
    assert migration.migrate(engine, apply=True) == 1
    with engine.connect() as connection:
        for model in (SPEC.orm_class, LogisticsChannel, LogisticsChannelCamera):
            assert_table_matches(connection, model.__table__)
        row = connection.execute(select(SPEC.orm_class.__table__)).mappings().one()
        assert row['id'] == row['camera_id'] == 1
        assert row['enable'] is True
        assert row['IOU_THR'] == .3
        assert not migration.REMOVED_COLUMNS.intersection(row)
        assert dict(connection.execute(select(LogisticsChannel.__table__)).mappings().one()) == before_channel
        assert dict(connection.execute(select(LogisticsChannelCamera.__table__)).mappings().one()) == before_member
    with pytest.raises(ValueError, match='列不一致'):
        migration.migrate(engine, apply=True)


def test_explicit_aspect_assignment_preserves_other_camera_values(source_db):
    engine, source = source_db
    with engine.begin() as connection:
        connection.execute(source.update().values(ASPECT_RATIO_RANGE=None, enable=False))
    changes = {"1": {"expected": {"ASPECT_RATIO_RANGE": None, "enable": False},
                     "values": {"ASPECT_RATIO_RANGE": [0, 10]}}}
    assert migration.migrate(engine, value_changes=changes, apply=True) == 1
    with engine.connect() as connection:
        row = connection.execute(select(SPEC.orm_class.__table__)).mappings().one()
        assert row["ASPECT_RATIO_RANGE"] == [0, 10] and row["enable"] is False
        assert row["IOU_THR"] == .3


@pytest.mark.parametrize('assignment', [
    '"IOU_THR" = 1.1', '"IOU_THR" = NULL', '"MIN_BOX_AREA" = 0.5',
    'cap_interval = 0', "ASPECT_RATIO_RANGE = '[3, 1]'", 'enable = 2',
])
def test_invalid_retained_camera_data_blocks_ddl(source_db, assignment):
    engine, source = source_db
    with engine.begin() as connection:
        connection.exec_driver_sql(f'UPDATE "{source.name}" SET {assignment}')
    with pytest.raises(ValueError):
        migration.migrate(engine, apply=True)
    assert migration.REMOVED_COLUMNS <= {c['name'] for c in inspect(engine).get_columns(source.name)}


@pytest.mark.parametrize('sql', [
    'UPDATE ai_logistics_channel SET confidence_threshold=1.1',
    'UPDATE ai_logistics_channel SET enabled=2',
    'UPDATE ai_logistics_channel_camera SET enabled=2',
    "UPDATE ai_camera_config SET department='electronics_electrician'",
    "UPDATE ai_logistics_channel SET feature_name='unknown'",
])
def test_invalid_channel_or_membership_blocks_ddl(source_db, sql):
    engine, source = source_db
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)
    with pytest.raises(ValueError):
        migration.migrate(engine, apply=True)
    assert migration.REMOVED_COLUMNS <= {c['name'] for c in inspect(engine).get_columns(source.name)}


def test_ddl_failure_rolls_back_original_structure_and_data(source_db, monkeypatch):
    engine, source = source_db
    original = migration.assert_table_matches
    def fail_after_drop(connection, table):
        original(connection, table)
        if table is SPEC.orm_class.__table__:
            raise RuntimeError('injected post-DDL failure')
    monkeypatch.setattr(migration, 'assert_table_matches', fail_after_drop)
    with pytest.raises(RuntimeError, match='post-DDL'):
        migration.migrate(engine, apply=True)
    with engine.connect() as connection:
        assert_table_matches(connection, source)
        assert connection.execute(text(f'SELECT CONF_THRESHOLD FROM {source.name}')).scalar_one() == .99
