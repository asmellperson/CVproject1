"""事业部工作区正式契约，不在运行时迁移旧全局数据。"""
import json
import pytest

from AiVision.integrations.security_vlm.src.department_workspace import DepartmentWorkspaceManager
from AiVision.integrations.security_vlm.src.departments import DEPARTMENTS, require_department


def test_requires_known_non_empty_department():
    for department in DEPARTMENTS:
        assert require_department(department) == department

    with pytest.raises(ValueError, match="department"):
        require_department("")
    with pytest.raises(ValueError, match="department"):
        require_department("unknown")


def test_manager_creates_all_registered_isolated_empty_workspaces(tmp_path):
    manager = DepartmentWorkspaceManager(
        tmp_path / "data",
        tmp_path / "runtime",
    )

    workspaces = [manager.get(department) for department in DEPARTMENTS]

    assert len({workspace.data_dir for workspace in workspaces}) == len(DEPARTMENTS)
    assert len({workspace.runtime_dir for workspace in workspaces}) == len(DEPARTMENTS)
    assert len({workspace.registry.path for workspace in workspaces}) == len(DEPARTMENTS)
    assert len({workspace.roi_dir for workspace in workspaces}) == len(DEPARTMENTS)
    assert len({workspace.camera_runtime_dir for workspace in workspaces}) == len(DEPARTMENTS)
    assert len({workspace.archive_dir for workspace in workspaces}) == len(DEPARTMENTS)
    assert len({workspace.results_dir for workspace in workspaces}) == len(DEPARTMENTS)

    for workspace in workspaces:
        assert workspace.department in DEPARTMENTS
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
