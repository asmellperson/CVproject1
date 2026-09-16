"""可选 MySQL 8 实测：显式测试连接，每例创建并删除独立测试库。"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from AiVision.core.schema import assert_table_matches
from AiVision.features.logistics_channel.spec import SPEC
from AiVision.features.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera
from AiVision.migrations import logistics_feature_20260914 as migration
from AiVision.cameras.orm import AiCameraConfig
from AiVision.alarms.devices.orm import AiHornConfig

CHANNEL_TABLE, CONFIG_TABLE = migration.target_tables()


@pytest.fixture
def mysql_source():
    url = os.environ.get('LOGISTICS_TEST_MYSQL_URL')
    if not url:
        pytest.skip('需要显式 LOGISTICS_TEST_MYSQL_URL 指向隔离 MySQL 测试实例')
    parsed = make_url(url)
    if parsed.database or parsed.get_backend_name() != 'mysql':
        pytest.fail('测试连接必须为 MySQL 且不得指定已有数据库；每例创建独立随机库')
    database = 'test_logistics_' + uuid.uuid4().hex
    admin = create_engine(parsed, hide_parameters=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE `{database}`')
    engine = create_engine(parsed.set(database=database), hide_parameters=True)
    try:
        source = migration.source_table()
        source.metadata.create_all(engine, tables=[source.metadata.tables[name] for name in (
            AiCameraConfig.__tablename__, AiHornConfig.__tablename__, source.name,
            LogisticsChannel.__tablename__, LogisticsChannelCamera.__tablename__,
        )])
        with engine.begin() as connection:
            connection.execute(AiCameraConfig.__table__.insert(), dict(id=1, name='camera', shm_name='cam', url='test', department='general_electric'))
            connection.execute(source.insert(), dict(id=1, camera_id=1, enable=True,
                **SPEC.config_schema().value.model_dump(), CONF_THRESHOLD=.99,
                empty_grace_seconds=99, multi_grace_seconds=88, alarm_interval=77,
                sql_enable=True, horn_enable=False, wechat_enable=False))
            connection.execute(CHANNEL_TABLE.insert(), dict(id=1, name='channel', feature_name=SPEC.name,
                department='general_electric', confidence_threshold=0, empty_grace_seconds=0,
                sql_enable=True, wechat_enable=True, wechat_user='keep-value'))
            connection.execute(LogisticsChannelCamera.__table__.insert(), dict(id=1, channel_id=1, camera_id=1))
            connection.exec_driver_sql(f'ALTER TABLE `{source.name}` AUTO_INCREMENT=50')
        yield engine, source
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP DATABASE `{database}`')
        admin.dispose()


def test_mysql_alter_preserves_tables_values_and_auto_increment(mysql_source):
    engine, source = mysql_source
    with engine.connect() as connection:
        unchanged = {table: [dict(row) for row in connection.execute(select(table)).mappings()]
                     for table in (CHANNEL_TABLE, LogisticsChannelCamera.__table__)}
    assert migration.migrate(engine) == 1
    assert migration.migrate(engine, apply=True) == 1
    with engine.connect() as connection:
        for table in (CONFIG_TABLE, CHANNEL_TABLE, LogisticsChannelCamera.__table__):
            assert_table_matches(connection, table)
        row = connection.execute(select(CONFIG_TABLE)).mappings().one()
        assert not migration.REMOVED_COLUMNS.intersection(row)
        for table, expected in unchanged.items():
            assert [dict(row) for row in connection.execute(select(table)).mappings()] == expected
        next_id = connection.execute(text('SELECT AUTO_INCREMENT FROM information_schema.TABLES '
            'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:name'), {'name': source.name}).scalar_one()
        assert next_id == 50
    with pytest.raises(ValueError, match='列不一致'):
        migration.migrate(engine, apply=True)


@pytest.mark.parametrize('assignment', ['IOU_THR=1.1', 'cap_interval=0', 'enable=2'])
def test_mysql_bad_values_abort_before_alter(mysql_source, assignment):
    engine, source = mysql_source
    with engine.begin() as connection:
        connection.exec_driver_sql(f'UPDATE `{source.name}` SET {assignment}')
    with pytest.raises(ValueError):
        migration.migrate(engine, apply=True)
    assert migration.REMOVED_COLUMNS <= {column['name'] for column in inspect(engine).get_columns(source.name)}


def test_mysql_aspect_assignment_preserves_timestamp(mysql_source):
    engine, source = mysql_source
    with engine.begin() as connection:
        connection.execute(source.update().values(ASPECT_RATIO_RANGE=None, enable=False))
        before = connection.execute(select(source)).mappings().one()
    changes = {'1': {'expected': {'ASPECT_RATIO_RANGE': None, 'enable': False},
                     'values': {'ASPECT_RATIO_RANGE': [0, 10]}}}
    migration.migrate(engine, value_changes=changes, apply=True)
    with engine.connect() as connection:
        row = connection.execute(select(CONFIG_TABLE)).mappings().one()
        assert row['updated_at'] == before['updated_at']
        assert row['ASPECT_RATIO_RANGE'] == [0, 10] and row['enable'] is False


def test_mysql_channel_policy_migration_removes_camera_strategy_and_keeps_values(mysql_source, tmp_path):
    from AiVision.migrations import logistics_channel_policy_20260916 as policy
    engine, _ = mysql_source
    migration.migrate(engine, apply=True)
    channel_table, camera_table = policy.source_tables()
    with engine.begin() as connection:
        connection.execute(camera_table.update().values(IOU_THR=.61, MIN_BOX_AREA=17, ASPECT_RATIO_RANGE=[.2, 3.4], cap_interval=.7))
        before = connection.execute(select(channel_table)).mappings().one()
    assert policy.migrate(engine, apply=True, backup=tmp_path / 'mysql-policy.json')['applied'] is True
    with engine.connect() as connection:
        for table in (LogisticsChannel.__table__, SPEC.orm_class.__table__, LogisticsChannelCamera.__table__):
            assert_table_matches(connection, table)
        row = connection.execute(select(LogisticsChannel.__table__)).mappings().one()
        assert row['updated_at'] == before['updated_at']
        assert row['model_iou_threshold'] == pytest.approx(.61)
        assert row['min_box_area'] == 17 and row['cap_interval'] == pytest.approx(.7)
        assert row['min_aspect_ratio'] == pytest.approx(.2) and row['max_aspect_ratio'] == pytest.approx(3.4)
        assert not set(policy.REMOVED_FIELDS) & {column['name'] for column in inspect(connection).get_columns(camera_table.name)}
