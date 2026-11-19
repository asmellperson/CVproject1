"""关停回归：使用临时媒体、模拟采集进程和 shell 命令，不连接现场设备或数据库。"""
import datetime
import os
from pathlib import Path
from queue import Queue
import subprocess
from threading import Barrier, Event, Lock, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def modules(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "shutdown_test",
        "MYSQL_DB_PASSWORD": "shutdown_test", "MYSQL_DB_NAME": "shutdown_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "shutdown-test-signing-key-00000000",
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.core import media_cleanup
    from AiVision.alarms.records import service
    from AiVision.cameras import runtime_manager
    return media_cleanup, service, runtime_manager


class References:
    media_directories = ("media",)

    def __init__(self, records=()):
        self.records = list(records)
        self.deleted = []

    def iter_records(self, before):
        yield from (record for record in self.records if record.created_at < before)

    def referenced_paths(self, paths):
        return {path for record in self.records for path in record.paths}

    def delete_record(self, record, remove_file):
        assert all(remove_file(path) for path in record.paths)
        self.deleted.append(record.id)
        return 1


def media_file(root, name, days=40):
    path = root / "media" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"evidence")
    timestamp = (datetime.datetime.now() - datetime.timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp))
    return path


def cleaner_for(module, root, references=None):
    return module.MediaCleaner(root, retention_days=31, max_bytes=1,
                               references=(references or References(),))


def test_cancel_finishes_current_record_and_keeps_next_record(modules, tmp_path):
    media, _, _ = modules
    files = [media_file(tmp_path, f"{index}.jpg") for index in range(3)]
    old = datetime.datetime.now() - datetime.timedelta(days=40)
    refs = References([media.MediaRecord(1, old, tuple(map(str, files[:2]))),
                       media.MediaRecord(2, old, (str(files[2]),))])
    entered, release = Event(), Event()

    def delete_record(record, remove_file):
        assert remove_file(record.paths[0])
        entered.set()
        assert release.wait(3)
        assert remove_file(record.paths[1])
        refs.deleted.append(record.id)
        return 1

    refs.delete_record = delete_record
    cleaner = cleaner_for(media, tmp_path, refs)
    results = []
    thread = Thread(target=lambda: results.append(cleaner.cleanup()))
    thread.start()
    try:
        assert entered.wait(3)
        cleaner.request_stop()
        # 请求取消不能被正在执行的清理锁阻塞。
        assert thread.is_alive()
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert refs.deleted == [1]
    assert not files[0].exists() and not files[1].exists() and files[2].exists()
    assert results[0].cancelled and results[0].removed_records == 1


def test_cancel_during_directory_scan_and_resume(modules, tmp_path, monkeypatch):
    media, _, _ = modules
    path = media_file(tmp_path, "old.jpg")
    cleaner = cleaner_for(media, tmp_path)
    original = Path.rglob

    def rglob(directory, pattern):
        for item in original(directory, pattern):
            cleaner.request_stop()
            yield item

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rglob", rglob)
        stats = cleaner.cleanup()
    assert stats.cancelled and path.exists()
    # 取消后释放锁；下一次启动可以恢复维护。
    cleaner.reset_stop()
    stats = cleaner.cleanup()
    assert not stats.cancelled and stats.removed_files == 1 and not path.exists()


@pytest.mark.parametrize("phase", ["sort", "capacity", "empty_directories"])
def test_cancel_remaining_scan_phases(modules, tmp_path, monkeypatch, phase):
    media, _, _ = modules
    path = media_file(tmp_path, "retained.jpg", days=1)
    cleaner = cleaner_for(media, tmp_path)
    if phase == "sort":
        original = cleaner._safe_mtime

        def mtime(item):
            cleaner.request_stop()
            return original(item)

        monkeypatch.setattr(cleaner, "_safe_mtime", mtime)
    else:
        original = cleaner._managed_entries
        calls = 0

        def entries():
            nonlocal calls
            calls += 1
            if calls == (2 if phase == "capacity" else 3):
                cleaner.request_stop()
            yield from original()

        monkeypatch.setattr(cleaner, "_managed_entries", entries)
    assert cleaner.cleanup().cancelled
    assert path.exists()


def test_retention_and_path_safety_survive_cancellation(modules, tmp_path):
    media, _, _ = modules
    recent = media_file(tmp_path, "recent.jpg", days=1)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    link = tmp_path / "media" / "link.jpg"
    link.symlink_to(outside)
    cleaner = cleaner_for(media, tmp_path)
    cleaner.request_stop()
    assert cleaner.cleanup().cancelled
    cleaner.reset_stop()
    stats = cleaner.cleanup()
    assert not stats.cancelled and stats.removed_files == 0
    assert recent.exists() and outside.exists() and link.is_symlink()


def test_writer_cancels_running_scheduler_and_drains_accepted_queue(modules, tmp_path, monkeypatch):
    media, service, _ = modules
    writer = service.AsyncViolationWriter()
    writer._media_cleaner = cleaner_for(media, tmp_path)
    entered = Event()

    def referenced_paths(paths):
        entered.set()
        assert writer._media_cleaner._stop_requested.wait(3)
        return set()

    writer._media_cleaner._primary_references[0].referenced_paths = referenced_paths
    patched = Mock()
    monkeypatch.setattr(writer, "_apply_metadata_patch", patched)
    for cycle in range(2):
        media_file(tmp_path, f"{cycle}.jpg")
        entered.clear()
        if cycle:
            writer.start()
        else:
            # 在 start 之前接受的记录也必须被排空。
            assert writer.enqueue_metadata_patch(event_key="event", feature_name="security_fence",
                department="general_electric", camera_no="camera_1", metadata={"reason": "test"})
            writer.start()
        try:
            assert entered.wait(3)
            writer.request_cleanup_stop()
            assert not writer._stop_event.is_set()
            writer.stop()
        finally:
            writer.stop()
        assert writer._queue.unfinished_tasks == 0
        assert writer._thread is None and writer._scheduler is None
    patched.assert_called_once()


def test_shutdown_notifies_maintenance_without_stopping_detection(modules, monkeypatch):
    from AiVision.runtime import orchestrator
    cleanup_stop = Mock()
    monkeypatch.setattr(orchestrator.violation_writer, "request_cleanup_stop", cleanup_stop)
    service = SimpleNamespace(begin_shutdown=Mock(return_value=1))
    instance = object.__new__(orchestrator.Orchestrator)
    instance.consumers = {"agv_person_check": SimpleNamespace(service=service)}
    instance.begin_shutdown()
    cleanup_stop.assert_called_once()
    service.begin_shutdown.assert_called_once_with(orchestrator.settings.runtime.shutdown_grace_seconds)


@pytest.mark.parametrize("fail_one", [False, True])
def test_camera_shutdown_notifies_all_then_reaps_in_parallel(modules, monkeypatch, fail_one):
    _, _, module = modules
    manager = module.CameraRuntimeManager(SimpleNamespace(Queue=lambda **kwargs: Queue()))
    monkeypatch.setattr(module.settings.runtime, "camera_stop_workers", 2)
    unregistered = set()
    monkeypatch.setattr(module.frame_reader_registry, "unregister", unregistered.add)
    # 两路必须同时进入 stop，串行回收会使屏障超时。
    barrier = Barrier(2, timeout=3)
    lock = Lock()
    active = peak = 0
    runtimes = {}

    def stop(name):
        nonlocal active, peak
        assert all(runtime.notified.is_set() for runtime in runtimes.values())
        assert name in unregistered
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            barrier.wait()
            if fail_one and name == "camera_0":
                raise RuntimeError("模拟回收失败")
        finally:
            with lock:
                active -= 1

    for index in range(4):
        name = f"camera_{index}"
        notified = Event()
        runtimes[name] = SimpleNamespace(notified=notified, request_stop=notified.set,
                                         stop=lambda key=name: stop(key))
    manager._runtimes.update(runtimes)
    if fail_one:
        with pytest.raises(RuntimeError, match="1 路"):
            manager.stop_all()
        assert manager._runtimes == {"camera_0": runtimes["camera_0"]}
    else:
        manager.stop_all()
        assert not manager._runtimes
    assert peak == 2 and manager._stopping
    assert unregistered == set(runtimes)


def test_camera_runtime_event_drain_only_ignores_empty_queue(modules, monkeypatch):
    _, _, module = modules
    manager = module.CameraRuntimeManager(SimpleNamespace(Queue=lambda **kwargs: Queue()))
    reported = Mock()
    monkeypatch.setattr(module.logger, "exception", reported)

    manager._drain_runtime_events()
    reported.assert_not_called()

    class BrokenQueue:
        def get_nowait(self):
            raise RuntimeError("manager queue disconnected")

    manager._runtime_event_queue = BrokenQueue()
    manager._drain_runtime_events()
    reported.assert_called_once()
    assert "读取摄像头运行事件失败" in reported.call_args.args[0]


def test_engine_uses_bounded_pool_and_socket_timeouts(modules, monkeypatch):
    from AiVision.core import db

    captured = {}
    engine = object()
    fake_db = SimpleNamespace(
        auto_create=False,
        sqlalchemy_url="mysql+pymysql://test:test@127.0.0.1/test",
        name="test",
        url="127.0.0.1",
        pool_timeout_seconds=7,
        connect_timeout_seconds=5,
        read_timeout_seconds=8,
        write_timeout_seconds=9,
    )

    def create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return engine

    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    monkeypatch.setattr(db, "settings", SimpleNamespace(db=fake_db))
    monkeypatch.setattr(db, "create_engine", create_engine)

    assert db.get_engine() is engine
    assert captured["url"] == fake_db.sqlalchemy_url
    assert captured["pool_timeout"] == 7
    assert captured["connect_args"] == {"connect_timeout": 5, "read_timeout": 8, "write_timeout": 9}


def test_database_bootstrap_engine_uses_socket_timeouts(monkeypatch):
    from AiVision.core import db

    captured = {}
    fake_db = SimpleNamespace(
        name="test",
        charset="utf8mb4",
        user="test",
        password="test",
        url="127.0.0.1",
        port=3306,
        pool_timeout_seconds=7,
        connect_timeout_seconds=5,
        read_timeout_seconds=8,
        write_timeout_seconds=9,
    )

    def create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        raise RuntimeError("skip database bootstrap")

    monkeypatch.setattr(db, "settings", SimpleNamespace(db=fake_db))
    monkeypatch.setattr(db, "create_engine", create_engine)

    with pytest.raises(RuntimeError, match="skip database bootstrap"):
        db._ensure_database_exists()

    assert captured["pool_timeout"] == 7
    assert captured["connect_args"] == {"connect_timeout": 5, "read_timeout": 8, "write_timeout": 9}


@pytest.mark.parametrize("already_signalled", [False, True])
@pytest.mark.parametrize("scenario", ["slow_exit", "timeout", "exited", "configured_timeout"])
def test_stop_script_waits_once_and_preserves_session_on_timeout(already_signalled, scenario):
    root = Path(__file__).resolve().parents[2]
    # 模拟时间与进程状态，不发真实信号、不等待现场关停时长。
    shell = r'''
set -euo pipefail
source scripts/service_control.sh
unset FUDA_STOP_TIMEOUT_SECONDS
expected_timeout=600
if [[ "$SCENARIO" == configured_timeout ]]; then
  FUDA_STOP_TIMEOUT_SECONDS=30
  expected_timeout=30
fi
SECONDS=0
session_killed=0
signals=0
fuda_find_aivision_pids() { [[ "$SCENARIO" == exited ]] || echo 123; return 0; }
fuda_aivision_pid_running() {
  [[ "$SCENARIO" == timeout || "$SECONDS" -lt 450 ]]
}
tmux() {
  case "$1" in
    show-option) [[ "$ALREADY" == 1 ]] && echo ' 123'; return 0 ;;
    set-option|has-session) return 0 ;;
    kill-session) session_killed=1 ;;
    *) return 1 ;;
  esac
}
kill() { [[ "$1" == -TERM && "$2" == 123 ]]; signals=$((signals + 1)); }
sleep() { SECONDS=$((SECONDS + 15)); }
if fuda_stop_session aivision; then result=0; else result=$?; fi
expected_signals=1
[[ "$ALREADY" == 1 || "$SCENARIO" == exited ]] && expected_signals=0
[[ "$signals" == "$expected_signals" ]]
if [[ "$SCENARIO" == timeout || "$SCENARIO" == configured_timeout ]]; then
  [[ "$result" != 0 && "$session_killed" == 0 && "$SECONDS" -ge "$expected_timeout" ]]
else
  [[ "$result" == 0 && "$session_killed" == 1 ]]
fi
'''
    result = subprocess.run(["bash", "-c", shell], cwd=root, capture_output=True, text=True,
                            env={**os.environ, "ALREADY": str(int(already_signalled)), "SCENARIO": scenario},
                            timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    if scenario != "exited":
        assert ("30s" if scenario == "configured_timeout" else "600s") in result.stdout
        assert "已等待 15s" in result.stdout


def test_stop_script_targets_only_main_process_in_its_session():
    root = Path(__file__).resolve().parents[2]
    shell = r'''
set -euo pipefail
source scripts/service_control.sh
tmux() { echo 100; }
ps() {
  if [[ "$*" == '-ww -eo pid=,ppid=,comm=,args=' ]]; then
    cat <<'PROCESSES'
100 1 bash bash
101 100 python python -m AiVision.main
102 101 python python -c model-worker
103 1 python python -m AiVision.main
104 100 python python -m unrelated.main
PROCESSES
  else
    case "$3" in
      101) echo 'Sl python python -m AiVision.main' ;;
      102) echo 'Z python python -m AiVision.main' ;;
      103) echo 'Sl python python -m unrelated.main' ;;
    esac
  fi
}
[[ "$(fuda_find_aivision_pids aivision)" == 101 ]]
fuda_aivision_pid_running 101
! fuda_aivision_pid_running 102
! fuda_aivision_pid_running 103
'''
    result = subprocess.run(["bash", "-c", shell], cwd=root, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
