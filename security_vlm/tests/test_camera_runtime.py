import stat
from pathlib import Path

import pytest
import yaml

try:
    import camera_runtime
except ModuleNotFoundError:
    camera_runtime = None


def test_camera_runtime_module_exists():
    assert camera_runtime is not None, "camera_runtime module is required"


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_camera_runtime_paths_are_scoped_by_camera(tmp_path):
    paths = camera_runtime.CameraRuntimePaths(tmp_path / "runtime", "camera-a")

    assert paths.runtime_dir == tmp_path / "runtime" / "cameras" / "camera-a"
    assert paths.pending_dir == paths.runtime_dir / "pending"
    assert paths.config_path == paths.runtime_dir / "worker_config.yaml"

    custom_paths = camera_runtime.CameraRuntimePaths(
        tmp_path / "runtime",
        "camera-a",
        camera_root_dir=tmp_path / "custom-camera-root",
    )
    assert custom_paths.runtime_dir == tmp_path / "custom-camera-root" / "camera-a"


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_camera_runtime_paths_reject_unsafe_camera_ids(tmp_path):
    for camera_id in ("", "../camera-a", "camera/a", "camera a"):
        with pytest.raises(ValueError, match="camera_id"):
            camera_runtime.CameraRuntimePaths(tmp_path, camera_id)


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_build_camera_config_is_isolated_from_base_config(tmp_path):
    base_cfg = {
        "data": {"input_video": "rtsp://legacy/stream", "video_id": "legacy"},
        "runtime": {"dir": "/tmp/legacy-runtime"},
        "session": {"pending_queue_dir": "/tmp/legacy-pending"},
    }
    camera = {
        "camera_id": "camera-a",
        "name": "安检工位一号",
        "rtsp_url": "rtsp://admin:secret@camera-a/stream",
    }
    paths = camera_runtime.CameraRuntimePaths(tmp_path / "runtime", "camera-a")

    snapshot = camera_runtime.build_camera_config(base_cfg, camera, paths)

    assert snapshot["data"]["input_video"] == camera["rtsp_url"]
    assert snapshot["data"]["video_id"] == camera["camera_id"]
    assert snapshot["data"]["camera_name"] == camera["name"]
    assert snapshot["runtime"]["dir"] == str(paths.runtime_dir)
    assert snapshot["session"]["pending_queue_dir"] == str(paths.pending_dir)
    snapshot["data"]["video_id"] = "changed"
    assert base_cfg["data"]["video_id"] == "legacy"


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_write_camera_config_is_atomic_and_owner_only(tmp_path):
    config_path = tmp_path / "runtime" / "worker_config.yaml"
    snapshot = {"data": {"input_video": "rtsp://camera-a/stream"}}

    camera_runtime.write_camera_config(snapshot, config_path)

    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == snapshot
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert list(config_path.parent.glob("*.tmp")) == []


class FakeProcess:
    def __init__(self, name, events):
        self.name = name
        self.events = events
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.events.append(("terminate", self.name))
        self.returncode = 0

    def wait(self, timeout=None):
        self.events.append(("wait", self.name))
        return self.returncode

    def kill(self):
        self.events.append(("kill", self.name))
        self.returncode = -9


def make_manager(tmp_path, cameras, *, failing_camera_id=None, fail_vlm=False):
    events = []
    clock = [100.0]

    def popen(command, cwd=None, env=None):
        script_name = Path(command[1]).stem
        camera_id = "global"
        if "--config" in command:
            config_path = Path(command[command.index("--config") + 1])
            if config_path.name == "worker_config.yaml":
                camera_id = config_path.parent.name
        if failing_camera_id == camera_id and script_name == "detector_worker":
            raise RuntimeError("detector failed")
        if fail_vlm and script_name == "vlm_worker":
            raise RuntimeError("vlm failed")
        name = f"{camera_id}:{script_name}"
        events.append(("start", name, command))
        return FakeProcess(name, events)

    base_cfg = {
        "envs": {"worker_python": "/env/bin/python"},
        "runtime": {"dir": str(tmp_path / "runtime")},
        "data": {},
        "session": {},
    }
    manager = camera_runtime.CameraRuntimeManager(
        base_cfg=base_cfg,
        project_root=tmp_path / "project",
        base_config_path=tmp_path / "config.yaml",
        camera_provider=lambda: list(cameras),
        popen_factory=popen,
        sleep=lambda _seconds: None,
        clock=lambda: clock[0],
        start_monitor=False,
    )
    return manager, events, clock


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_manager_starts_camera_workers_in_order_and_vlm_once(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
        {"camera_id": "camera-b", "name": "B", "rtsp_url": "rtsp://b/stream"},
    ]
    manager, events, _clock = make_manager(tmp_path, cameras)

    manager.start("camera-a")
    manager.start("camera-b")

    starts = [event[1] for event in events if event[0] == "start"]
    assert starts == [
        "camera-a:capture_worker",
        "camera-a:detector_worker",
        "camera-a:session_worker",
        "global:vlm_worker",
        "camera-b:capture_worker",
        "camera-b:detector_worker",
        "camera-b:session_worker",
    ]
    assert manager.is_running("camera-a") is True
    assert manager.is_running("camera-b") is True
    assert (
        manager.runtimes["camera-a"].config_path
        != manager.runtimes["camera-b"].config_path
    )


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_stopping_one_camera_leaves_other_running_and_stops_vlm_last(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
        {"camera_id": "camera-b", "name": "B", "rtsp_url": "rtsp://b/stream"},
    ]
    manager, events, _clock = make_manager(tmp_path, cameras)
    manager.start_all()
    events.clear()

    manager.stop("camera-a")

    terminated = [event[1] for event in events if event[0] == "terminate"]
    assert terminated == [
        "camera-a:session_worker",
        "camera-a:detector_worker",
        "camera-a:capture_worker",
    ]
    assert manager.is_running("camera-b") is True
    assert manager.vlm_process.poll() is None

    manager.stop("camera-b")
    assert [event[1] for event in events if event[0] == "terminate"][-1] == (
        "global:vlm_worker"
    )


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_start_all_continues_after_one_camera_fails(tmp_path):
    cameras = [
        {"camera_id": "bad-camera", "name": "Bad", "rtsp_url": "rtsp://bad/stream"},
        {"camera_id": "camera-b", "name": "B", "rtsp_url": "rtsp://b/stream"},
    ]
    manager, _events, _clock = make_manager(
        tmp_path,
        cameras,
        failing_camera_id="bad-camera",
    )

    result = manager.start_all()

    assert result["results"]["bad-camera"]["ok"] is False
    assert result["results"]["camera-b"]["ok"] is True
    assert manager.is_running("camera-b") is True


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_unexpected_exit_uses_bounded_backoff_and_user_stop_cancels_restart(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
    ]
    manager, _events, clock = make_manager(tmp_path, cameras)
    manager.start("camera-a")
    runtime = manager.runtimes["camera-a"]

    delays = []
    for attempt in range(6):
        runtime.processes["detector"].returncode = 1
        manager.reconcile()
        delays.append(runtime.restart_at - clock[0])
        clock[0] = runtime.restart_at
        manager.reconcile()
        runtime = manager.runtimes["camera-a"]

    assert delays == [1, 2, 5, 10, 30, 30]
    manager.stop("camera-a")
    assert runtime.desired_running is False
    assert runtime.restart_at is None


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_explicit_start_cleans_up_partially_alive_old_group(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
    ]
    manager, events, _clock = make_manager(tmp_path, cameras)
    manager.start("camera-a")
    runtime = manager.runtimes["camera-a"]
    runtime.processes["detector"].returncode = 1
    events.clear()

    manager.start("camera-a")

    terminated = [event[1] for event in events if event[0] == "terminate"]
    assert terminated[:2] == [
        "camera-a:session_worker",
        "camera-a:capture_worker",
    ]
    assert manager.is_running("camera-a") is True


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_vlm_start_failure_marks_camera_start_degraded_and_schedules_retry(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
    ]
    manager, _events, _clock = make_manager(tmp_path, cameras, fail_vlm=True)

    result = manager.start("camera-a")
    vlm = manager.vlm_status()

    assert result["ok"] is False
    assert result["running"] is True
    assert result["degraded"] is True
    assert vlm["running"] is False
    assert vlm["restart_at"] == 101.0
    assert "vlm failed" in vlm["last_error"]
