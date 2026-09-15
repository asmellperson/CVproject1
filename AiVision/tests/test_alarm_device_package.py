"""报警设备新包的独立导入、无外部副作用和单一 ORM/运行实例验证。"""
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def isolated_environment(tmp_path):
    env = os.environ.copy()
    for name in ("CONFIG_TEST_MYSQL_URL", "LOGISTICS_TEST_MYSQL_URL", "HUMAN_TEST_MYSQL_URL"):
        env.pop(name, None)
    env.update(
        PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1",
        MYSQL_DB_URL="127.0.0.1", MYSQL_DB_PORT="1", MYSQL_DB_USER="alarm_device_package_test",
        MYSQL_DB_PASSWORD="test-only-unused", MYSQL_DB_NAME="alarm_device_package_test",
        AUTO_CREATE_DB="false", DATA_PATH=str(tmp_path / "media"),
        AUTH_USERS_DB=str(tmp_path / "auth.sqlite"),
        UNIFIED_BACKEND_DATA_DIR=str(tmp_path / "backend"),
    )
    return env


@pytest.mark.parametrize("entry", [
    "AiVision.alarms", "AiVision.alarms.devices", "AiVision.alarms.devices.orm",
    "AiVision.alarms.devices.service", "AiVision.alarms.devices.runtime_manager",
    "AiVision.api.routes.horns", "AiVision.features", "AiVision.core.db", "AiVision.runtime.orchestrator",
])
def test_fresh_imports_are_inert_and_share_device_registration(entry, tmp_path):
    program = textwrap.dedent("""
        from contextlib import ExitStack
        import importlib
        import importlib.util
        from pathlib import Path
        import sys
        from unittest.mock import patch

        attempts = []
        def forbid(name):
            def called(*args, **kwargs):
                attempts.append(name)
                raise AssertionError("unexpected import side effect: " + name)
            return called

        with ExitStack() as stack:
            for target in (
                "sqlalchemy.create_engine", "sqlalchemy.engine.Engine.connect",
                "sqlite3.connect", "pymysql.connect",
                "requests.sessions.Session.request", "socket.create_connection",
                "socket.socket.connect", "socket.socket.connect_ex",
                "threading.Thread.start", "multiprocessing.process.BaseProcess.start", "subprocess.Popen",
            ):
                stack.enter_context(patch(target, side_effect=forbid(target)))

            entry = sys.argv[1]
            importlib.import_module(entry)
            # 父包和设备包本身都只作职责说明，不提前导入实现或应用依赖。
            if entry in ("AiVision.alarms", "AiVision.alarms.devices"):
                expected = {"AiVision", "AiVision.alarms"}
                if entry == "AiVision.alarms.devices":
                    expected.add("AiVision.alarms.devices")
                assert {name for name in sys.modules if name == "AiVision" or name.startswith("AiVision.")} == expected

            import AiVision.alarms as alarms
            import AiVision.alarms.devices as devices
            from AiVision.alarms.devices import binding, orm, runtime_manager, schema, service
            from AiVision.api import deps
            from AiVision.api.routes import horns
            from AiVision.core import db, system_config
            from AiVision.features.registry import all_specs
            from AiVision.runtime import orchestrator
            from AiVision.alarms.records import orm as violation_orm
            from sqlalchemy.orm import configure_mappers

            root = Path(sys.argv[2]) / "AiVision"
            assert Path(alarms.__file__).parent == root / "alarms"
            assert Path(devices.__file__).parent == root / "alarms/devices"
            for module in (binding, orm, runtime_manager, schema, service):
                assert Path(module.__file__).parent == root / "alarms/devices"
            assert binding.AiHornConfig is service.AiHornConfig is orm.AiHornConfig
            assert orm.AiHornConfig.__module__ == "AiVision.alarms.devices.orm"
            assert orm.AiHornConfig.__tablename__ == "ai_horn_config"
            assert db.Base.metadata.tables["ai_horn_config"] is orm.AiHornConfig.__table__
            assert set(orm.AiHornConfig.__table__.columns.keys()) == {
                "id", "name", "url", "username", "password", "enable", "description", "created_at", "updated_at",
            }
            configure_mappers()
            assert [mapper.class_ for mapper in db.Base.registry.mappers
                    if mapper.local_table.name == "ai_horn_config"] == [orm.AiHornConfig]
            # 解析所有外键，验证绑定仍指向同一张表；不建表也不查询。
            for table in db.Base.metadata.sorted_tables:
                for key in table.foreign_keys:
                    if key.column.table.name == "ai_horn_config":
                        assert key.column.table is orm.AiHornConfig.__table__
            assert set(all_specs()) == {
                "blocks", "detect_door", "detect_face", "detect_human",
                "detect_logistics_single_person", "detect_phone", "recognize_face",
            }
            assert deps.get_horn_service() is service.horn_service
            runtime = runtime_manager.horn_runtime_manager
            assert deps.get_horn_runtime_manager() is orchestrator.horn_runtime_manager is runtime
            assert horns.HornCreate is schema.HornCreate
            assert horns.HornInUseError is service.HornInUseError
            assert not runtime._active and runtime._threads == [] and runtime._entries == {}
            assert db._engine is None and db._session_factory is None
            # Check removed layout and loaded package hierarchy without resolving a retired import path.
            aivision_root = Path(importlib.util.find_spec("AiVision").origin).parent
            assert not (aivision_root / "platform").exists()
            assert not (aivision_root / "platform.py").exists()
            assert "platform" not in {name.split(".")[1] for name in sys.modules if name.startswith("AiVision.")}
            # 即使导入代码捕获了异常，也不能掩盖尝试过外部访问或启动任务。
            assert attempts == [], attempts
            print("registered without side effects")
    """)
    result = subprocess.run([sys.executable, "-c", program, entry, str(REPO_ROOT)],
                            cwd=tmp_path, env=isolated_environment(tmp_path),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "registered without side effects"
    assert "加载 features." not in result.stderr
    assert not (tmp_path / "auth.sqlite").exists()
