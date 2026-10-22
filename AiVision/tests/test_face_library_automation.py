"""海康自动更新入口、旧 systemd 配置升级及失败可见性的回归验证。"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from AiVision import face_library
from AiVision.features.face_recognition.library import automation


@pytest.mark.parametrize("sync_result, embedding_result", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_update_runs_both_stages_and_reports_any_failure(monkeypatch, sync_result, embedding_result):
    calls = []

    def load_module(name):
        result = sync_result if name == face_library.STAGE_MODULES[0][1] else embedding_result

        def run():
            calls.append(name)
            return result

        return SimpleNamespace(main=run)

    monkeypatch.setattr(face_library.importlib, "import_module", load_module)
    assert face_library.update_library() == int(bool(sync_result or embedding_result))
    assert calls == [name for _, name in face_library.STAGE_MODULES]


def test_unexpected_source_failure_does_not_suppress_other_stage_or_expose_parameters(monkeypatch, capsys):
    calls = []

    def load_module(name):
        def run():
            calls.append(name)
            if name == face_library.STAGE_MODULES[0][1]:
                raise RuntimeError("sensitive-database-parameters")
            return 0

        return SimpleNamespace(main=run)

    monkeypatch.setattr(face_library.importlib, "import_module", load_module)
    assert face_library.update_library() == 1
    assert len(calls) == 2
    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert "sensitive-database-parameters" not in output
    assert "全部完成" not in output


def test_installed_entrypoint_can_check_real_modules_without_loading_deployment_configuration():
    # 在全新进程中检查真实入口，防止测试替身掩盖下次功能包改名引入的断链。
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("MYSQL_", "HIKVISION_")) and key != "DATA_PATH"}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([
        sys.executable, "-c",
        "import sys; from AiVision.face_library import main; "
        "assert main(['--check']) == 0; "
        "assert 'AiVision.core.db' not in sys.modules; "
        "assert 'AiVision.core.settings' not in sys.modules; "
        "assert 'insightface' not in sys.modules",
    ], cwd=face_library.PROJECT_ROOT, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def systemd(monkeypatch, tmp_path):
    unit_directory = tmp_path / "units"
    unit_directory.mkdir()
    project_root = tmp_path / "deployed project"
    project_root.mkdir()
    calls = []
    service = {
        "LoadState": "loaded", "WorkingDirectory": str(project_root),
        "ExecStart": "{ argv[]=python -m AiVision.face_library ; }",
        "ActiveState": "inactive", "Result": "success", "ExecMainStatus": "0",
        "ExecMainStartTimestamp": "Thu 2026-10-22 12:56:00 CST",
        "ExecMainExitTimestamp": "Thu 2026-10-22 12:57:00 CST",
    }
    timer = {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled",
             "LastTriggerUSec": "Thu 2026-10-22 12:56:00 CST"}

    def run(*args):
        calls.append(args)
        if args[0] == "show":
            properties = service if args[1] == automation.SERVICE_NAME else timer
            return "\n".join(f"{name}={value}" for name, value in properties.items())
        return ""

    monkeypatch.setattr(automation, "UNIT_DIRECTORY", unit_directory)
    monkeypatch.setattr(automation, "_systemctl", run)
    monkeypatch.setattr(automation.os, "geteuid", lambda: 0)
    return SimpleNamespace(directory=unit_directory, root=project_root, calls=calls, service=service, timer=timer)


def test_install_replaces_legacy_module_backs_up_config_and_is_repeatable(systemd):
    service_path = systemd.directory / automation.SERVICE_NAME
    legacy = "[Service]\nExecStart=python -m AiVision.platform.face_library.sync\n"
    service_path.write_text(legacy, encoding="utf-8")
    assert automation.install_systemd(systemd.root) == 0
    installed = service_path.read_text(encoding="utf-8")
    assert "-m AiVision.face_library\n" in installed
    assert "AiVision.platform" not in installed
    assert f"WorkingDirectory={systemd.root}" in installed
    assert service_path.with_name(f"{service_path.name}.bak").read_text(encoding="utf-8") == legacy
    assert systemd.calls.index(("daemon-reload",)) < systemd.calls.index(("enable", "--now", automation.TIMER_NAME))
    assert ("start", "--no-block", automation.SERVICE_NAME) in systemd.calls
    modified_at = service_path.stat().st_mtime_ns
    assert automation.install_systemd(systemd.root) == 0
    assert service_path.stat().st_mtime_ns == modified_at
    assert service_path.with_name(f"{service_path.name}.bak").read_text(encoding="utf-8") == legacy


def test_install_refuses_to_claim_success_when_a_drop_in_keeps_the_old_module(systemd, capsys):
    systemd.service["ExecStart"] = "{ argv[]=python -m AiVision.platform.face_library.sync ; }"
    assert automation.install_systemd(systemd.root) == 1
    assert ("enable", "--now", automation.TIMER_NAME) not in systemd.calls
    assert "drop-in" in capsys.readouterr().out


def test_dry_run_does_not_modify_units_or_start_services(systemd, monkeypatch):
    monkeypatch.setattr(automation.os, "geteuid", lambda: 1000)
    assert automation.install_systemd(systemd.root, dry_run=True) == 0
    assert list(systemd.directory.iterdir()) == []
    assert systemd.calls == []


def test_install_without_root_stops_before_changing_any_unit(systemd, monkeypatch):
    monkeypatch.setattr(automation.os, "geteuid", lambda: 1000)
    assert automation.install_systemd(systemd.root) == 1
    assert list(systemd.directory.iterdir()) == []
    assert systemd.calls == []


def test_invalid_generated_configuration_cannot_overwrite_installed_units(systemd, monkeypatch):
    service_path = systemd.directory / automation.SERVICE_NAME
    service_path.write_text("existing service", encoding="utf-8")

    def reject(units):
        raise subprocess.CalledProcessError(1, ["systemd-analyze", "verify"])

    monkeypatch.setattr(automation, "_verify_units", reject)
    with pytest.raises(subprocess.CalledProcessError):
        automation.install_systemd(systemd.root)
    assert service_path.read_text(encoding="utf-8") == "existing service"
    assert systemd.calls == []


def test_broken_business_entrypoint_prevents_install(monkeypatch, systemd):
    monkeypatch.setattr(face_library, "STAGE_MODULES", (("人员资料同步", "AiVision.missing_sync_module"),))
    assert face_library.main(["--install-systemd"]) == 1
    assert list(systemd.directory.iterdir()) == []
    assert systemd.calls == []


def test_active_timer_does_not_hide_the_actual_service_failure(systemd, capsys):
    systemd.service.update(Result="exit-code", ExecMainStatus="1", ActiveState="failed")
    assert automation.show_status(systemd.root) == 1
    output = capsys.readouterr().out
    assert "定时器：已启用" in output
    assert "最近更新存在失败" in output
    assert "均已完成" not in output


@pytest.mark.parametrize("entry", [
    "python -m AiVision.platform.face_library.sync",
    "python -m AiVision.face_library_old",
    "python -m AiVision.face_library --check",
])
def test_status_detects_an_outdated_or_similarly_named_entrypoint(systemd, entry):
    systemd.service["ExecStart"] = f"{{ argv[]={entry} ; }}"
    assert automation.show_status(systemd.root) == 1


def test_status_requires_enabled_timer_and_a_completed_run(systemd):
    systemd.timer["UnitFileState"] = "disabled"
    assert automation.show_status(systemd.root) == 1
    systemd.timer["UnitFileState"] = "enabled"
    systemd.service["ExecMainExitTimestamp"] = ""
    assert automation.show_status(systemd.root) == 1


def test_running_update_is_distinguished_from_a_failed_or_completed_one(systemd, capsys):
    systemd.service.update(ActiveState="activating", ExecMainExitTimestamp="")
    assert automation.show_status(systemd.root) == 0
    assert "正在执行" in capsys.readouterr().out


def test_status_accepts_an_inactive_successful_oneshot(systemd):
    assert automation.show_status(systemd.root) == 0


def test_renderer_escapes_paths_and_reschedules_after_completion():
    units = automation.render_units(Path('/srv/project with % and $'), Path('/venv with $ and %/bin/python'))
    assert 'WorkingDirectory=/srv/project with %% and $' in units[automation.SERVICE_NAME]
    assert 'ExecStart="/venv with $$ and %%/bin/python" -m AiVision.face_library' in units[automation.SERVICE_NAME]
    assert "Type=oneshot" in units[automation.SERVICE_NAME]
    assert "OnUnitInactiveSec=10min" in units[automation.TIMER_NAME]
    assert "OnUnitActiveSec=" not in units[automation.TIMER_NAME]


def test_generated_units_are_accepted_by_systemd_with_a_space_in_the_project_path(tmp_path):
    verifier = shutil.which("systemd-analyze")
    if verifier is None:
        pytest.skip("本机没有 systemd 原生校验工具")
    project_root = tmp_path / "deployed project"
    project_root.mkdir()
    paths = []
    for name, content in automation.render_units(project_root, Path(sys.executable)).items():
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        paths.append(str(path))
    result = subprocess.run([verifier, "verify", "--man=no", *paths], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_systemctl_errors_are_propagated_with_operation_and_exit_code(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="Failed to connect to bus")

    # 这一项使用真实包装函数，确保进程错误不会被安装流程当作成功。
    monkeypatch.setattr(automation.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        automation._systemctl("daemon-reload")
    assert "daemon-reload 失败，退出码 1" in capsys.readouterr().out
