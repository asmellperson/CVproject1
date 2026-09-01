import importlib
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

from unified_backend import run_server


def test_load_env_file_uses_backend_env_without_overriding_system_values(
    monkeypatch,
    tmp_path,
):
    expected_env_file = Path(run_server.__file__).resolve().parent / ".env"
    assert run_server._ENV_FILE == expected_env_file

    env_file = tmp_path / ".env"
    env_file.write_text(
        "UNIFIED_ENV_PRIORITY=from-file\nUNIFIED_ENV_FILE_ONLY=loaded\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_server, "_ENV_FILE", env_file)
    monkeypatch.setenv("UNIFIED_ENV_PRIORITY", "from-system")
    monkeypatch.delenv("UNIFIED_ENV_FILE_ONLY", raising=False)

    run_server._load_env_file()

    assert os.environ["UNIFIED_ENV_PRIORITY"] == "from-system"
    assert os.environ["UNIFIED_ENV_FILE_ONLY"] == "loaded"


def test_main_loads_env_before_importing_app_and_keeps_cli_priority(monkeypatch):
    events = []

    class RecordingAppModule(ModuleType):
        def __getattribute__(self, name):
            if name == "create_app":
                events.append("import_app")
            return super().__getattribute__(name)

    app = object()
    app_module = RecordingAppModule("unified_backend.app")
    app_module.create_app = lambda: events.append("create_app") or app
    uvicorn_run = Mock()

    monkeypatch.setattr(run_server, "_load_env_file", lambda: events.append("load_env"))
    monkeypatch.setattr(run_server.uvicorn, "run", uvicorn_run)
    monkeypatch.setitem(sys.modules, "unified_backend.app", app_module)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_server.py", "--host", "127.0.0.2", "--port", "6001"],
    )
    monkeypatch.delenv("UNIFIED_BACKEND_PORT", raising=False)

    run_server.main()

    assert events == ["load_env", "import_app", "create_app"]
    assert os.environ["UNIFIED_BACKEND_PORT"] == "6001"
    uvicorn_run.assert_called_once_with(
        app,
        host="127.0.0.2",
        port=6001,
        access_log=False,
    )


def test_app_import_uses_status_worker_count_loaded_from_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("UNIFIED_STATUS_MAX_WORKERS=3\n", encoding="utf-8")
    monkeypatch.setattr(run_server, "_ENV_FILE", env_file)
    monkeypatch.delenv("UNIFIED_STATUS_MAX_WORKERS", raising=False)
    monkeypatch.delitem(sys.modules, "unified_backend.app", raising=False)

    run_server._load_env_file()
    app_module = importlib.import_module("unified_backend.app")

    try:
        assert app_module._platform_status_max_workers() == 3
        assert app_module._PLATFORM_STATUS_EXECUTOR._max_workers == 3
    finally:
        app_module._PLATFORM_STATUS_EXECUTOR.shutdown(wait=True)
