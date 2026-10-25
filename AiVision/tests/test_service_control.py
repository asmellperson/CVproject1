"""运维脚本只通知当前会话主进程，并等正常退出后再关闭会话。"""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

import pytest


CONTROL = Path(__file__).resolve().parents[2] / "scripts" / "service_control.sh"


def test_find_main_process_in_tmux_descendants_excludes_workers_and_other_deployments():
    result = subprocess.run(["bash", "-c", '''
source "$CONTROL"
tmux() { echo 100; }
ps() {
  cat <<'PROCESSES'
100 1 bash /bin/bash
101 100 bash /bin/bash
102 101 python /env/bin/python -m AiVision.main
103 102 python /env/bin/python -c multiprocessing.spawn
200 1 python /other/bin/python -m AiVision.main
201 100 bash /bin/bash -c python -m AiVision.main
PROCESSES
}
fuda_find_aivision_pids aivision
'''], env={**os.environ, "CONTROL": str(CONTROL)}, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "102"


@pytest.mark.parametrize("finish", [True, False])
def test_stop_waits_before_closing_tmux_and_keeps_session_on_timeout(tmp_path, finish):
    env = {**os.environ, "CONTROL": str(CONTROL), "CASE_DIR": str(tmp_path),
           "FUDA_STOP_TIMEOUT_SECONDS": "1" if not finish else "5"}
    script = '''
source "$CONTROL"
tmux() {
  case "$1" in
    show-option) cat "$CASE_DIR/signalled" 2>/dev/null ;;
    set-option) printf '%s' "$5" > "$CASE_DIR/signalled" ;;
    has-session) return 0 ;;
    kill-session) touch "$CASE_DIR/killed" ;;
  esac
}
fuda_find_aivision_pids() { echo 777; }
fuda_aivision_pid_running() { [[ ! -e "$CASE_DIR/finished" ]]; }
kill() { echo TERM >> "$CASE_DIR/signals"; touch "$CASE_DIR/draining"; }
fuda_stop_session aivision
'''
    process = subprocess.Popen(["bash", "-c", script], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 3
        while not (tmp_path / "draining").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert (tmp_path / "draining").exists()
        assert not (tmp_path / "killed").exists()
        assert process.poll() is None
        if finish:
            (tmp_path / "finished").touch()
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == (0 if finish else 1), stdout + stderr
        assert (tmp_path / "killed").exists() is finish
        if not finish:
            assert "保留会话" in stdout
            # 重试停止命令不能再次发信号打断正在进行的资源清理。
            retried = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=5)
            assert retried.returncode == 1
        assert (tmp_path / "signals").read_text().splitlines() == ["TERM"]
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=3)


def test_stop_sends_real_sigterm_and_waits_for_main_process_to_exit(tmp_path):
    """用隔离的 Python 主入口验证真实 PID 识别、信号及退出等待。"""
    package = tmp_path / "AiVision"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "main.py").write_text('''
import os
from pathlib import Path
import signal
import time

root = Path(os.environ["CASE_DIR"])
signal.signal(signal.SIGTERM, lambda *args: (root / "draining").touch())
(root / "ready").touch()
while not (root / "draining").exists() or not (root / "finished").exists():
    time.sleep(.01)
''')
    import sys

    env = {**os.environ, "PYTHONPATH": str(tmp_path), "CASE_DIR": str(tmp_path),
           "CONTROL": str(CONTROL), "FUDA_STOP_TIMEOUT_SECONDS": "5"}
    main = subprocess.Popen([sys.executable, "-m", "AiVision.main"], cwd=tmp_path, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stopper = None
    try:
        deadline = time.monotonic() + 3
        while not (tmp_path / "ready").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert (tmp_path / "ready").exists()
        stopper = subprocess.Popen(["bash", "-c", '''
source "$CONTROL"
tmux() {
  case "$1" in
    list-panes) echo "$PANE_PID" ;;
    show-option|set-option|has-session) return 0 ;;
    kill-session) touch "$CASE_DIR/killed" ;;
  esac
}
fuda_stop_session aivision
'''], env={**env, "PANE_PID": str(main.pid)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 3
        while not (tmp_path / "draining").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert (tmp_path / "draining").exists()
        assert main.poll() is None
        assert stopper.poll() is None
        assert not (tmp_path / "killed").exists()
        (tmp_path / "finished").touch()
        assert main.wait(timeout=3) == 0
        stdout, stderr = stopper.communicate(timeout=3)
        assert stopper.returncode == 0, stdout + stderr
        assert (tmp_path / "killed").exists()
    finally:
        for process in (stopper, main):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=3)


FRONTEND_STOP_SCRIPT = '''
source "$CONTROL"
tmux() {
  case "$1" in
    has-session) return 0 ;;
    kill-session) touch "$CASE_DIR/session_closed" ;;
  esac
}
ss() {
  printf '%s\\n' "$*" >> "$CASE_DIR/ss_args"
  touch "$CASE_DIR/port_checked"
  if [[ "$SS_FAILURE" == "1" ]]; then
    echo 'ss unavailable' >&2
    return 23
  fi
  if [[ ! -e "$CASE_DIR/port_released" ]]; then
    echo "LISTEN 0 511 0.0.0.0:${TEST_PORT:-3000} 0.0.0.0:*"
  fi
}
# 停止会话只等待端口释放，不能向身份不明的监听进程发信号。
kill() { printf '%s\\n' "$*" >> "$CASE_DIR/signals"; return 1; }
if [[ -n "$TEST_PORT" ]]; then
  fuda_stop_session unified_frontend "$TEST_PORT"
else
  fuda_stop_session unified_frontend
fi
'''


@pytest.mark.parametrize("port", [None, "4300"])
def test_frontend_stop_waits_for_listener_release_after_tmux_closes(tmp_path, port):
    env = {**os.environ, "CONTROL": str(CONTROL), "CASE_DIR": str(tmp_path),
           "FUDA_STOP_TIMEOUT_SECONDS": "5", "TEST_PORT": port or "", "SS_FAILURE": "0"}
    process = subprocess.Popen(["bash", "-c", FRONTEND_STOP_SCRIPT], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 3
        while not (tmp_path / "port_checked").exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                break
            time.sleep(.01)
        assert (tmp_path / "session_closed").exists()
        assert (tmp_path / "port_checked").exists(), "关闭 tmux 后必须检查监听端口"
        assert process.poll() is None, "旧前端仍在释放端口时，停止操作不能提前成功"
        assert not (tmp_path / "signals").exists()
        (tmp_path / "port_released").touch()
        stdout, stderr = process.communicate(timeout=3)
        assert process.returncode == 0, stdout + stderr
        queries = (tmp_path / "ss_args").read_text().splitlines()
        assert len(queries) >= 2
        assert all(f"sport = :{port or '3000'}" in query for query in queries)
        assert not (tmp_path / "signals").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=3)


def test_frontend_stop_reports_timeout_without_killing_listener(tmp_path):
    env = {**os.environ, "CONTROL": str(CONTROL), "CASE_DIR": str(tmp_path),
           "FUDA_STOP_TIMEOUT_SECONDS": "1", "TEST_PORT": "", "SS_FAILURE": "0"}
    result = subprocess.run(["bash", "-c", FRONTEND_STOP_SCRIPT], env=env,
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0, result.stdout + result.stderr
    assert (tmp_path / "session_closed").exists()
    assert (tmp_path / "port_checked").exists()
    assert "3000" in result.stdout + result.stderr
    assert not (tmp_path / "signals").exists()


def test_frontend_stop_does_not_treat_failed_listener_query_as_released_port(tmp_path):
    env = {**os.environ, "CONTROL": str(CONTROL), "CASE_DIR": str(tmp_path),
           "FUDA_STOP_TIMEOUT_SECONDS": "1", "TEST_PORT": "", "SS_FAILURE": "1"}
    result = subprocess.run(["bash", "-c", FRONTEND_STOP_SCRIPT], env=env,
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0, result.stdout + result.stderr
    assert (tmp_path / "session_closed").exists()
    assert (tmp_path / "port_checked").exists()
    assert not (tmp_path / "signals").exists()


@pytest.mark.skipif(shutil.which("ss") is None, reason="需要 ss 查询实际 TCP 监听端口")
def test_frontend_stop_waits_for_real_tcp_listener_release(tmp_path):
    """真实监听验证 ss 的端口过滤语法，避免模拟输出掩盖查询错误。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        env = {**os.environ, "CONTROL": str(CONTROL), "CASE_DIR": str(tmp_path),
               "FUDA_STOP_TIMEOUT_SECONDS": "5", "TEST_PORT": str(port)}
        process = subprocess.Popen(["bash", "-c", '''
source "$CONTROL"
tmux() {
  case "$1" in
    has-session) return 0 ;;
    kill-session) touch "$CASE_DIR/session_closed" ;;
  esac
}
ss() {
  command ss "$@"
  local status="$?"
  touch "$CASE_DIR/port_checked"
  return "$status"
}
kill() { printf '%s\\n' "$*" >> "$CASE_DIR/signals"; return 1; }
fuda_stop_session unified_frontend "$TEST_PORT"
'''], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 3
            while not (tmp_path / "port_checked").exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(.01)
            assert (tmp_path / "session_closed").exists()
            assert (tmp_path / "port_checked").exists()
            with pytest.raises(subprocess.TimeoutExpired):
                process.communicate(timeout=.2)
            listener.close()
            stdout, stderr = process.communicate(timeout=3)
            assert process.returncode == 0, stdout + stderr
            assert not (tmp_path / "signals").exists()
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)
