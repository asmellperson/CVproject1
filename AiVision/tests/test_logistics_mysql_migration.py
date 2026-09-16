"""离线验证 MySQL 迁移分支；元数据与锁由 mock 提供，不连接真实 MySQL。"""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pymysql
import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import dialect as mysql_dialect
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.sql.elements import TextClause

from AiVision.core.schema import assert_table_matches
from AiVision.features.logistics_channel.orm import LogisticsChannelCamera
from AiVision.migrations import logistics_channel_policy_20260916 as policy
from AiVision.tests.test_logistics_feature_migration import (
    policy_db as policy_db,
    source_db as source_db,
)

UNRELATED_TABLES = (
    "ai_camera_config_blocks",
    "ai_camera_config_detect_face",
    "ai_camera_config_detect_human",
)


class ReachedMigrationDDL(RuntimeError):
    """在首次 DDL 前结束模拟，实际数据迁移由 SQLite 集成测试验证。"""


def _require_offline_mysql_test() -> None:
    url = os.environ.get("LOGISTICS_TEST_MYSQL_URL")
    if url:
        parsed = make_url(url)
        if parsed.database or parsed.get_backend_name() != "mysql":
            pytest.fail("测试连接必须为 MySQL 且不得指定已有数据库")
        pytest.fail("离线 MySQL 测试不接受真实连接，请移除 LOGISTICS_TEST_MYSQL_URL")


@pytest.fixture(autouse=True)
def forbid_mysql_connections(monkeypatch):
    blocked = Mock(side_effect=AssertionError("离线测试禁止连接真实 MySQL"))
    monkeypatch.setattr(pymysql, "connect", blocked)
    monkeypatch.setattr(pymysql.connections.Connection, "connect", blocked)
    return blocked


@pytest.fixture
def mysql_source(policy_db, monkeypatch):
    _require_offline_mysql_test()
    sqlite_engine, channel_table, camera_table = policy_db
    with sqlite_engine.begin() as sqlite_connection:
        for name in UNRELATED_TABLES:
            sqlite_connection.exec_driver_sql(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY)')
    with sqlite_engine.connect() as sqlite_connection:
        sqlite_inspector = inspect(sqlite_connection)
        member_fk = (LogisticsChannelCamera.__tablename__, channel_table.name)
        state = SimpleNamespace(
            locked=False,
            locks={},
            statements=[],
            accesses=[],
            incoming={False: [member_fk], True: [member_fk]},
            storage_engine="InnoDB",
            sql_mode="STRICT_TRANS_TABLES",
            triggers=[],
        )
        connection = MagicMock(spec=Connection)
        connection.dialect = mysql_dialect()
        connection.dialect.server_version_info = (8, 0, 44)
        connection.__enter__.return_value = connection
        engine = MagicMock(spec=Engine)
        engine.connect.return_value = connection

        def record_access(name):
            state.accesses.append((state.locked, name))
            if state.locked and name not in state.locks:
                raise AssertionError(f"锁表后访问了未锁定表：{name}")

        def table_names():
            if state.locked:
                raise AssertionError("锁表后不得遍历全部业务表")
            return sqlite_inspector.get_table_names()

        def foreign_keys(name):
            record_access(name)
            return sqlite_inspector.get_foreign_keys(name)

        inspector = Mock()
        inspector.get_table_names.side_effect = table_names
        inspector.get_foreign_keys.side_effect = foreign_keys

        def check_schema(candidate, table):
            assert candidate is connection
            record_access(table.name)
            assert_table_matches(sqlite_connection, table)

        def execute(statement, parameters=None):
            sql = str(statement)
            state.statements.append((state.locked, sql, parameters))
            if isinstance(statement, TextClause):
                if "information_schema.KEY_COLUMN_USAGE" in sql:
                    assert "TABLE_SCHEMA=DATABASE()" in sql
                    assert "REFERENCED_TABLE_SCHEMA=DATABASE()" in sql
                    assert "REFERENCED_TABLE_NAME IN (:camera_table, :channel_table)" in sql
                    assert parameters == {
                        "camera_table": camera_table.name,
                        "channel_table": channel_table.name,
                    }
                    return Mock(all=Mock(return_value=list(state.incoming[state.locked])))
                if "information_schema.TABLES" in sql:
                    record_access(parameters["name"])
                    return Mock(scalar_one=Mock(return_value=state.storage_engine))
                if "information_schema.TRIGGERS" in sql:
                    return Mock(scalars=Mock(return_value=tuple(state.triggers)))
                raise AssertionError(f"未声明的元数据查询：{sql}")
            assert statement.is_select, "模拟连接只允许读取 SQLite 测试数据"
            for table in statement.get_final_froms():
                record_access(table.name)
            return sqlite_connection.execute(statement, parameters or {})

        def exec_driver_sql(sql):
            state.statements.append((state.locked, sql, None))
            if sql == "SELECT @@SESSION.sql_mode":
                return Mock(scalar_one=Mock(return_value=state.sql_mode))
            if sql == "SET SESSION lock_wait_timeout=15":
                return None
            if sql.startswith("LOCK TABLES "):
                assert not state.locked
                state.locks = dict(
                    item.strip().replace("`", "").split()
                    for item in sql.removeprefix("LOCK TABLES ").split(",")
                )
                state.locked = True
                return None
            if sql == "UNLOCK TABLES":
                assert state.locked
                state.locked = False
                return None
            if sql.startswith("ALTER TABLE "):
                assert state.locked
                record_access(sql.split()[2])
                raise ReachedMigrationDDL(sql)
            raise AssertionError(f"未声明的 MySQL 操作：{sql}")

        connection.execute.side_effect = execute
        connection.exec_driver_sql.side_effect = exec_driver_sql
        monkeypatch.setattr(policy, "inspect", lambda candidate: inspector if candidate is connection else inspect(candidate))
        monkeypatch.setattr(policy, "assert_table_matches", check_schema)
        yield SimpleNamespace(
            engine=engine,
            connection=connection,
            inspector=inspector,
            state=state,
            sqlite_connection=sqlite_connection,
            camera_table=camera_table,
            channel_table=channel_table,
        )


def test_mysql_policy_checks_metadata_under_locks_before_ddl(mysql_source, tmp_path, forbid_mysql_connections):
    source = mysql_source
    backup = tmp_path / "policy.json"
    with pytest.raises(ReachedMigrationDDL, match="ALTER TABLE ai_logistics_channel ADD COLUMN"):
        policy.migrate(source.engine, apply=True, backup=backup)

    metadata_queries = [
        (locked, sql) for locked, sql, _ in source.state.statements
        if "information_schema.KEY_COLUMN_USAGE" in sql
    ]
    assert [locked for locked, _ in metadata_queries] == [False, True]
    assert source.state.locks == {
        "ai_logistics_channel": "WRITE",
        "ai_camera_config_detect_logistics_single_person": "WRITE",
        "ai_logistics_channel_camera": "READ",
        "ai_camera_config": "READ",
    }
    assert {name for locked, name in source.state.accesses if locked} == set(source.state.locks)
    assert not set(UNRELATED_TABLES).intersection(name for _, name in source.state.accesses)
    assert not any(name in sql for _, sql, _ in source.state.statements for name in UNRELATED_TABLES)
    source.inspector.get_table_names.assert_not_called()
    source.inspector.get_foreign_keys.assert_not_called()
    assert source.state.locked is False
    assert source.state.statements[-1][1] == "UNLOCK TABLES"
    assert backup.exists() and backup.stat().st_mode & 0o777 == 0o600
    source.connection.commit.assert_called_once()
    forbid_mysql_connections.assert_not_called()


@pytest.mark.parametrize("locked_phase", [False, True])
@pytest.mark.parametrize("referenced_table,message", [
    ("ai_camera_config_detect_logistics_single_person", "引用待缩减的摄像头配置表"),
    ("ai_logistics_channel", "存在未声明的通道外键"),
])
def test_mysql_policy_rejects_unexpected_incoming_foreign_keys(
    mysql_source, tmp_path, referenced_table, message, locked_phase,
):
    source = mysql_source
    source.state.incoming[locked_phase].append(("external_feature_reference", referenced_table))
    backup = tmp_path / "blocked.json"
    with pytest.raises(ValueError, match=message):
        policy.migrate(source.engine, apply=True, backup=backup)
    assert not any(sql.startswith("ALTER TABLE ") for _, sql, _ in source.state.statements)
    assert not any(name == "external_feature_reference" for _, name in source.state.accesses)
    assert source.state.locked is False
    assert backup.exists() is locked_phase
    if locked_phase:
        assert source.state.statements[-1][1] == "UNLOCK TABLES"


@pytest.mark.parametrize("assignment", ["IOU_THR=1.1", "cap_interval=0", "enable=2"])
def test_mysql_bad_values_abort_before_alter(mysql_source, tmp_path, assignment):
    source = mysql_source
    source.sqlite_connection.exec_driver_sql(
        f'UPDATE "{source.camera_table.name}" SET {assignment}'
    )
    backup = tmp_path / "invalid-values.json"
    with pytest.raises(ValueError):
        policy.migrate(source.engine, apply=True, backup=backup)
    assert not backup.exists()
    assert not any(sql.startswith(("LOCK TABLES ", "ALTER TABLE ")) for _, sql, _ in source.state.statements)


@pytest.mark.parametrize("condition,message", [
    ("old_version", "需要 MySQL 8.0.16"),
    ("non_strict", "必须启用严格 SQL 模式"),
    ("non_innodb", "必须为 InnoDB"),
    ("trigger", "存在触发器"),
])
def test_mysql_policy_keeps_preflight_safety_checks(mysql_source, condition, message):
    source = mysql_source
    if condition == "old_version":
        source.connection.dialect.server_version_info = (8, 0, 15)
    elif condition == "non_strict":
        source.state.sql_mode = "NO_ENGINE_SUBSTITUTION"
    elif condition == "non_innodb":
        source.state.storage_engine = "MyISAM"
    else:
        source.state.triggers = [source.camera_table.name]
    with pytest.raises(ValueError, match=message):
        policy.preflight(source.connection)
    assert not any(sql.startswith("ALTER TABLE ") for _, sql, _ in source.state.statements)


@pytest.mark.parametrize("url,message", [
    ("mysql+pymysql://test@127.0.0.1/aivision", "不得指定已有数据库"),
    ("mysql+pymysql://test@127.0.0.1/test_logistics", "不得指定已有数据库"),
    ("sqlite:///:memory:", "测试连接必须为 MySQL"),
    ("mysql+pymysql://test@127.0.0.1", "离线 MySQL 测试不接受真实连接"),
])
def test_mysql_test_connection_guard_rejects_database_urls(monkeypatch, forbid_mysql_connections, url, message):
    monkeypatch.setenv("LOGISTICS_TEST_MYSQL_URL", url)
    with pytest.raises(pytest.fail.Exception, match=message):
        _require_offline_mysql_test()
    forbid_mysql_connections.assert_not_called()
