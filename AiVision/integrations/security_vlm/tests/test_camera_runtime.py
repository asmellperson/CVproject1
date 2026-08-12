import stat
import threading
from pathlib import Path

import pytest
import yaml

try:
    import camera_runtime
except ModuleNotFoundError:
    camera_runtime = None


GENERAL = "general_electric"
ELECTRONICS = "electronics_electrician"


def test_camera_runtime_module_exists():
    assert camera_runtime is not None, "camera_runtime module is required"


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_camera_runtime_paths_are_scoped_by_camera(tmp_path):
    departments_root = tmp_path / "runtime" / "custom" / "departments"
    paths = camera_runtime.CameraRuntimePaths(
        departments_root,
        GENERAL,
        "camera-a",
    )

    assert paths.runtime_dir == (
        departments_root
        / GENERAL
        / "cameras"
        / "camera-a"
    )
    assert paths.department_runtime_dir == (
        departments_root / GENERAL
    )
    assert paths.pending_dir == paths.runtime_dir / "pending"
    assert paths.config_path == paths.runtime_dir / "worker_config.yaml"

    exact_root = tmp_path / "runtime" / "custom"
    exact_paths = camera_runtime.CameraRuntimePaths(
        exact_root,
        GENERAL,
        "camera-a",
    )
    assert exact_paths.runtime_dir == (
        exact_root / GENERAL / "cameras" / "camera-a"
    )


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_camera_runtime_paths_reject_unsafe_camera_ids(tmp_path):
    for camera_id in ("", ".", "..", "../camera-a", "camera/a", "camera a"):
        with pytest.raises(ValueError, match="camera_id"):
            camera_runtime.CameraRuntimePaths(tmp_path, GENERAL, camera_id)


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
    paths = camera_runtime.CameraRuntimePaths(
        tmp_path / "runtime",
        ELECTRONICS,
        "camera-a",
    )

    snapshot = camera_runtime.build_camera_config(base_cfg, camera, paths)

    assert snapshot["data"]["department"] == ELECTRONICS
    assert snapshot["data"]["input_video"] == camera["rtsp_url"]
    assert snapshot["data"]["video_id"] == camera["camera_id"]
    assert snapshot["data"]["camera_name"] == camera["name"]
    assert snapshot["runtime"]["dir"] == str(paths.runtime_dir)
    assert snapshot["runtime"]["department_dir"] == str(
        paths.department_runtime_dir
    )
    assert snapshot["session"]["pending_queue_dir"] == str(paths.pending_dir)
    snapshot["data"]["video_id"] = "changed"
    assert base_cfg["data"]["video_id"] == "legacy"


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_build_camera_config_uses_department_roi_directory(tmp_path):
    base_cfg = {
        "data": {"staff_identity_dir": "data/annotations/staff_rois"},
        "runtime": {},
        "session": {},
    }
    camera = {
        "camera_id": "camera-a",
        "name": "安检工位一号",
        "rtsp_url": "rtsp://camera-a/stream",
    }
    paths = camera_runtime.CameraRuntimePaths(
        tmp_path / "runtime" / "departments",
        ELECTRONICS,
        "camera-a",
    )
    roi_dir = tmp_path / "data" / "departments" / ELECTRONICS / "rois"

    snapshot = camera_runtime.build_camera_config(
        base_cfg,
        camera,
        paths,
        staff_identity_dir=roi_dir,
    )

    assert snapshot["data"]["staff_identity_dir"] == str(roi_dir.resolve())
    assert base_cfg["data"]["staff_identity_dir"] == "data/annotations/staff_rois"


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


def make_manager(
    tmp_path,
    cameras,
    *,
    failing_camera_id=None,
    fail_vlm=False,
    max_running_cameras=16,
):
    events = []
    clock = [100.0]
    cameras_by_department = (
        cameras
        if isinstance(cameras, dict)
        else {GENERAL: list(cameras)}
    )

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
        "runtime": {
            "dir": str(tmp_path / "runtime"),
            "max_running_cameras": max_running_cameras,
        },
        "data": {},
        "session": {},
    }
    manager = camera_runtime.CameraRuntimeManager(
        base_cfg=base_cfg,
        project_root=tmp_path / "project",
        base_config_path=tmp_path / "config.yaml",
        camera_provider=lambda department: list(
            cameras_by_department.get(department, [])
        ),
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

    manager.start(GENERAL, "camera-a")
    manager.start(GENERAL, "camera-b")

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
    assert manager.is_running(GENERAL, "camera-a") is True
    assert manager.is_running(GENERAL, "camera-b") is True
    assert (
        manager.runtimes[(GENERAL, "camera-a")].config_path
        != manager.runtimes[(GENERAL, "camera-b")].config_path
    )


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_manager_removes_stale_framehub_before_starting_workers(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
    ]
    manager, _events, _clock = make_manager(tmp_path, cameras)
    paths = manager._paths(GENERAL, "camera-a")
    paths.runtime_dir.mkdir(parents=True)
    for name in ("frame_meta.json", "frame_slot_0.bin", "frame_slot_1.bin"):
        (paths.runtime_dir / name).write_bytes(b"stale")

    manager.start(GENERAL, "camera-a")

    for name in ("frame_meta.json", "frame_slot_0.bin", "frame_slot_1.bin"):
        assert not (paths.runtime_dir / name).exists()
    assert paths.config_path.exists()


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_force_killed_worker_is_waited_for_reaping():
    events = []

    class SlowProcess(FakeProcess):
        def __init__(self):
            super().__init__("slow", events)
            self.wait_calls = 0

        def terminate(self):
            events.append(("terminate", self.name))

        def wait(self, timeout=None):
            self.wait_calls += 1
            events.append(("wait", self.name, timeout))
            if self.wait_calls == 1:
                raise TimeoutError("still running")
            return self.returncode

    process = SlowProcess()
    camera_runtime.CameraRuntimeManager._terminate_process(process, "detector")

    assert ("kill", "slow") in events
    assert ("wait", "slow", 2.0) in events


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_stopping_one_camera_leaves_other_running_and_stops_vlm_last(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
        {"camera_id": "camera-b", "name": "B", "rtsp_url": "rtsp://b/stream"},
    ]
    manager, events, _clock = make_manager(tmp_path, cameras)
    manager.start_all(GENERAL)
    events.clear()

    manager.stop(GENERAL, "camera-a")

    terminated = [event[1] for event in events if event[0] == "terminate"]
    assert terminated == [
        "camera-a:session_worker",
        "camera-a:detector_worker",
        "camera-a:capture_worker",
    ]
    assert manager.is_running(GENERAL, "camera-b") is True
    assert manager.vlm_process.poll() is None

    manager.stop(GENERAL, "camera-b")
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

    result = manager.start_all(GENERAL)

    assert result["results"]["bad-camera"]["ok"] is False
    assert result["results"]["camera-b"]["ok"] is True
    assert manager.is_running(GENERAL, "camera-b") is True


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_unexpected_exit_uses_bounded_backoff_and_user_stop_cancels_restart(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
    ]
    manager, _events, clock = make_manager(tmp_path, cameras)
    manager.start(GENERAL, "camera-a")
    runtime = manager.runtimes[(GENERAL, "camera-a")]

    delays = []
    for attempt in range(6):
        runtime.processes["detector"].returncode = 1
        manager.reconcile()
        delays.append(runtime.restart_at - clock[0])
        clock[0] = runtime.restart_at
        manager.reconcile()
        runtime = manager.runtimes[(GENERAL, "camera-a")]

    assert delays == [1, 2, 5, 10, 30, 30]
    manager.stop(GENERAL, "camera-a")
    assert runtime.desired_running is False
    assert runtime.restart_at is None


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_explicit_start_cleans_up_partially_alive_old_group(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
    ]
    manager, events, _clock = make_manager(tmp_path, cameras)
    manager.start(GENERAL, "camera-a")
    runtime = manager.runtimes[(GENERAL, "camera-a")]
    runtime.processes["detector"].returncode = 1
    events.clear()

    manager.start(GENERAL, "camera-a")

    terminated = [event[1] for event in events if event[0] == "terminate"]
    assert terminated[:2] == [
        "camera-a:session_worker",
        "camera-a:capture_worker",
    ]
    assert manager.is_running(GENERAL, "camera-a") is True


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_vlm_start_failure_marks_camera_start_degraded_and_schedules_retry(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
    ]
    manager, _events, _clock = make_manager(tmp_path, cameras, fail_vlm=True)

    result = manager.start(GENERAL, "camera-a")
    vlm = manager.vlm_status()

    assert result["ok"] is False
    assert result["running"] is True
    assert result["degraded"] is True
    assert vlm["running"] is False
    assert vlm["restart_at"] == 101.0
    assert "vlm failed" in vlm["last_error"]


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_same_camera_id_runs_independently_in_two_departments(tmp_path):
    shared_camera = {
        "camera_id": "shared-camera",
        "name": "共享编号",
        "rtsp_url": "rtsp://camera/stream",
    }
    manager, _events, _clock = make_manager(
        tmp_path,
        {
            GENERAL: [shared_camera],
            ELECTRONICS: [shared_camera],
        },
    )

    assert manager.start(GENERAL, "shared-camera")["ok"] is True
    assert manager.start(ELECTRONICS, "shared-camera")["ok"] is True

    general_runtime = manager.runtimes[(GENERAL, "shared-camera")]
    electronics_runtime = manager.runtimes[(ELECTRONICS, "shared-camera")]
    assert general_runtime is not electronics_runtime
    assert general_runtime.department == GENERAL
    assert electronics_runtime.department == ELECTRONICS
    assert general_runtime.config_path != electronics_runtime.config_path
    assert GENERAL in general_runtime.config_path.parts
    assert ELECTRONICS in electronics_runtime.config_path.parts


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_start_all_and_stop_all_only_affect_requested_department(tmp_path):
    cameras = {
        GENERAL: [
            {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
        ],
        ELECTRONICS: [
            {"camera_id": "camera-b", "name": "B", "rtsp_url": "rtsp://b/stream"},
        ],
    }
    manager, _events, _clock = make_manager(tmp_path, cameras)

    manager.start_all(GENERAL)
    manager.start_all(ELECTRONICS)
    manager.stop_all(GENERAL)

    assert manager.is_running(GENERAL, "camera-a") is False
    assert manager.is_running(ELECTRONICS, "camera-b") is True
    assert manager.vlm_process.poll() is None


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_total_runtime_limit_and_duplicate_start_idempotency(tmp_path):
    shared_camera = {
        "camera_id": "shared-camera",
        "name": "共享编号",
        "rtsp_url": "rtsp://camera/stream",
    }
    manager, events, _clock = make_manager(
        tmp_path,
        {
            GENERAL: [shared_camera],
            ELECTRONICS: [shared_camera],
        },
        max_running_cameras=1,
    )

    first = manager.start(GENERAL, "shared-camera")
    starts_after_first = len([event for event in events if event[0] == "start"])
    duplicate = manager.start(GENERAL, "shared-camera")
    starts_after_duplicate = len([event for event in events if event[0] == "start"])
    over_limit = manager.start(ELECTRONICS, "shared-camera")

    assert first["ok"] is True
    assert duplicate["ok"] is True
    assert duplicate["message"] == "already running"
    assert starts_after_duplicate == starts_after_first
    assert over_limit["ok"] is False
    assert "1" in over_limit["message"]
    assert "上限" in over_limit["message"]


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_manager_rejects_unknown_department_and_unsafe_camera_id(tmp_path):
    manager, _events, _clock = make_manager(tmp_path, [])

    with pytest.raises(ValueError, match="事业部"):
        manager.start("unknown", "camera-a")
    for camera_id in (".", "..", "../camera-a"):
        with pytest.raises(ValueError, match="camera_id"):
            manager.status(GENERAL, camera_id)


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_manager_resolves_relative_roots_from_security_vlm_project(tmp_path):
    project_root = tmp_path / "security_vlm"
    base_cfg = {
        "envs": {"worker_python": "/env/bin/python"},
        "runtime": {
            "dir": "runtime",
            "camera_root": "runtime/legacy-cameras",
            "max_running_cameras": 16,
        },
        "departments": {
            "data_root": "data/custom/departments",
            "runtime_root": "runtime/custom/departments",
        },
        "data": {},
        "session": {},
    }
    manager = camera_runtime.CameraRuntimeManager(
        base_cfg=base_cfg,
        project_root=project_root,
        base_config_path=project_root / "config.yaml",
        camera_provider=lambda _department: [],
        start_monitor=False,
    )

    assert manager.base_runtime_dir == (project_root / "runtime").resolve()
    assert manager.legacy_camera_root == (
        project_root / "runtime" / "legacy-cameras"
    ).resolve()
    assert manager.departments_root == (
        project_root / "runtime" / "custom" / "departments"
    ).resolve()
    assert manager.departments_data_root == (
        project_root / "data" / "custom" / "departments"
    ).resolve()


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_started_session_worker_reads_the_same_department_roi_directory(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
    ]
    manager, _events, _clock = make_manager(tmp_path, cameras)

    assert manager.start(GENERAL, "camera-a")["ok"] is True

    snapshot = yaml.safe_load(
        manager._paths(GENERAL, "camera-a").config_path.read_text(encoding="utf-8")
    )
    assert snapshot["data"]["staff_identity_dir"] == str(
        (manager.departments_data_root / GENERAL / "rois").resolve()
    )


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_vlm_command_passes_exact_department_and_legacy_roots(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
    ]
    manager, events, _clock = make_manager(tmp_path, cameras)

    assert manager.start(GENERAL, "camera-a")["ok"] is True

    vlm_command = next(
        event[2]
        for event in events
        if event[0] == "start" and event[1] == "global:vlm_worker"
    )
    assert vlm_command[vlm_command.index("--departments-root") + 1] == str(
        manager.departments_root
    )
    assert vlm_command[vlm_command.index("--camera-root") + 1] == str(
        manager.legacy_camera_root
    )


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_stop_all_linearizes_against_concurrent_start(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
        {"camera_id": "camera-b", "name": "B", "rtsp_url": "rtsp://b/stream"},
    ]
    manager, _events, _clock = make_manager(tmp_path, cameras)
    manager.start(GENERAL, "camera-a")
    original_stop = manager.stop
    stop_entered = threading.Event()
    allow_stop = threading.Event()

    def blocked_stop(department, camera_id):
        stop_entered.set()
        assert allow_stop.wait(timeout=2)
        return original_stop(department, camera_id)

    manager.stop = blocked_stop
    stop_thread = threading.Thread(target=manager.stop_all, args=(GENERAL,))
    start_result = {}
    start_thread = threading.Thread(
        target=lambda: start_result.update(manager.start(GENERAL, "camera-b"))
    )

    stop_thread.start()
    assert stop_entered.wait(timeout=2)
    start_thread.start()
    allow_stop.set()
    stop_thread.join(timeout=2)
    start_thread.join(timeout=2)

    assert not stop_thread.is_alive()
    assert not start_thread.is_alive()
    assert manager.is_running(GENERAL, "camera-a") is False
    # start 要么在线性化点前完成并被 stop_all 停止，要么在线性化点后成功。
    if start_result["ok"]:
        assert manager.is_running(GENERAL, "camera-b") is True


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_shutdown_rejects_concurrent_and_future_starts(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
        {"camera_id": "camera-b", "name": "B", "rtsp_url": "rtsp://b/stream"},
    ]
    manager, _events, _clock = make_manager(tmp_path, cameras)
    manager.start(GENERAL, "camera-a")
    entered = threading.Event()
    release = threading.Event()
    original_terminate = manager._terminate_processes

    def blocked_terminate(processes):
        entered.set()
        assert release.wait(timeout=2)
        original_terminate(processes)

    manager._terminate_processes = blocked_terminate
    shutdown_thread = threading.Thread(target=manager.shutdown)
    concurrent = {}
    start_thread = threading.Thread(
        target=lambda: concurrent.update(manager.start(GENERAL, "camera-b"))
    )
    shutdown_thread.start()
    assert entered.wait(timeout=2)

    start_thread.start()
    release.set()
    shutdown_thread.join(timeout=2)
    start_thread.join(timeout=2)
    future = manager.start(GENERAL, "camera-b")

    assert not shutdown_thread.is_alive()
    assert not start_thread.is_alive()
    assert concurrent["ok"] is False
    assert future["ok"] is False
    assert "关闭" in concurrent["message"]
    assert all(not runtime.desired_running for runtime in manager.runtimes.values())


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_slow_stop_does_not_hold_cross_department_global_lock(tmp_path):
    manager, events, _clock = make_manager(
        tmp_path,
        {
            GENERAL: [
                {
                    "camera_id": "camera-a",
                    "name": "A",
                    "rtsp_url": "rtsp://a/stream",
                },
            ],
            ELECTRONICS: [
                {
                    "camera_id": "camera-b",
                    "name": "B",
                    "rtsp_url": "rtsp://b/stream",
                },
            ],
        },
    )
    wait_entered = threading.Event()
    release_wait = threading.Event()

    class SlowProcess(FakeProcess):
        def terminate(self):
            self.events.append(("terminate", self.name))

        def wait(self, timeout=None):
            wait_entered.set()
            assert release_wait.wait(timeout=2)
            self.returncode = 0
            return self.returncode

    manager.runtimes[(GENERAL, "camera-a")] = camera_runtime.CameraRuntime(
        GENERAL,
        "camera-a",
        tmp_path / "camera-a.yaml",
        desired_running=True,
        processes={"capture": SlowProcess("camera-a:capture", events)},
    )
    manager.runtimes[(ELECTRONICS, "camera-b")] = camera_runtime.CameraRuntime(
        ELECTRONICS,
        "camera-b",
        tmp_path / "camera-b.yaml",
        desired_running=True,
        processes={
            name: FakeProcess(f"camera-b:{name}", events)
            for name in ("capture", "detector", "session")
        },
    )
    stop_thread = threading.Thread(
        target=manager.stop,
        args=(GENERAL, "camera-a"),
    )
    stop_thread.start()
    assert wait_entered.wait(timeout=2)

    probe_done = threading.Event()
    probe_result = []

    def probe_other_department():
        probe_result.append(manager.is_running(ELECTRONICS, "camera-b"))
        probe_done.set()

    probe_thread = threading.Thread(target=probe_other_department)
    probe_thread.start()
    assert probe_done.wait(timeout=0.2)
    assert probe_result == [True]

    release_wait.set()
    stop_thread.join(timeout=2)
    probe_thread.join(timeout=2)
    assert not stop_thread.is_alive()


@pytest.mark.skipif(camera_runtime is None, reason="camera_runtime is not implemented")
def test_reconcile_waits_for_old_group_before_same_camera_restart(tmp_path):
    cameras = [
        {"camera_id": "camera-a", "name": "A", "rtsp_url": "rtsp://a/stream"},
    ]
    manager, events, _clock = make_manager(tmp_path, cameras)
    wait_entered = threading.Event()
    release_wait = threading.Event()

    class SlowProcess(FakeProcess):
        def terminate(self):
            self.events.append(("terminate", self.name))

        def wait(self, timeout=None):
            wait_entered.set()
            assert release_wait.wait(timeout=2)
            self.returncode = 0
            return self.returncode

    failed_detector = FakeProcess("old:detector", events)
    failed_detector.returncode = 1
    runtime = camera_runtime.CameraRuntime(
        GENERAL,
        "camera-a",
        tmp_path / "camera-a.yaml",
        desired_running=True,
        processes={
            "capture": SlowProcess("old:capture", events),
            "detector": failed_detector,
            "session": FakeProcess("old:session", events),
        },
    )
    manager.runtimes[(GENERAL, "camera-a")] = runtime
    reconcile_thread = threading.Thread(target=manager.reconcile)
    start_result = {}
    start_thread = threading.Thread(
        target=lambda: start_result.update(
            manager.start(GENERAL, "camera-a")
        )
    )

    reconcile_thread.start()
    assert wait_entered.wait(timeout=2)
    starts_before = len([event for event in events if event[0] == "start"])
    start_thread.start()
    assert start_thread.is_alive()
    assert len([event for event in events if event[0] == "start"]) == starts_before

    release_wait.set()
    reconcile_thread.join(timeout=2)
    start_thread.join(timeout=2)
    assert not reconcile_thread.is_alive()
    assert not start_thread.is_alive()
    assert start_result["ok"] is True
