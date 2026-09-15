"""在隔离数据库执行真实迁移并对照最终 ORM；不访问应用数据库。"""
from pathlib import Path

import pytest
from sqlalchemy import Column, Float, Integer, JSON, MetaData, Table, create_engine, inspect, select, text

from AiVision.core.schema import assert_table_matches
from AiVision.migrations.config_20260914 import DWELL, IOU_FIELDS, REMOVED, migrate, specs, write_schema


@pytest.fixture
def legacy(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    metadata = MetaData()
    targets = specs()
    for target in next(iter(targets.values())).orm_class.metadata.sorted_tables:
        if target.name not in {s.orm_class.__tablename__ for s in targets.values()}:
            target.to_metadata(metadata)
    tables = {}
    iou_values = {}
    for name, spec in targets.items():
        target = spec.orm_class.__table__
        columns = []
        for column in target.columns:
            if name in DWELL and column.name in IOU_FIELDS:
                continue
            column_type = Float if (name, column.name) in {
                ("detect_face", "MAX_LOST"), ("detect_phone", "MIN_CONSECUTIVE_HITS")
            } else column.type
            columns.append(Column(column.name, column_type, primary_key=column.primary_key,
                                  nullable=True if not column.primary_key else False))
        for field in REMOVED[name]:
            columns.append(Column(field, JSON if field == "YAW_THRESHOLD" else Float))
        tables[name] = Table(target.name, metadata, *columns)
        if name in DWELL:
            iou_values[name] = {"1": {"DETECTION_IOU_THR": .2, "TRACK_IOU_THR": .8}}
    metadata.create_all(engine)
    with engine.begin() as connection:
        camera = metadata.tables["ai_camera_config"]
        connection.execute(camera.insert(), dict(id=1, name="camera", shm_name="test-camera", url="test", department="general_electric"))
        for name, spec in targets.items():
            config = spec.config_schema().model_dump()
            row = dict(config["value"], id=1, camera_id=1, enable=False,
                       sql_enable=True, horn_enable=False, horn_id=None, horn_event_id=9,
                       wechat_enable=True, wechat_user="migration-user")
            if name in DWELL:
                for field in IOU_FIELDS:
                    row.pop(field)
            for field in REMOVED[name]:
                row[field] = [0, .3] if field == "YAW_THRESHOLD" else .4
            connection.execute(tables[name].insert(), row)
    yield engine, tables, iou_values
    engine.dispose()


def test_migration_actual_structure_data_and_defaults(legacy):
    engine, tables, iou_values = legacy
    assert migrate(engine, iou_values) == {name: 1 for name in specs()}
    assert "IOU_THR" in {c["name"] for c in inspect(engine).get_columns(tables["detect_face"].name)}
    migrate(engine, iou_values, apply=True)
    with engine.connect() as connection:
        for name, spec in specs().items():
            target = spec.orm_class.__table__
            assert_table_matches(connection, target)
            row = connection.execute(select(target)).mappings().one()
            assert row["sql_enable"] is True
            assert row["horn_event_id"] == 9
            assert row["wechat_user"] == "migration-user"
            assert not REMOVED[name].intersection(row)
            if name in DWELL:
                assert row["DETECTION_IOU_THR"] == .2
                assert row["TRACK_IOU_THR"] == .8
            if name == "detect_face":
                assert type(row["MAX_LOST"]) is int
            if name == "detect_phone":
                assert type(row["MIN_CONSECUTIVE_HITS"]) is int
            if name == "detect_door":
                assert row["env_threshold"] is None
    with pytest.raises(ValueError, match="已经迁移"):
        migrate(engine, iou_values, apply=True)


@pytest.mark.parametrize("feature,field,value", [
    ("detect_face", "MAX_LOST", 1.5), ("detect_face", "MAX_LOST", -1),
    ("detect_phone", "MIN_CONSECUTIVE_HITS", 2.1), ("detect_phone", "MIN_CONSECUTIVE_HITS", 0),
    ("detect_door", "env_threshold", 10), ("detect_door", "threshold", 1.1),
    ("detect_door", "global_motion_threshold", -1),
    ("detect_human", "ASPECT_RATIO_RANGE", None),
])
def test_invalid_data_blocks_all_mutation(legacy, feature, field, value):
    engine, tables, iou_values = legacy
    with engine.begin() as connection:
        connection.execute(tables[feature].update().values({field: value}))
    before = {name: inspect(engine).get_columns(table.name) for name, table in tables.items()}
    with pytest.raises(ValueError):
        migrate(engine, iou_values, apply=True)
    for name, table in tables.items():
        assert [c["name"] for c in inspect(engine).get_columns(table.name)] == [c["name"] for c in before[name]]


def test_missing_or_invalid_explicit_iou_blocks_migration(legacy):
    engine, tables, iou_values = legacy
    with pytest.raises(ValueError, match="准确覆盖"):
        migrate(engine, {}, apply=True)
    iou_values["detect_face"]["1"]["TRACK_IOU_THR"] = 1.1
    with pytest.raises(ValueError):
        migrate(engine, iou_values, apply=True)
    assert "IOU_THR" in {c["name"] for c in inspect(engine).get_columns(tables["detect_face"].name)}


def test_explicit_environment_assignment_is_checked_and_saved(legacy):
    engine, tables, iou_values = legacy
    with engine.begin() as connection:
        connection.execute(tables["detect_door"].update().values(env_threshold=10))
    with pytest.raises(ValueError, match="前置值"):
        migrate(engine, iou_values, value_changes={"detect_door": {"1": {"expected": {"env_threshold": 2}, "values": {"env_threshold": None}}}}, apply=True)
    migrate(engine, iou_values, value_changes={"detect_door": {"1": {"expected": {"env_threshold": 10}, "values": {"env_threshold": None}}}}, apply=True)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT env_threshold FROM ai_camera_config_detect_door")).scalar_one() is None


def test_aspect_assignment_requires_original_value_and_disabled_state(legacy):
    engine, tables, iou_values = legacy
    changes = {"detect_human": {"1": {"expected": {"ASPECT_RATIO_RANGE": None, "enable": False},
                                       "values": {"ASPECT_RATIO_RANGE": [0, 10]}}}}
    with engine.begin() as connection:
        connection.execute(tables["detect_human"].update().values(ASPECT_RATIO_RANGE=None, enable=True))
    with pytest.raises(ValueError, match="前置值"):
        migrate(engine, iou_values, value_changes=changes, apply=True)
    with engine.begin() as connection:
        connection.execute(tables["detect_human"].update().values(enable=False))
    migrate(engine, iou_values, value_changes=changes, apply=True)
    with engine.connect() as connection:
        target = specs()["detect_human"].orm_class.__table__
        assert connection.execute(select(target.c.ASPECT_RATIO_RANGE)).scalar_one() == [0, 10]


@pytest.mark.parametrize("assignment", [
    None,
    {"expected": {"env_threshold": None}, "values": {"env_threshold": 2}},
    {"expected": {}, "values": {"env_threshold": None}},
    {"expected": {"camera_id": 1}, "values": {"camera_id": 2}},
])
def test_invalid_explicit_assignment_cannot_bypass_validation(legacy, assignment):
    engine, tables, iou_values = legacy
    with pytest.raises(ValueError):
        migrate(engine, iou_values, value_changes={"detect_door": {"1": assignment}}, apply=True)
    assert "blur_kernel" in {c["name"] for c in inspect(engine).get_columns(tables["detect_door"].name)}


@pytest.mark.parametrize("field,value", [("camera_id", 999), ("horn_id", 999), ("sql_enable", 2)])
def test_bad_reference_or_boolean_blocks_mutation(legacy, field, value):
    engine, tables, iou_values = legacy
    with engine.begin() as connection:
        connection.execute(text(f"UPDATE ai_camera_config_blocks SET {field}=:value"), {"value": value})
    with pytest.raises(ValueError):
        migrate(engine, iou_values, apply=True)
    assert "blur_kernel" in {c["name"] for c in inspect(engine).get_columns(tables["blocks"].name)}


def test_sqlite_ddl_failure_rolls_back_all_tables(legacy, monkeypatch):
    from AiVision.migrations import config_20260914 as migration
    engine, tables, iou_values = legacy
    def fail(*args, **kwargs):
        raise ValueError("injected failure")
    monkeypatch.setattr(migration, "assert_table_matches", fail)
    with pytest.raises(ValueError, match="injected failure"):
        migrate(engine, iou_values, apply=True)
    with engine.connect() as connection:
        for table in tables.values():
            assert len(connection.execute(select(table)).all()) == 1


def test_committed_mysql_create_sql_matches_orm(tmp_path):
    output = tmp_path / "schema.sql"
    write_schema(output)
    committed = Path(__file__).parents[1] / "migrations" / "schema_mysql.sql"
    assert output.read_text() == committed.read_text()


def test_startup_rejects_old_schema_without_adding_columns(legacy, monkeypatch):
    from AiVision.core import db
    from AiVision.runtime.bootstrap import bootstrap_database
    engine, tables, _ = legacy
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    with pytest.raises(ValueError, match="离线迁移"):
        bootstrap_database()
    columns = {c["name"] for c in inspect(engine).get_columns(tables["detect_face"].name)}
    assert "IOU_THR" in columns
    assert not IOU_FIELDS.intersection(columns)
