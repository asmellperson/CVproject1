"""预检只读、精确映射和字段边界；不连接生产数据库，不加载旧 Guard 模块。"""
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from AiVision.migrations import guard_behavior_cutover_20260917 as migration


@pytest.fixture
def dataset(tmp_path):
    database = tmp_path / "data.sqlite"
    old_root = tmp_path / "guard"
    (old_root / "src").mkdir(parents=True)
    # 复制字段声明文本用于 AST 审计，不执行旧目录代码。
    (old_root / "src/config.py").write_text((migration.OLD_ROOT / "src/config.py").read_text())
    guard_yaml = old_root / "config.yaml"
    guard_yaml.write_text("{}")
    model_paths = tmp_path / "models.yaml"
    models = {}
    old_models = {}
    for old, (name, _) in migration.MODEL_FIELDS.items():
        weight = tmp_path / f"{name}.pt"
        weight.write_bytes(b"synthetic local model")
        models[name] = {"path": str(weight)}
        old_models[old] = str(weight)
    model_paths.write_text(json.dumps({"models": models}))
    config = {section: {} for section in migration.SECTIONS}
    config["models"] = old_models
    config["runtime"] = {"enable_vehicle_unattended": True, "vehicle_camera_id": "cam1"}
    config["rules"] = {"vehicle_roi": [[0, 0], [1, 0], [1, 1]]}
    config["room"] = {"frame_width": 1920, "frame_height": 1080}
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE guard_room_site (id INTEGER, department TEXT, name TEXT, enabled BOOLEAN, sort_order INTEGER)")
        c.exec_driver_sql("CREATE TABLE guard_room_camera (id INTEGER, site_id INTEGER, name TEXT, rtsp_url TEXT, enabled BOOLEAN, sort_order INTEGER)")
        columns = ", ".join(f"{section}_json JSON" for section in migration.SECTIONS)
        c.exec_driver_sql(f"CREATE TABLE guard_room_site_config (id INTEGER, site_id INTEGER, {columns})")
        c.exec_driver_sql("CREATE TABLE ai_camera_config (id INTEGER, department TEXT, name TEXT, url TEXT, enable BOOLEAN, fps INTEGER)")
        c.exec_driver_sql("CREATE TABLE ai_guard_behavior_site (id INTEGER, department TEXT, name TEXT)")
        c.exec_driver_sql("CREATE TABLE ai_guard_behavior_site_camera (id INTEGER, site_id INTEGER, camera_id INTEGER)")
        for table in migration.NEW_TABLES[2:]:
            c.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER)")
        c.exec_driver_sql("INSERT INTO guard_room_site VALUES (1, 'general_electric', '南门', 1, 0)")
        c.exec_driver_sql("INSERT INTO guard_room_camera VALUES (10, 1, '旧名称', 'rtsp://operator:fixture@camera/1', 1, 0)")
        c.exec_driver_sql("INSERT INTO ai_camera_config VALUES (100, 'general_electric', '平台名称', 'rtsp://operator:fixture@camera/1', 1, 5)")
        parameters = {section: json.dumps(value) for section, value in config.items()}
        c.execute(text("INSERT INTO guard_room_site_config VALUES (1, 1, " + ", ".join(f":{section}" for section in config) + ")"), parameters)
    engine.dispose()

    def run():
        with migration.read_only_connection(f"sqlite:///{database}") as c:
            return migration.preflight(c, c, old_root=old_root, model_config=model_paths, guard_config=guard_yaml, env={})

    def execute(statement, parameters=()):
        with sqlite3.connect(database) as c:
            c.execute(statement, parameters)

    def update(section, values):
        config[section].update(values)
        execute(f"UPDATE guard_room_site_config SET {section}_json=?", (json.dumps(config[section]),))
    return SimpleNamespace(database=database, root=old_root, run=run, execute=execute,
                           update=update, config=config, models=model_paths)


def codes(report):
    return {item["code"] for item in report["blockers"]}


def test_preflight_is_repeatable_read_only_and_redacts_credentials(dataset):
    before = dataset.database.read_bytes()
    result = dataset.run()
    assert result["result"] == "PRECHECK PASS"
    assert result == dataset.run()
    assert dataset.database.read_bytes() == before
    assert result["sites"][0]["cameras"][0]["camera_id"] == 100
    assert "operator:fixture" not in json.dumps(result)
    assert result["sites"][0]["policy"]["vehicle_camera_id"] == 100
    assert result["sites"][0]["roi"]["normalized"] == [[0, 0], [1, 0], [1, 1]]
    with migration.read_only_connection(f"sqlite:///{dataset.database}") as connection:
        with pytest.raises(DBAPIError):
            connection.exec_driver_sql("DELETE FROM guard_room_site")


@pytest.mark.parametrize("statement,expected", [
    ("UPDATE ai_camera_config SET url='rtsp://different'", "camera_unmatched"),
    ("INSERT INTO ai_camera_config SELECT 101,department,'另一路',url,enable,fps FROM ai_camera_config", "camera_ambiguous"),
    ("UPDATE ai_camera_config SET department='electronics_electrician'", "camera_department_conflict"),
    ("INSERT INTO ai_guard_behavior_site VALUES(2,'general_electric','南门')", "site_name_conflict"),
    ("INSERT INTO ai_guard_behavior_site_camera VALUES(2,2,100)", "existing_membership"),
    ("UPDATE guard_room_site SET department='unknown'", "invalid_site"),
    ("DROP TABLE ai_guard_behavior_site_policy", "missing_tables"),
])
def test_ambiguous_or_conflicting_resources_are_blockers(dataset, statement, expected):
    dataset.execute(statement)
    assert expected in codes(dataset.run())


def test_same_name_does_not_replace_exact_rtsp_match(dataset):
    dataset.execute("UPDATE ai_camera_config SET name='旧名称', url='rtsp://other'")
    result = dataset.run()
    assert result["sites"][0]["cameras"][0]["camera_id"] is None
    assert {"camera_name_conflict", "camera_unmatched"} <= codes(result)


def test_vehicle_slot_uses_enabled_order_not_old_primary_key(dataset):
    dataset.execute("INSERT INTO guard_room_camera VALUES(2,1,'停用','rtsp://disabled',0,-1)")
    dataset.execute("INSERT INTO ai_camera_config VALUES(200,'general_electric','停用平台','rtsp://disabled',0,5)")
    result = dataset.run()
    assert result["result"] == "PRECHECK PASS"
    assert result["sites"][0]["policy"]["vehicle_camera_id"] == 100


@pytest.mark.parametrize("value,room", [
    ([[0, 0], [2, 0], [2, 2]], {}),
    ([[0, 0], [2000, 0], [2000, 1080]], {"frame_width": 1920, "frame_height": 1080}),
    ([[0, 0], [1, 1]], {}),
    ([[0, 0], [1, 0], [1, -1]], {}),
    ([{"x": 0, "y": 1}], {}),
    ([[False, 0], [1, 0], [1, 1]], {}),
    ([[0, 0], [float("nan"), 0], [1, 1]], {}),
])
def test_unreliable_roi_is_rejected(value, room):
    with pytest.raises(ValueError):
        migration.convert_roi(value, room)


def test_pixel_roi_conversion_requires_explicit_valid_dimensions():
    roi, mode = migration.convert_roi([[0, 0], [1920, 0], [1920, 1080]], {"frame_width": 1920, "frame_height": 1080})
    assert roi == [[0, 0], [1, 0], [1, 1]]
    assert mode == "pixel_converted_with_explicit_room_dimensions"
    assert migration.convert_roi([], {}) == ([], "normalized")


def test_all_old_fields_have_dispositions_and_frame_stride_is_not_seconds(dataset):
    catalog = migration.field_catalog(dataset.root / "src/config.py")
    dataset.update("video", {"process_every_n_frames": 37})
    result = dataset.run()
    dispositions = {item["field"]: item for item in result["field_dispositions"]}
    declared = {f"{section}.{key}" for section, keys in catalog.items() for key in keys}
    assert set(dispositions) == declared | {f"video.source_cam{i}" for i in range(1, 10)}
    assert all(item["action"] in {"迁移", "使用新默认值", "删除"} for item in dispositions.values())
    assert result["sites"][0]["policy"]["cap_interval"] == migration.SITE_POLICY_DEFAULTS["cap_interval"]
    dataset.update("rules", {"unhandled_future_rule": 1})
    assert "unknown_config_key" in codes(dataset.run())


def test_alarm_plan_preserves_four_intervals_and_wechat_gate(dataset):
    dataset.update("rules", {"alarm_cooldown_absent": 77, "alarm_cooldown_phone": 88,
                              "alarm_cooldown_prone_sleep": 99, "alarm_cooldown_vehicle_unattended": 111})
    dataset.update("wechat", {"enable": True, "enable_phone": False, "alarm_user": "synthetic-user", "corpsecret": "do-not-print"})
    result = dataset.run()
    policies = result["sites"][0]["alarms"]
    assert [item["violation_type"] for item in policies] == [8, 9, 10, 11]
    assert [item["alarm_interval"] for item in policies] == [77, 88, 99, 111]
    assert [item["wechat_enable"] for item in policies] == [True, False, True, True]
    assert all(not item["sql_enable"] and not item["horn_enable"] for item in policies)
    assert "wechat_global_mismatch" in codes(result)
    assert "do-not-print" not in json.dumps(result)


def test_model_gaps_and_vehicle_activation_change_are_visible(dataset):
    dataset.models.write_text('{"models": {}}')
    dataset.update("models", {"vehicle_detector_model": ""})
    result = dataset.run()
    assert len([item for item in result["blockers"] if item["code"] == "model_path_missing_or_invalid"]) == 4
    assert "vehicle_activation_change" in codes(result)


def test_history_is_counted_once_never_migrated_or_deleted(dataset):
    output = dataset.root / "outputs"
    output.mkdir()
    history = output / "alarm_events.json"
    history.write_text(json.dumps([{"event_type": "absent"}, {"event_type": "phone_use"}]))
    dataset.update("video", {"output_dir": "outputs"})
    before = history.read_bytes()
    result = dataset.run()
    assert result["history"]["count"] == 2
    assert len(result["history"]["files"]) == 1
    assert history.read_bytes() == before
    assert "protected_files_in_deleted_tree" in codes(result)
    history.write_text("broken")
    result = dataset.run()
    assert not result["history"]["complete"] and "history_unreadable" in codes(result)


def test_cli_has_no_apply_or_delete_entrypoint():
    with pytest.raises(SystemExit) as exc:
        migration.main(["--apply"])
    assert exc.value.code == 2


def test_unknown_history_table_is_not_silently_discarded(dataset):
    dataset.execute("CREATE TABLE guard_room_alarm_history (id INTEGER)")
    result = dataset.run()
    assert "unclassified_old_table" in codes(result)
    assert "guard_room_alarm_history" not in result["storage"]["deletion_plan"]["after_verify_tables"]


def test_missing_sqlite_source_is_not_created(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError), migration.read_only_connection(f"sqlite:///{missing}"):
        pytest.fail("missing source must not open")
    assert not missing.exists()


def test_no_global_cutover_or_old_runtime_import():
    from AiVision.features.registry import all_specs
    from AiVision.alarms.types import VIOLATION_TYPE_META
    assert "guard_behavior" not in all_specs()
    assert set(VIOLATION_TYPE_META) == set(range(1, 8))
    source = Path(migration.__file__).read_text()
    assert "from AiVision.integrations.guard_room" not in source
    assert "import AiVision.integrations.guard_room" not in source
