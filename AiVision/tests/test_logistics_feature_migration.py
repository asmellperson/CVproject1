"""离线迁移使用真实隔离 SQLite，验证结构、数据保留和失败原子性。"""
import pytest
from sqlalchemy import create_engine, event, inspect, select, text

from AiVision.core.schema import assert_table_matches
from AiVision.features.logistics_channel.spec import SPEC
from AiVision.features.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera
from AiVision.migrations import logistics_feature_20260914 as migration
from AiVision.cameras.orm import AiCameraConfig
from AiVision.alarms.devices.orm import AiHornConfig

CHANNEL_TABLE, CONFIG_TABLE = migration.target_tables()


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
        connection.execute(CHANNEL_TABLE.insert(), dict(
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
        before_channel = dict(connection.execute(select(CHANNEL_TABLE)).mappings().one())
        before_member = dict(connection.execute(select(LogisticsChannelCamera.__table__)).mappings().one())
    assert migration.migrate(engine) == 1
    assert migration.REMOVED_COLUMNS <= {c['name'] for c in inspect(engine).get_columns(source.name)}
    assert migration.migrate(engine, apply=True) == 1
    with engine.connect() as connection:
        for table in (CONFIG_TABLE, CHANNEL_TABLE, LogisticsChannelCamera.__table__):
            assert_table_matches(connection, table)
        row = connection.execute(select(CONFIG_TABLE)).mappings().one()
        assert row['id'] == row['camera_id'] == 1
        assert row['enable'] is True
        assert row['IOU_THR'] == .3
        assert not migration.REMOVED_COLUMNS.intersection(row)
        assert dict(connection.execute(select(CHANNEL_TABLE)).mappings().one()) == before_channel
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
        row = connection.execute(select(CONFIG_TABLE)).mappings().one()
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
        if table.name == CONFIG_TABLE.name and not migration.REMOVED_COLUMNS.intersection(table.c.keys()):
            raise RuntimeError('injected post-DDL failure')
    monkeypatch.setattr(migration, 'assert_table_matches', fail_after_drop)
    with pytest.raises(RuntimeError, match='post-DDL'):
        migration.migrate(engine, apply=True)
    with engine.connect() as connection:
        assert_table_matches(connection, source)
        assert connection.execute(text(f'SELECT CONF_THRESHOLD FROM {source.name}')).scalar_one() == .99


@pytest.fixture
def policy_db(source_db):
    from AiVision.migrations import logistics_channel_policy_20260916 as policy
    engine, _ = source_db
    migration.migrate(engine, apply=True)
    channel_table, camera_table = policy.source_tables()
    with engine.begin() as connection:
        connection.execute(AiCameraConfig.__table__.insert(), dict(id=2, name='second', shm_name='second', url='test', department='general_electric'))
        connection.execute(camera_table.insert(), dict(id=2, camera_id=2, enable=True, roi_pos=[[0., 0.], [1., 0.], [1., 1.]]))
        connection.execute(LogisticsChannelCamera.__table__.insert(), dict(id=2, channel_id=1, camera_id=2, enabled=False, sort_order=7))
        connection.execute(channel_table.insert(), dict(id=2, name='empty', feature_name=SPEC.name, department='fulida_company'))
    return engine, channel_table, camera_table


def test_policy_migration_preserves_equal_member_values_roi_and_membership(policy_db, tmp_path):
    import json
    from AiVision.migrations import logistics_channel_policy_20260916 as policy
    from AiVision.features.logistics_channel.schema import LogisticsChannelConfigUpdate
    engine, channel_table, camera_table = policy_db
    with engine.begin() as connection:
        connection.execute(camera_table.update().values(IOU_THR=.71, MIN_BOX_AREA=17, ASPECT_RATIO_RANGE=[.4, 2.8], cap_interval=.63))
        before = policy.preflight(connection)
    report = policy.migrate(engine)
    assert report['applied'] is False
    backup = tmp_path / 'policy-backup.json'
    assert policy.migrate(engine, apply=True, backup=backup)['applied'] is True
    assert backup.stat().st_mode & 0o777 == 0o600
    assert json.loads(backup.read_text())['camera_configs'][0]['IOU_THR'] == .71
    with engine.connect() as connection:
        channels = list(connection.execute(select(LogisticsChannel.__table__).order_by(LogisticsChannel.id)).mappings())
        assert {field: channels[0][field] for field in policy.CHANNEL_FIELDS} == dict(
            model_iou_threshold=.71, min_box_area=17, min_aspect_ratio=.4, max_aspect_ratio=2.8, cap_interval=.63)
        defaults = LogisticsChannelConfigUpdate().model_dump()
        assert {field: channels[1][field] for field in policy.CHANNEL_FIELDS} == {field: defaults[field] for field in policy.CHANNEL_FIELDS}
        assert channels[0]['confidence_threshold'] == 0.
        assert channels[0]['updated_at'] == before['channels'][0]['updated_at']
        assert dict(connection.execute(select(SPEC.orm_class.__table__).where(SPEC.orm_class.camera_id == 2)).mappings().one()) == {
            key: value for key, value in before['camera_configs'][1].items() if key not in policy.REMOVED_FIELDS}
        assert [dict(row) for row in connection.execute(select(LogisticsChannelCamera.__table__).order_by(LogisticsChannelCamera.id)).mappings()] == before['members']
        assert not set(policy.REMOVED_FIELDS) & {column['name'] for column in inspect(connection).get_columns(camera_table.name)}
        assert set(policy.CHANNEL_FIELDS) <= {column['name'] for column in inspect(connection).get_columns(channel_table.name) if not column['nullable']}
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


@pytest.mark.parametrize('field,value,reported', [
    ('IOU_THR', .72, ['model_iou_threshold']), ('MIN_BOX_AREA', 16, ['min_box_area']),
    ('ASPECT_RATIO_RANGE', [.5, 3.], ['min_aspect_ratio', 'max_aspect_ratio']),
    ('cap_interval', .6, ['cap_interval']),
])
def test_policy_conflicts_include_disabled_members_and_abort_before_ddl(policy_db, tmp_path, field, value, reported):
    from AiVision.migrations import logistics_channel_policy_20260916 as policy
    engine, channel_table, camera_table = policy_db
    with engine.begin() as connection:
        connection.execute(camera_table.update().where(camera_table.c.camera_id == 2).values(**{field: value}))
    backup = tmp_path / 'blocked.json'
    with pytest.raises(policy.ChannelPolicyConflict) as error:
        policy.migrate(engine, apply=True, backup=backup)
    conflict, = error.value.conflicts
    assert conflict['channel_id'] == 1 and conflict['channel_name'] == 'channel'
    assert set(conflict['fields']) == set(reported)
    assert {entry['camera_id'] for entry in conflict['fields'][reported[0]]} == {1, 2}
    assert not backup.exists()
    with engine.connect() as connection:
        assert_table_matches(connection, channel_table)
        assert_table_matches(connection, camera_table)


def test_policy_migration_checks_equality_per_channel(policy_db, tmp_path):
    from AiVision.migrations import logistics_channel_policy_20260916 as policy
    engine, _, camera_table = policy_db
    with engine.begin() as connection:
        connection.execute(AiCameraConfig.__table__.update().where(AiCameraConfig.id == 2).values(department='fulida_company'))
        connection.execute(LogisticsChannelCamera.__table__.update().where(LogisticsChannelCamera.camera_id == 2).values(channel_id=2))
        connection.execute(camera_table.update().where(camera_table.c.camera_id == 2).values(IOU_THR=.9, cap_interval=.8))
    policy.migrate(engine, apply=True, backup=tmp_path / 'independent.json')
    with engine.connect() as connection:
        rows = connection.execute(select(LogisticsChannel.__table__).order_by(LogisticsChannel.id)).mappings().all()
        assert rows[0]['model_iou_threshold'] == .3 and rows[1]['model_iou_threshold'] == .9
        assert rows[0]['cap_interval'] == .2 and rows[1]['cap_interval'] == .8


def test_policy_migration_failure_restores_sqlite_source(policy_db, tmp_path, monkeypatch):
    from AiVision.migrations import logistics_channel_policy_20260916 as policy
    engine, channel_table, camera_table = policy_db
    def fail_verification(_connection, _plan):
        raise RuntimeError('injected verification failure')
    monkeypatch.setattr(policy, '_verify', fail_verification)
    with pytest.raises(RuntimeError, match='verification'):
        policy.migrate(engine, apply=True, backup=tmp_path / 'rollback.json')
    with engine.connect() as connection:
        assert_table_matches(connection, channel_table)
        assert_table_matches(connection, camera_table)
        assert connection.execute(select(camera_table.c.IOU_THR).where(camera_table.c.camera_id == 1)).scalar_one() == .3
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one() == 1


@pytest.mark.parametrize('referenced_table, message', [
    ('ai_camera_config_detect_logistics_single_person', '引用待缩减的摄像头配置表'),
    ('ai_logistics_channel', '存在未声明的通道外键'),
])
def test_policy_sqlite_rejects_unexpected_incoming_foreign_keys(policy_db, tmp_path, referenced_table, message):
    from AiVision.migrations import logistics_channel_policy_20260916 as policy
    engine, channel_table, camera_table = policy_db
    with engine.begin() as connection:
        connection.exec_driver_sql(
            'CREATE TABLE policy_external_reference (id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL, '
            f'FOREIGN KEY (target_id) REFERENCES "{referenced_table}" (id))'
        )
    backup = tmp_path / 'blocked-foreign-key.json'
    with pytest.raises(ValueError, match=message):
        policy.migrate(engine, apply=True, backup=backup)
    assert not backup.exists()
    with engine.connect() as connection:
        assert_table_matches(connection, channel_table)
        assert_table_matches(connection, camera_table)
