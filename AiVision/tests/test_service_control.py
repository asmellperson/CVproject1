"""运维脚本只通知当前会话主进程，并等正常退出后再关闭会话。"""
import os
from pathlib import Path
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
