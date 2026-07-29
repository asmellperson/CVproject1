import json

import pytest

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

    for workspace in workspaces:
        assert workspace.department in SECURITY_DEPARTMENTS
        assert workspace.data_dir.is_dir()
        assert workspace.runtime_dir.is_dir()
        assert workspace.roi_dir.is_dir()
        assert workspace.camera_runtime_dir.is_dir()
        assert workspace.archive_dir.is_dir()
        assert workspace.registry.path.is_file()
        assert workspace.registry.list() == []
        assert workspace.result_store.runtime_dir == workspace.runtime_dir
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
        assert json.loads((general.runtime_dir / name).read_text(encoding="utf-8")) == {
            "source": name
        }
    assert not (general.runtime_dir / "frame_meta.json").exists()
    assert not (general.runtime_dir / "capture_status.json").exists()
    assert not (general.runtime_dir / "vlm_status.json").exists()
    assert not (general.runtime_dir / "session_pending.json").exists()

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
    assert not (general.runtime_dir / "vlm_history.json").exists()


@pytest.mark.parametrize(
    "target_name",
    ["cameras.json", "vlm_history.json"],
)
def test_completed_marker_rejects_missing_or_changed_target(tmp_path, target_name):
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

    if target_name == "cameras.json":
        general.registry.path.unlink()
    else:
        _write_json(general.runtime_dir / target_name, {"tampered": True})

    with pytest.raises(RuntimeError, match="完整性"):
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
