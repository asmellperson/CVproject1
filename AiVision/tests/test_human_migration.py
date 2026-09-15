"""人员逗留离线迁移：真实事务、冲突、恢复和独立旧表清理。"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import os
import json
import sqlite3
import uuid

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, event, inspect, select, text
from sqlalchemy.engine import make_url
from fastapi import FastAPI
from fastapi.testclient import TestClient
from auth.auth import get_current_user
from AiVision.api.features import create_features_router
from AiVision.api.deps import get_current_orchestrator

from AiVision.migrations import human_20260915 as migration
from AiVision.features.detect_human import SPEC
from AiVision.cameras.orm import AiCameraConfig
from AiVision.alarms.devices.orm import AiHornConfig
from AiVision.platform.violation.orm import AiAlarmEvent


def test_retired_feature_has_no_registration_or_http_alias():
    from AiVision.features import get_spec
    assert get_spec(migration.OLD) is None
    app = FastAPI()
    app.include_router(create_features_router(None))
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    app.dependency_overrides[get_current_orchestrator] = lambda: None
    with TestClient(app) as client:
        for suffix in ("", "/configs/camera-2", "/cameras/camera-2/status"):
            assert client.get(f"/api/features/{migration.OLD}{suffix}").status_code == 404


def populate(engine):
    metadata = MetaData()
    for table in (AiCameraConfig.__table__, AiHornConfig.__table__, SPEC.orm_class.__table__, AiAlarmEvent.__table__):
        table.to_metadata(metadata)
    old = SPEC.orm_class.__table__.to_metadata(metadata, name=migration.SOURCE)
    for index in old.indexes:
        index.name = index.name.replace(migration.NEW, migration.OLD)
    for constraint in old.constraints:
        if constraint.name:
            constraint.name = constraint.name.replace(migration.NEW, migration.OLD)
    Table(migration.LINKS, metadata, Column("id", Integer, primary_key=True),
          Column("feature_name", String(100)), Column("department", String(100)))
    metadata.create_all(engine)
    stamp = datetime(2026, 9, 14, 12, 0)
    with engine.begin() as connection:
        for camera_id, department in ((1, "general_electric"), (2, "haoda_company"), (3, "haoda_company")):
            functions = {} if camera_id == 1 else {migration.OLD: camera_id == 2}
            connection.execute(metadata.tables[migration.CAMERAS].insert(), dict(
                id=camera_id, name=f"camera-{camera_id}", shm_name=f"camera-{camera_id}", url="test-only",
                department=department, function_config=functions, updated_at=stamp))
            canonical = {**migration._default_row(), "id": camera_id, "camera_id": camera_id,
                         "created_at": stamp, "updated_at": stamp}
            source = deepcopy(canonical)
            if camera_id == 1:
                canonical.update(enable=True, MAX_TIME=12.)
            else:
                source.update(enable=camera_id == 2, MAX_TIME=31. + camera_id, cap_interval=.25,
                              sql_enable=True, wechat_enable=True, wechat_user="test-recipient",
                              roi_pos=[[0., 0.], [.5, 0.], [.5, .5]], alarm_interval=55.)
            connection.execute(metadata.tables[migration.TARGET].insert(), canonical)
            connection.execute(old.insert(), source)
        connection.execute(metadata.tables[migration.ALARMS].insert(), dict(
            id=1, violation_type=5, feature_name=migration.OLD, department="haoda_company",
            camera_no="camera-2", subject_type="camera", subject_id="camera-2", image_path="unchanged-image.png",
            event_metadata={"feature_name": migration.OLD, "department": "haoda_company", "dwell_time": 44},
            create_time=stamp))
        connection.execute(metadata.tables[migration.LINKS].insert(), dict(
            id=1, feature_name=migration.OLD, department="haoda_company"))
    return metadata.tables


@pytest.fixture
def legacy(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'human.sqlite'}")
    tables = populate(engine)
    yield engine, tables, tmp_path / "backup.json"
    engine.dispose()


def snapshot(engine, tables):
    with engine.connect() as connection:
        return {name: migration._rows(connection, table) for name, table in tables.items()}


def test_read_only_apply_verify_restore_and_drop(legacy, auth_database):
    engine, tables, backup = legacy
    before = snapshot(engine, tables)
    report = migration.run(engine, auth_db=auth_database)
    assert report["transferred_camera_ids"] == [2, 3]
    assert report["source_default_camera_ids"] == [1]
    assert snapshot(engine, tables) == before
    assert not backup.exists()
    migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert os.stat(backup).st_mode & 0o777 == 0o600
    after = snapshot(engine, tables)
    assert after[migration.SOURCE] == before[migration.SOURCE]
    assert after[migration.TARGET][0] == before[migration.TARGET][0]
    for row in after[migration.TARGET][1:]:
        assert row == before[migration.SOURCE][row["id"] - 1]
    for row in after[migration.CAMERAS][1:]:
        assert row["function_config"] == {migration.NEW: row["id"] == 2}
    alarm = after[migration.ALARMS][0]
    assert alarm["feature_name"] == alarm["event_metadata"]["feature_name"] == migration.NEW
    assert alarm["id"] == 1 and alarm["image_path"] == "unchanged-image.png"
    assert after[migration.LINKS][0]["feature_name"] == migration.NEW
    migration.run(engine, auth_db=auth_database, action="verify", backup=backup)
    migration.run(engine, auth_db=auth_database, action="restore", backup=backup)
    assert snapshot(engine, tables) == before
    second_backup = backup.with_name("second.json")
    migration.run(engine, auth_db=auth_database, action="apply", backup=second_backup)
    migration.run(engine, auth_db=auth_database, action="drop-old", backup=second_backup)
    assert migration.SOURCE not in inspect(engine).get_table_names()
    migration.run(engine, auth_db=auth_database, action="verify", backup=second_backup)


@pytest.mark.parametrize("conflict", ["two_configs", "two_keys", "enable_mismatch", "ownership", "alarm", "links", "nested"])
def test_conflicts_fail_before_any_write_or_backup(legacy, conflict, auth_database):
    engine, tables, backup = legacy
    with engine.begin() as connection:
        if conflict == "two_configs":
            connection.execute(tables[migration.TARGET].update().where(tables[migration.TARGET].c.camera_id == 2).values(MAX_TIME=99))
        elif conflict in {"two_keys", "enable_mismatch", "nested"}:
            value = {migration.OLD: True, migration.NEW: False} if conflict == "two_keys" else (
                {migration.OLD: False} if conflict == "enable_mismatch" else {"unknown": migration.OLD})
            connection.execute(tables[migration.CAMERAS].update().where(tables[migration.CAMERAS].c.id == 2).values(function_config=value))
        elif conflict == "ownership":
            connection.execute(tables[migration.CAMERAS].update().where(tables[migration.CAMERAS].c.id == 2).values(department=None))
        elif conflict == "alarm":
            connection.execute(tables[migration.ALARMS].update().values(department="general_electric"))
        else:
            connection.execute(tables[migration.LINKS].insert(), dict(id=2, feature_name=migration.NEW, department="haoda_company"))
    before = snapshot(engine, tables)
    with pytest.raises(ValueError):
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert snapshot(engine, tables) == before
    assert not backup.exists()


def test_sql_failure_rolls_back_all_changes_and_retains_backup(legacy, monkeypatch, auth_database):
    engine, tables, backup = legacy
    before = snapshot(engine, tables)
    write = migration._write_changes
    def fail(connection, old, new):
        write(connection, old, new)
        raise RuntimeError("injected transaction failure")
    monkeypatch.setattr(migration, "_write_changes", fail)
    with pytest.raises(RuntimeError):
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert snapshot(engine, tables) == before
    assert backup.exists()


def test_missing_target_allocates_new_id_without_colliding(legacy, auth_database):
    engine, tables, backup = legacy
    with engine.begin() as connection:
        connection.execute(tables[migration.TARGET].delete().where(tables[migration.TARGET].c.camera_id == 2))
    migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    with engine.connect() as connection:
        rows = migration._rows(connection, tables[migration.TARGET])
    assert [(row["id"], row["camera_id"]) for row in rows] == [(1, 1), (3, 3), (4, 2)]


def test_changed_data_blocks_verify_restore_and_drop(legacy, auth_database):
    engine, tables, backup = legacy
    migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    with engine.begin() as connection:
        connection.execute(tables[migration.TARGET].update().values(MAX_TIME=66))
    before = snapshot(engine, tables)
    for action in ("verify", "restore", "drop-old"):
        with pytest.raises(ValueError, match="镜像"):
            migration.run(engine, auth_db=auth_database, action=action, backup=backup)
    assert snapshot(engine, tables) == before
    assert migration.SOURCE in inspect(engine).get_table_names()


def test_unknown_persistent_reference_or_schema_never_discarded(legacy, auth_database):
    engine, tables, backup = legacy
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE custom_permissions (id INTEGER PRIMARY KEY, feature TEXT)")
        connection.execute(text("INSERT INTO custom_permissions VALUES (1, :feature)"), {"feature": migration.OLD})
    with pytest.raises(ValueError, match="持久化引用"):
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert not backup.exists()


@pytest.mark.parametrize("duplicate", [False, True])
def test_persistent_function_catalog_conversion_and_conflict(legacy, duplicate, auth_database):
    engine, tables, backup = legacy
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE ai_function (id INTEGER PRIMARY KEY, name VARCHAR(100), "
                                  "description TEXT, required_models JSON, config_table_name VARCHAR(100), "
                                  "import_path VARCHAR(100), enable BOOLEAN, created_at TIMESTAMP, updated_at TIMESTAMP)")
        function = migration._table(connection, migration.FUNCTIONS)
        connection.execute(function.insert(), dict(id=10, name=migration.OLD,
            config_table_name=migration.SOURCE, import_path="AiVision.features." + migration.OLD, enable=True))
        if duplicate:
            connection.execute(function.insert(), dict(id=11, name=migration.NEW))
    if duplicate:
        with pytest.raises(ValueError, match="重名"):
            migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
        assert not backup.exists()
    else:
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
        with engine.connect() as connection:
            row = connection.execute(select(function)).mappings().one()
        assert row["id"] == 10 and row["name"] == migration.NEW
        assert row["config_table_name"] == migration.TARGET
        assert row["import_path"] == "AiVision.features." + migration.NEW


def test_unexpected_config_column_blocks_migration(legacy, auth_database):
    engine, _, backup = legacy
    with engine.begin() as connection:
        connection.exec_driver_sql(f"ALTER TABLE {migration.SOURCE} ADD COLUMN detection_schedule JSON")
    with pytest.raises(ValueError, match="列不一致"):
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert not backup.exists()


@pytest.fixture
def auth_database(tmp_path):
    path = tmp_path / "auth.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE auth_users (employee_id TEXT PRIMARY KEY, name TEXT, role TEXT, "
                           "department TEXT, departments TEXT, enabled INTEGER, password_hash TEXT, "
                           "auth_version INTEGER, created_at TEXT, updated_at TEXT)")
        for number, (role, departments) in enumerate((
            ("viewer", ["general_electric"]), ("viewer", ["haoda_company"]),
            ("viewer", ["general_electric", "haoda_company"]), ("admin", ["all"]),
        )):
            connection.execute("INSERT INTO auth_users VALUES (?, ?, ?, ?, ?, 1, NULL, 1, 'stamp', 'stamp')",
                               (str(number), "test-" + str(number), role, departments[0], json.dumps(departments)))
    return path


def test_auth_database_is_read_only_and_rejects_unknown_legacy_permission(auth_database):
    before = auth_database.read_bytes()
    report = migration.check_auth_database(auth_database)
    assert report["auth_users"] == 4
    assert report["auth_converted_rows"] == report["auth_old_feature_references"] == 0
    assert report["auth_enabled_human_viewers"] == {"general_electric": 2, "haoda_company": 2}
    assert auth_database.read_bytes() == before
    with sqlite3.connect(auth_database) as connection:
        connection.execute("UPDATE auth_users SET departments=? WHERE employee_id='1'", (migration.OLD,))
    with pytest.raises(ValueError, match="auth_users.departments: 1 行"):
        migration.check_auth_database(auth_database)


def test_mysql_transaction_round_trip(tmp_path, auth_database):
    """仅显式无库名连接；永远不使用应用数据库，创建随机独立测试库。"""
    value = os.environ.get("HUMAN_TEST_MYSQL_URL")
    if not value:
        pytest.skip("需要 HUMAN_TEST_MYSQL_URL 才运行独立 MySQL 库测试")
    url = make_url(value)
    if url.database or url.get_backend_name() != "mysql":
        pytest.fail("测试 URL 必须为 MySQL，且不能包含已有数据库名")
    name = "test_human_merge_" + uuid.uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")
    engine = create_engine(url.set(database=name), hide_parameters=True)
    try:
        tables = populate(engine)
        before = snapshot(engine, tables)
        backup = tmp_path / "mysql-backup.json"
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
        migration.run(engine, auth_db=auth_database, action="verify", backup=backup)
        migration.run(engine, auth_db=auth_database, action="restore", backup=backup)
        assert snapshot(engine, tables) == before
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup.with_name("drop-backup.json"))
        migration.run(engine, auth_db=auth_database, action="drop-old", backup=backup.with_name("drop-backup.json"))
        assert migration.SOURCE not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f"DROP DATABASE `{name}`")
        admin.dispose()


def test_camera_21_null_receiver_is_default_without_rewriting_raw_rows(legacy, auth_database):
    engine, tables, backup = legacy
    stamp_old = datetime(2026, 8, 27, 9, 42, 46)
    stamp_new = datetime(2026, 6, 10, 15, 29, 25)
    with engine.begin() as connection:
        connection.execute(tables[migration.CAMERAS].insert(), dict(
            id=21, name="物流通道6", shm_name="camera-21", url="test-only", enable=True,
            department="general_electric", function_config={}))
        for name, row_id, stamp in ((migration.SOURCE, 11, stamp_old), (migration.TARGET, 20, stamp_new)):
            connection.execute(tables[name].insert(), dict(
                **{**migration._default_row(), "wechat_user": None},
                id=row_id, camera_id=21, created_at=stamp, updated_at=stamp))
    before = snapshot(engine, tables)
    report = migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert 21 in report["source_default_camera_ids"]
    after = snapshot(engine, tables)
    for name in (migration.SOURCE, migration.TARGET):
        assert next(r for r in after[name] if r["camera_id"] == 21) == next(
            r for r in before[name] if r["camera_id"] == 21)


@pytest.mark.parametrize("change", [
    {"MAX_TIME": 11.}, {"roi_pos": [[0., 0.], [.5, 0.], [.5, .5]]},
    {"alarm_interval": 8.}, {"wechat_user": "saved-recipient"}, {"cap_interval": .2},
])
def test_disabled_nondefault_camera_21_blocks_before_sql_write(legacy, auth_database, change):
    engine, tables, backup = legacy
    with engine.begin() as connection:
        connection.execute(tables[migration.CAMERAS].insert(), dict(
            id=21, name="物流通道6", shm_name="camera-21", url="test-only", department="general_electric"))
        for name in (migration.SOURCE, migration.TARGET):
            values = {**migration._default_row(), "wechat_user": None, **change}
            connection.execute(tables[name].insert(), dict(**values, id=21, camera_id=21))
    before = snapshot(engine, tables)
    writes = []
    def record(_conn, _cursor, statement, *_args):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE"}:
            writes.append(statement)
    event.listen(engine, "before_cursor_execute", record)
    try:
        with pytest.raises(ValueError, match="camera_id=21.*不能据此认定配置无效"):
            migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert writes == [] and not backup.exists()
    assert snapshot(engine, tables) == before


@pytest.mark.parametrize("problem", ["missing", "relative", "empty", "legacy_reference", "invalid_departments", "unknown_schema"])
def test_all_auth_prechecks_run_before_business_write(legacy, auth_database, problem, tmp_path):
    engine, tables, backup = legacy
    if problem == "missing":
        auth_database = tmp_path / "does-not-exist.sqlite"
    elif problem == "relative":
        auth_database = Path("relative-auth.sqlite")
    elif problem == "empty":
        auth_database.write_bytes(b"")
    else:
        with sqlite3.connect(auth_database) as connection:
            if problem == "unknown_schema":
                connection.execute("ALTER TABLE auth_users ADD COLUMN feature_permissions TEXT")
            else:
                value = json.dumps([migration.OLD]) if problem == "legacy_reference" else '["all"]'
                connection.execute("UPDATE auth_users SET departments=? WHERE role='viewer'", (value,))
    before = snapshot(engine, tables)
    with pytest.raises(ValueError):
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert snapshot(engine, tables) == before and not backup.exists()
    if problem == "missing":
        assert not auth_database.exists()
    with pytest.raises(ValueError, match="必须显式"):
        migration.run(engine, action="apply", backup=backup)


def test_auth_change_during_business_preflight_prevents_backup_and_writes(legacy, auth_database, monkeypatch):
    engine, tables, backup = legacy
    original = migration.preflight
    def changed(connection):
        plan = original(connection)
        with sqlite3.connect(auth_database) as auth:
            auth.execute("UPDATE auth_users SET enabled=0 WHERE role='viewer'")
        return plan
    monkeypatch.setattr(migration, "preflight", changed)
    before = snapshot(engine, tables)
    with pytest.raises(ValueError, match="认证库路径或数据"):
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert snapshot(engine, tables) == before and not backup.exists()


def test_auth_change_before_commit_rolls_back_business_and_is_not_overwritten(legacy, auth_database, monkeypatch):
    engine, tables, backup = legacy
    original = migration._write_changes
    def changed(*args):
        original(*args)
        with sqlite3.connect(auth_database) as auth:
            auth.execute("UPDATE auth_users SET enabled=0 WHERE role='viewer'")
    monkeypatch.setattr(migration, "_write_changes", changed)
    before = snapshot(engine, tables)
    with pytest.raises(ValueError, match="认证库路径或数据"):
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert snapshot(engine, tables) == before and backup.exists()
    assert migration.check_auth_database(auth_database)["auth_enabled_human_viewers"] == {
        "general_electric": 0, "haoda_company": 0,
    }


def test_auth_unchanged_and_other_database_cannot_be_substituted(legacy, auth_database, tmp_path):
    engine, _, backup = legacy
    before = auth_database.read_bytes()
    migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert auth_database.read_bytes() == before
    replacement = tmp_path / "another-auth.sqlite"
    replacement.write_bytes(before)
    for action in ("verify", "restore", "drop-old"):
        with pytest.raises(ValueError, match="禁止切换数据库"):
            migration.run(engine, auth_db=replacement, action=action, backup=backup)
    migration.run(engine, auth_db=auth_database, action="verify", backup=backup)


@pytest.mark.parametrize("camera_id,functions", [(1, {migration.OLD: False}), (2, {migration.NEW: False})])
def test_enabled_flags_must_match_the_merged_configuration(legacy, auth_database, camera_id, functions):
    engine, tables, backup = legacy
    with engine.begin() as connection:
        connection.execute(tables[migration.CAMERAS].update().where(tables[migration.CAMERAS].c.id == camera_id)
                           .values(function_config=functions))
    before = snapshot(engine, tables)
    with pytest.raises(ValueError, match="合并后配置 enable 冲突"):
        migration.run(engine, auth_db=auth_database, action="apply", backup=backup)
    assert snapshot(engine, tables) == before and not backup.exists()
