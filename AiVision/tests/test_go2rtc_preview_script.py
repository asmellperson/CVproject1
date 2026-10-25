"""预览侧车只管理自己的会话，并把可能含凭据的配置保留在私有运行目录。"""
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest
import yaml


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "go2rtc_preview.sh"
TEMPLATE = SCRIPT.with_name("go2rtc.preview.yaml")

MOCK_COMMANDS = r'''
source "$SCRIPT"
tmux() {
  printf '%s\n' "$*" >> "$CASE_DIR/tmux.calls"
  case "$1" in
    has-session) [[ "$SESSION_EXISTS" == 1 ]] ;;
    show-option)
      case "${@: -1}" in
        @fuda_go2rtc_root) printf '%s\n' "${OWNER_ROOT:-$GO2RTC_PREVIEW_ROOT}" ;;
        @fuda_go2rtc_binary) printf '%s\n' "$BINARY" ;;
      esac ;;
    list-panes) printf '%s:4321\n' "${PANE_SESSION_NAME:-fuda_go2rtc_preview}" ;;
    new-session)
      SESSION_EXISTS=1
      LISTENER='LISTEN 0 128 127.0.0.1:1984 0.0.0.0:* users:(("go2rtc",pid=4321,fd=3))'
      printf '%s' "${@: -1}" > "$CASE_DIR/start.command" ;;
    kill-session) touch "$CASE_DIR/session.closed"; SESSION_EXISTS=0 ;;
    set-option) return 0 ;;
  esac
}
ss() {
  [[ "$SS_FAILURE" == 0 ]] || return 1
  if [[ "${SS_SILENT_FAILURE:-0}" == 1 ]]; then
    echo 'Cannot open netlink socket: Operation not permitted' >&2
    return 0
  fi
  printf '%s' "$LISTENER"
}
curl() { [[ "$HEALTHY" == 1 ]]; }
go2rtc_preview_pid_matches() { [[ "$PROCESS_RUNNING" == 1 ]]; }
kill() {
  printf '%s\n' "$*" >> "$CASE_DIR/signals"
  if [[ "$STOP_COMPLETES" == 1 ]]; then PROCESS_RUNNING=0; LISTENER=''; fi
}
go2rtc_preview_main "$ACTION"
'''


@pytest.fixture
def script_environment(tmp_path):
    binary = tmp_path / "go2rtc binary"
    binary.write_text("#!/usr/bin/env bash\nexit 0\n")
    binary.chmod(0o700)
    return {
        **os.environ, "SCRIPT": str(SCRIPT), "CASE_DIR": str(tmp_path),
        "FUDA_CVP_ROOT": str(tmp_path), "GO2RTC_BIN": str(binary), "BINARY": str(binary),
        "SESSION_EXISTS": "0", "LISTENER": "", "SS_FAILURE": "0", "HEALTHY": "1",
        "PROCESS_RUNNING": "1", "STOP_COMPLETES": "1", "GO2RTC_PREVIEW_WAIT_SECONDS": "1",
    }


def run_script(environment, action):
    return subprocess.run(
        ["bash", "-c", MOCK_COMMANDS], env={**environment, "ACTION": action},
        capture_output=True, text=True, timeout=5,
    )


def test_template_disables_public_media_listeners_and_contains_no_sources():
    config = yaml.safe_load(TEMPLATE.read_text())
    assert config["api"]["listen"] == "127.0.0.1:1984"
    assert config["rtsp"]["listen"] == config["webrtc"]["listen"] == ""
    assert config["webrtc"]["ice_servers"] == []
    assert "streams" not in config


@pytest.mark.parametrize("action", ["start", "stop", "status"])
def test_unknown_listener_is_preserved(script_environment, action):
    script_environment["LISTENER"] = 'LISTEN 0 128 127.0.0.1:1984 0.0.0.0:* users:(("unknown",pid=999,fd=3))'
    result = run_script(script_environment, action)
    assert result.returncode == 1, result.stdout + result.stderr
    root = Path(script_environment["CASE_DIR"])
    assert not (root / "signals").exists()
    assert not (root / "session.closed").exists()
    assert not (root / "runtime").exists()


@pytest.mark.parametrize("action", ["start", "stop", "status"])
def test_foreign_tmux_session_is_preserved(script_environment, action):
    script_environment.update(SESSION_EXISTS="1", OWNER_ROOT="/other/deployment")
    result = run_script(script_environment, action)
    assert result.returncode == 1, result.stdout + result.stderr
    root = Path(script_environment["CASE_DIR"])
    assert not (root / "signals").exists()
    assert not (root / "session.closed").exists()
    assert not (root / "start.command").exists()


@pytest.mark.parametrize("action", ["start", "stop", "status"])
def test_port_inspection_failure_is_not_reported_as_success(script_environment, action):
    script_environment["SS_FAILURE"] = "1"
    result = run_script(script_environment, action)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "无法核对" in result.stderr
    assert not (Path(script_environment["CASE_DIR"]) / "signals").exists()


@pytest.mark.parametrize("action", ["start", "stop", "status"])
def test_ss_permission_error_with_zero_exit_status_is_not_treated_as_free_port(script_environment, action):
    script_environment["SS_SILENT_FAILURE"] = "1"
    result = run_script(script_environment, action)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "无法核对" in result.stderr
    assert not (Path(script_environment["CASE_DIR"]) / "signals").exists()


@pytest.mark.parametrize("action", ["start", "stop", "status"])
def test_tmux_prefix_match_is_not_treated_as_the_exact_managed_session(script_environment, action):
    script_environment.update(SESSION_EXISTS="1", PANE_SESSION_NAME="fuda_go2rtc_preview_other")
    result = run_script(script_environment, action)
    assert result.returncode == 1, result.stdout + result.stderr
    root = Path(script_environment["CASE_DIR"])
    assert not (root / "signals").exists()
    assert not (root / "session.closed").exists()


def test_missing_binary_prints_official_install_hint_without_installing(script_environment):
    script_environment["GO2RTC_BIN"] = "/missing/go2rtc"
    result = run_script(script_environment, "start")
    assert result.returncode == 1
    assert "https://github.com/AlexxIT/go2rtc/releases" in result.stderr
    assert "GO2RTC_BIN" in result.stderr
    assert not (Path(script_environment["CASE_DIR"]) / "runtime").exists()


def test_start_uses_private_config_copy_and_does_not_touch_template(script_environment):
    original = TEMPLATE.read_bytes()
    result = run_script(script_environment, "start")
    assert result.returncode == 0, result.stdout + result.stderr
    root = Path(script_environment["CASE_DIR"])
    runtime = root / "runtime" / "go2rtc"
    config = runtime / TEMPLATE.name
    log = runtime / "go2rtc.log"
    assert config.read_bytes() == original == TEMPLATE.read_bytes()
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    assert stat.S_IMODE(config.stat().st_mode) == stat.S_IMODE(log.stat().st_mode) == 0o600
    command = (root / "start.command").read_text()
    assert str(config) in command
    assert str(TEMPLATE) not in command
    assert "go2rtc.log" in command


def test_start_rejects_a_private_config_symlink_to_the_tracked_template(script_environment):
    runtime = Path(script_environment["CASE_DIR"]) / "runtime" / "go2rtc"
    runtime.mkdir(parents=True)
    (runtime / TEMPLATE.name).symlink_to(TEMPLATE)
    original = TEMPLATE.read_bytes()
    result = run_script(script_environment, "start")
    assert result.returncode == 1
    assert "符号链接" in result.stderr
    assert TEMPLATE.read_bytes() == original
    assert not (Path(script_environment["CASE_DIR"]) / "start.command").exists()


def test_running_start_checks_health_without_overwriting_registered_sources(script_environment):
    root = Path(script_environment["CASE_DIR"])
    runtime = root / "runtime" / "go2rtc"
    runtime.mkdir(parents=True)
    private_config = runtime / TEMPLATE.name
    private_config.write_text("streams:\n  private: rtsp://private-user:private-password@camera.invalid/live\n")
    script_environment.update(
        SESSION_EXISTS="1",
        LISTENER='LISTEN 0 128 127.0.0.1:1984 0.0.0.0:* users:(("go2rtc",pid=4321,fd=3))',
    )
    result = run_script(script_environment, "start")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "private-password" in private_config.read_text()
    assert "private-password" not in result.stdout + result.stderr
    assert not (root / "start.command").exists()


@pytest.mark.parametrize("listener, healthy", [
    ('LISTEN 0 128 0.0.0.0:1984 0.0.0.0:* users:(("go2rtc",pid=4321,fd=3))', "1"),
    ('LISTEN 0 128 127.0.0.1:1984 0.0.0.0:* users:(("unknown",pid=999,fd=3))', "1"),
    ('LISTEN 0 128 127.0.0.1:1984 0.0.0.0:* users:(("go2rtc",pid=4321,fd=3))', "0"),
])
def test_status_requires_private_listener_pid_and_http_health(script_environment, listener, healthy):
    script_environment.update(SESSION_EXISTS="1", LISTENER=listener, HEALTHY=healthy)
    result = run_script(script_environment, "status")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "运行正常" not in result.stdout


@pytest.mark.parametrize("completes", [True, False])
def test_stop_waits_for_process_exit_and_port_release_without_forcing(script_environment, completes):
    script_environment.update(
        SESSION_EXISTS="1", STOP_COMPLETES="1" if completes else "0",
        LISTENER='LISTEN 0 128 127.0.0.1:1984 0.0.0.0:* users:(("go2rtc",pid=4321,fd=3))',
    )
    result = run_script(script_environment, "stop")
    assert result.returncode == (0 if completes else 1), result.stdout + result.stderr
    root = Path(script_environment["CASE_DIR"])
    assert (root / "signals").read_text().splitlines() == ["-TERM 4321"]
    assert (root / "session.closed").exists() is completes
    if not completes:
        assert "不强制" in result.stderr


def test_status_reports_stopped_without_a_session_or_listener(script_environment):
    result = run_script(script_environment, "status")
    assert result.returncode == 3
    assert "未运行" in result.stdout


def test_process_identity_requires_program_and_exact_private_config(tmp_path):
    binary = tmp_path / "go2rtc-wrapper"
    binary.write_text("import time\ntime.sleep(10)\n")
    config = tmp_path / "runtime" / "go2rtc" / TEMPLATE.name
    process = subprocess.Popen([sys.executable, str(binary), "-c", str(config)])
    try:
        command = 'source "$SCRIPT"; go2rtc_preview_pid_matches "$PREVIEW_PID" "$BINARY"'
        environment = {
            **os.environ, "SCRIPT": str(SCRIPT), "FUDA_CVP_ROOT": str(tmp_path),
            "PREVIEW_PID": str(process.pid), "BINARY": str(binary),
        }
        matched = subprocess.run(["bash", "-c", command], env=environment, capture_output=True, timeout=3)
        assert matched.returncode == 0
        for overrides in ({"BINARY": "/other/go2rtc"}, {"FUDA_CVP_ROOT": str(tmp_path.parent)}):
            rejected = subprocess.run(
                ["bash", "-c", command], env={**environment, **overrides}, capture_output=True, timeout=3,
            )
            assert rejected.returncode == 1
    finally:
        process.terminate()
        process.wait(timeout=3)
