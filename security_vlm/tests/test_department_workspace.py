import json
import multiprocessing
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import camera_registry
import department_workspace
from department_workspace import (
    DepartmentWorkspaceManager,
    migrate_general_electric,
)
from departments import SECURITY_DEPARTMENTS, require_department


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _legacy_camera(camera_id="legacy-camera"):
    return {
        "camera_id": camera_id,
        "name": "旧摄像头",
        "rtsp_url": "rtsp://user:secret@legacy-camera/stream",
        "created_at": 1.0,
        "updated_at": 1.0,
    }


def _migration_source(tmp_path):
    legacy_registry = tmp_path / "legacy" / "cameras.json"
    legacy_roi_dir = tmp_path / "legacy" / "rois"
    legacy_runtime_dir = tmp_path / "legacy" / "runtime"
    _write_json(
        legacy_registry,
        {"version": 1, "cameras": [_legacy_camera()]},
    )
    _write_json(
        legacy_roi_dir / "legacy-camera_staff_rois.json",
        {"staff_rois": {"工位": [1, 2, 3, 4]}},
    )
    for name in (
        "vlm_state.json",
        "vlm_history.json",
        "vlm_latest_stats.json",
        "vlm_budget.json",
    ):
        _write_json(legacy_runtime_dir / name, {"source": name})
    return legacy_registry, legacy_roi_dir, legacy_runtime_dir


def _migrate(manager, source):
    legacy_registry, legacy_roi_dir, legacy_runtime_dir = source
    return migrate_general_electric(
        manager,
        legacy_registry_path=legacy_registry,
        legacy_roi_dir=legacy_roi_dir,
        legacy_runtime_dir=legacy_runtime_dir,
    )


def _process_migrate(
    data_root,
    runtime_root,
    source,
    start_event,
    results,
):
    original_load = department_workspace._load_legacy_cameras

    def slow_load(path):
        cameras = original_load(path)
        time.sleep(0.1)
        return cameras

    department_workspace._load_legacy_cameras = slow_load
    manager = DepartmentWorkspaceManager(data_root, runtime_root)
    start_event.wait()
    try:
        migrated = _migrate(manager, source)
    except Exception as exc:
        results.put(("error", type(exc).__name__, str(exc)))
    else:
        results.put(("ok", migrated))


def test_requires_known_non_empty_department():
    for department in SECURITY_DEPARTMENTS:
        assert require_department(department) == department

    with pytest.raises(ValueError, match="事业部"):
        require_department("")
    with pytest.raises(ValueError, match="事业部"):
        require_department("unknown")


def test_manager_creates_four_isolated_empty_workspaces(tmp_path):
    manager = DepartmentWorkspaceManager(
        tmp_path / "data",
        tmp_path / "runtime",
    )

    workspaces = [manager.get(department) for department in SECURITY_DEPARTMENTS]

    assert len({workspace.data_dir for workspace in workspaces}) == 4
    assert len({workspace.runtime_dir for workspace in workspaces}) == 4
    assert len({workspace.registry.path for workspace in workspaces}) == 4
    assert len({workspace.roi_dir for workspace in workspaces}) == 4
    assert len({workspace.camera_runtime_dir for workspace in workspaces}) == 4
    assert len({workspace.archive_dir for workspace in workspaces}) == 4
    assert len({workspace.results_dir for workspace in workspaces}) == 4

    for workspace in workspaces:
        assert workspace.department in SECURITY_DEPARTMENTS
        assert workspace.data_dir.is_dir()
        assert workspace.runtime_dir.is_dir()
        assert workspace.roi_dir.is_dir()
        assert workspace.camera_runtime_dir.is_dir()
        assert workspace.archive_dir.is_dir()
        assert workspace.results_dir.is_dir()
        assert workspace.registry.path.is_file()
        assert workspace.registry.list() == []
        assert workspace.result_store.runtime_dir == workspace.results_dir
        assert workspace.results_dir.parent == workspace.data_dir
        assert workspace.results_dir != workspace.runtime_dir
        payload = json.loads(workspace.registry.path.read_text(encoding="utf-8"))
        assert payload == {
            "version": 2,
            "department": workspace.department,
            "cameras": [],
        }


def test_legacy_data_migrates_only_to_general_electric_and_is_idempotent(tmp_path):
    manager = DepartmentWorkspaceManager(
        tmp_path / "departments",
        tmp_path / "runtime" / "departments",
    )
    legacy_registry = tmp_path / "legacy" / "cameras.json"
    legacy_roi_dir = tmp_path / "legacy" / "rois"
    legacy_runtime_dir = tmp_path / "legacy" / "runtime"
    camera = _legacy_camera()
    _write_json(legacy_registry, {"version": 1, "cameras": [camera]})
    _write_json(
        legacy_roi_dir / "legacy-camera_staff_rois.json",
        {"staff_rois": {"工位": [1, 2, 3, 4]}},
    )
    persistent_names = (
        "vlm_state.json",
        "vlm_history.json",
        "vlm_latest_stats.json",
        "vlm_budget.json",
    )
    for name in persistent_names:
        _write_json(legacy_runtime_dir / name, {"source": name})
    for name in (
        "frame_meta.json",
        "capture_status.json",
        "vlm_status.json",
        "session_pending.json",
    ):
        _write_json(legacy_runtime_dir / name, {"temporary": True})

    first = migrate_general_electric(
        manager,
        legacy_registry_path=legacy_registry,
        legacy_roi_dir=legacy_roi_dir,
        legacy_runtime_dir=legacy_runtime_dir,
    )
    second = migrate_general_electric(
        manager,
        legacy_registry_path=legacy_registry,
        legacy_roi_dir=legacy_roi_dir,
        legacy_runtime_dir=legacy_runtime_dir,
    )

    general = manager.get("general_electric")
    assert first is True
    assert second is False
    assert general.registry.list() == [camera]
    registry_payload = json.loads(
        general.registry.path.read_text(encoding="utf-8")
    )
    assert registry_payload["version"] == 2
    assert registry_payload["department"] == "general_electric"
    assert (general.data_dir / ".migration-v2.json").is_file()
    assert (
        general.roi_dir / "legacy-camera_staff_rois.json"
    ).read_text(encoding="utf-8") == (
        legacy_roi_dir / "legacy-camera_staff_rois.json"
    ).read_text(encoding="utf-8")

    for name in persistent_names:
        assert json.loads((general.results_dir / name).read_text(encoding="utf-8")) == {
            "source": name
        }
    assert not (general.runtime_dir / "frame_meta.json").exists()
    assert not (general.runtime_dir / "capture_status.json").exists()
    assert not (general.runtime_dir / "vlm_status.json").exists()
    assert not (general.runtime_dir / "session_pending.json").exists()
    assert not any((general.runtime_dir / name).exists() for name in persistent_names)

    for department in SECURITY_DEPARTMENTS:
        if department != "general_electric":
            assert manager.get(department).registry.list() == []

    assert legacy_registry.exists()
    assert (legacy_roi_dir / "legacy-camera_staff_rois.json").exists()
    for name in persistent_names:
        assert (legacy_runtime_dir / name).exists()


def test_migration_copies_only_rois_for_registered_cameras(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    legacy_registry = tmp_path / "legacy" / "cameras.json"
    legacy_roi_dir = tmp_path / "legacy" / "rois"
    camera = _legacy_camera("registered")
    _write_json(legacy_registry, {"version": 1, "cameras": [camera]})
    _write_json(
        legacy_roi_dir / "registered_staff_rois.json",
        {"staff_rois": {"registered": [1, 2, 3, 4]}},
    )
    _write_json(
        legacy_roi_dir / "orphan_staff_rois.json",
        {"staff_rois": {"orphan": [5, 6, 7, 8]}},
    )

    assert migrate_general_electric(
        manager,
        legacy_registry_path=legacy_registry,
        legacy_roi_dir=legacy_roi_dir,
        legacy_runtime_dir=tmp_path / "legacy" / "runtime",
    )

    general = manager.get("general_electric")
    assert (general.roi_dir / "registered_staff_rois.json").is_file()
    assert not (general.roi_dir / "orphan_staff_rois.json").exists()


def test_migration_validates_all_json_before_replacing_targets(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    legacy_registry = tmp_path / "legacy" / "cameras.json"
    legacy_runtime_dir = tmp_path / "legacy" / "runtime"
    _write_json(
        legacy_registry,
        {"version": 1, "cameras": [_legacy_camera()]},
    )
    legacy_runtime_dir.mkdir(parents=True)
    (legacy_runtime_dir / "vlm_history.json").write_text(
        "{broken",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="迁移 JSON"):
        migrate_general_electric(
            manager,
            legacy_registry_path=legacy_registry,
            legacy_roi_dir=tmp_path / "legacy" / "rois",
            legacy_runtime_dir=legacy_runtime_dir,
        )

    general = manager.get("general_electric")
    assert general.registry.list() == []
    assert not (general.data_dir / ".migration-v2.json").exists()
    assert not (general.results_dir / "vlm_history.json").exists()


@pytest.mark.parametrize(
    "target_name",
    ["cameras.json", "vlm_history.json"],
)
def test_completed_marker_rejects_missing_target(tmp_path, target_name):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    assert _migrate(manager, source) is True
    general = manager.get("general_electric")
    marker = json.loads(
        (general.data_dir / ".migration-v2.json").read_text(encoding="utf-8")
    )
    assert marker["state"] == "complete"
    assert marker["files"]
    assert all(item["sha256"] for item in marker["files"])
    assert marker["migrated_camera_ids"] == ["legacy-camera"]

    if target_name == "cameras.json":
        general.registry.path.unlink()
    else:
        (general.results_dir / target_name).unlink()

    with pytest.raises(RuntimeError, match="完整性"):
        _migrate(manager, source)


def test_completed_migration_allows_camera_create_and_update(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    assert _migrate(manager, source) is True
    general = manager.get("general_electric")

    created = general.registry.create("新增摄像头", "rtsp://new-camera/stream")
    general.registry.update(
        "legacy-camera",
        name="迁入摄像头已改名",
        rtsp_url="rtsp://legacy-camera/new-stream",
    )

    assert _migrate(manager, source) is False
    assert general.registry.get(created["camera_id"]) is not None
    assert general.registry.get("legacy-camera")["name"] == "迁入摄像头已改名"


def test_completed_migration_allows_worker_json_updates(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    assert _migrate(manager, source) is True
    general = manager.get("general_electric")
    _write_json(
        general.results_dir / "vlm_history.json",
        {"items": [{"camera_id": "legacy-camera", "result": "updated"}]},
    )
    _write_json(
        general.results_dir / "vlm_latest_stats.json",
        {"total": 42, "updated": True},
    )

    assert _migrate(manager, source) is False


def test_completed_migration_rejects_empty_active_registry(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    assert _migrate(manager, source) is True
    general = manager.get("general_electric")
    general.registry.delete("legacy-camera")

    with pytest.raises(RuntimeError, match="完整性"):
        _migrate(manager, source)


def test_completed_migration_allows_roi_removal_and_camera_archive(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    assert _migrate(manager, source) is True
    general = manager.get("general_electric")
    (general.roi_dir / "legacy-camera_staff_rois.json").unlink()
    general.registry.delete("legacy-camera")
    archived_camera = general.archive_dir / "legacy-camera"
    _write_json(archived_camera / "camera.json", {"camera_id": "legacy-camera"})

    assert _migrate(manager, source) is False


def test_completed_marker_never_recreates_missing_registry(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    assert _migrate(manager, source) is True
    general = manager.get("general_electric")
    general.registry.create("后来新增", "rtsp://later-camera/stream")
    general.registry.delete("legacy-camera")
    _write_json(
        general.archive_dir / "legacy-camera" / "camera.json",
        {"camera_id": "legacy-camera"},
    )
    general.registry.path.unlink()

    with pytest.raises(RuntimeError, match="cameras.json.*缺失"):
        _migrate(manager, source)
    assert not general.registry.path.exists()


def test_completed_migration_survives_volatile_runtime_cleanup(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    assert _migrate(manager, source) is True
    general = manager.get("general_electric")
    (general.runtime_dir / "frame_meta.json").write_text("{}", encoding="utf-8")
    shutil.rmtree(general.runtime_dir)

    assert _migrate(manager, source) is False
    restored = manager.get("general_electric")
    assert restored.runtime_dir.is_dir()
    assert not (restored.runtime_dir / "frame_meta.json").exists()
    assert (restored.results_dir / "vlm_history.json").is_file()


def test_migration_and_other_registry_create_do_not_overwrite_each_other(
    tmp_path,
    monkeypatch,
):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    workspace = manager.get("general_electric")
    other_registry = camera_registry.CameraRegistry(
        workspace.registry.path,
        department="general_electric",
    )
    replace_started = threading.Event()
    allow_replace = threading.Event()
    original_replace = department_workspace._replace_staged_file

    def pause_registry_replace(staged_path, target):
        if target == workspace.registry.path:
            replace_started.set()
            assert allow_replace.wait(timeout=5)
        return original_replace(staged_path, target)

    monkeypatch.setattr(
        department_workspace,
        "_replace_staged_file",
        pause_registry_replace,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        migration_future = executor.submit(_migrate, manager, source)
        assert replace_started.wait(timeout=5)
        create_future = executor.submit(
            other_registry.create,
            "并发新增",
            "rtsp://concurrent-camera/stream",
        )
        time.sleep(0.05)
        allow_replace.set()
        assert migration_future.result(timeout=5) is True
        created = create_future.result(timeout=5)

    assert workspace.registry.get(created["camera_id"]) is not None
    assert {camera["name"] for camera in workspace.registry.list()} == {
        "旧摄像头",
        "并发新增",
    }


def test_two_processes_migrate_only_once(tmp_path):
    data_root = tmp_path / "data"
    runtime_root = tmp_path / "runtime"
    source = _migration_source(tmp_path)
    context = multiprocessing.get_context("fork")
    start_event = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_process_migrate,
            args=(
                data_root,
                runtime_root,
                source,
                start_event,
                results,
            ),
        )
        for _index in range(2)
    ]
    for process in processes:
        process.start()
    start_event.set()
    outcomes = [results.get(timeout=10) for _index in range(2)]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert sorted(outcomes) == [("ok", False), ("ok", True)]
    manager = DepartmentWorkspaceManager(data_root, runtime_root)
    assert len(manager.get("general_electric").registry.list()) == 1


def test_marker_rejects_non_string_camera_id_with_runtime_error(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    assert _migrate(manager, source) is True
    general = manager.get("general_electric")
    marker_path = general.data_dir / ".migration-v2.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["migrated_camera_ids"] = [{"bad": True}]
    _write_json(marker_path, marker)

    with pytest.raises(RuntimeError, match="camera_id"):
        _migrate(manager, source)


@pytest.mark.parametrize("invalid_scope", [[], {}])
def test_marker_rejects_non_string_manifest_scope_with_runtime_error(
    tmp_path,
    invalid_scope,
):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    assert _migrate(manager, source) is True
    general = manager.get("general_electric")
    marker_path = general.data_dir / ".migration-v2.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["files"][0]["scope"] = invalid_scope
    _write_json(marker_path, marker)

    with pytest.raises(RuntimeError, match="scope"):
        _migrate(manager, source)


@pytest.mark.parametrize("failure_index", range(6))
def test_migration_resumes_after_each_target_replace_failure(
    tmp_path,
    monkeypatch,
    failure_index,
):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    original_replace = department_workspace._replace_staged_file
    call_count = 0

    def fail_once(staged_path, target):
        nonlocal call_count
        current = call_count
        call_count += 1
        if current == failure_index:
            raise OSError(f"injected replace failure {failure_index}")
        return original_replace(staged_path, target)

    monkeypatch.setattr(
        department_workspace,
        "_replace_staged_file",
        fail_once,
    )
    with pytest.raises(OSError, match="injected"):
        _migrate(manager, source)

    general = manager.get("general_electric")
    journal = general.data_dir / ".migration-v2.in-progress.json"
    assert journal.is_file()
    assert not (general.data_dir / ".migration-v2.json").exists()

    monkeypatch.setattr(
        department_workspace,
        "_replace_staged_file",
        original_replace,
    )
    assert _migrate(manager, source) is True
    assert _migrate(manager, source) is False
    assert not journal.exists()
    assert len(general.registry.list()) == 1
    assert source[0].exists()


def test_migration_resumes_after_complete_marker_write_failure(
    tmp_path,
    monkeypatch,
):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    original_write_marker = department_workspace._write_complete_marker

    def fail_marker(*args, **kwargs):
        raise OSError("injected marker failure")

    monkeypatch.setattr(
        department_workspace,
        "_write_complete_marker",
        fail_marker,
    )
    with pytest.raises(OSError, match="marker"):
        _migrate(manager, source)

    general = manager.get("general_electric")
    journal = general.data_dir / ".migration-v2.in-progress.json"
    assert journal.is_file()
    assert not (general.data_dir / ".migration-v2.json").exists()

    monkeypatch.setattr(
        department_workspace,
        "_write_complete_marker",
        original_write_marker,
    )
    assert _migrate(manager, source) is True
    assert _migrate(manager, source) is False
    assert not journal.exists()
    assert len(general.registry.list()) == 1
    assert source[0].exists()


def test_corrupt_general_registry_does_not_break_other_department(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    general = manager.get("general_electric")
    electronics = manager.get("electronics_electrician")
    general.registry.path.write_text("{broken", encoding="utf-8")

    with pytest.raises(RuntimeError, match="读取失败"):
        general.registry.list()

    created = electronics.registry.create(
        "电子电工一号",
        "rtsp://electronics-camera/stream",
    )
    assert electronics.registry.get(created["camera_id"]) == created


def test_each_workspace_has_an_independent_four_camera_limit(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    general = manager.get("general_electric")
    components = manager.get("electrical_components")

    for index in range(4):
        general.registry.create(
            f"通用电气 {index}",
            f"rtsp://general-{index}/stream",
        )
        components.registry.create(
            f"电气元件 {index}",
            f"rtsp://components-{index}/stream",
        )

    with pytest.raises(ValueError, match="4"):
        general.registry.create("通用电气 5", "rtsp://general-5/stream")
    with pytest.raises(ValueError, match="4"):
        components.registry.create("电气元件 5", "rtsp://components-5/stream")

    assert len(general.registry.list()) == 4
    assert len(components.registry.list()) == 4
