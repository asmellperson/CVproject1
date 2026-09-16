# 文件说明：包含部门的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import json
import multiprocessing
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from AiVision.integrations.security_vlm.src import camera_registry
from AiVision.integrations.security_vlm.src import department_workspace
from AiVision.integrations.security_vlm.src.department_workspace import (
    DepartmentWorkspaceManager,
    migrate_general_electric,
)
from AiVision.integrations.security_vlm.src.departments import DEPARTMENTS, require_department


# 功能：更新或保存 `_write_json` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（未显式标注）：目标路径
#   - `payload`（未显式标注）：接口或事件携带的业务数据
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的 `_migration_source`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_legacy_data_migrates_only_to_general_electric_and_is_idempotent`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_migration_copies_only_rois_for_registered_cameras`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_migration_validates_all_json_before_replacing_targets` 调用本符号；另有 5 处静态调用
#   - 内部调用：`path.parent.mkdir`、`path.write_text`、`json.dumps`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# 功能：实现 `_legacy_camera` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `camera_id`（未显式标注）：摄像头唯一标识；默认值为 `'legacy-camera'`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的 `_migration_source`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_legacy_data_migrates_only_to_general_electric_and_is_idempotent`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_migration_copies_only_rois_for_registered_cameras`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_migration_validates_all_json_before_replacing_targets` 调用本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _legacy_camera(camera_id="legacy-camera"):
    return {
        "camera_id": camera_id,
        "name": "旧摄像头",
        "rtsp_url": "rtsp://user:secret@legacy-camera/stream",
        "created_at": 1.0,
        "updated_at": 1.0,
    }


# 功能：实现 `_migration_source` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的 `test_completed_marker_rejects_missing_target`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_completed_migration_allows_camera_create_and_update`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_completed_migration_allows_worker_json_updates`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_completed_migration_rejects_empty_active_registry` 调用本符号；另有 9 处静态调用
#   - 内部调用：`_write_json`、`_legacy_camera`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：实现 `_migrate` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `manager`（未显式标注）：`manager` 对应的业务输入值
#   - `source`（未显式标注）：`source` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的 `_process_migrate`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_completed_marker_rejects_missing_target`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_completed_migration_allows_camera_create_and_update`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_completed_migration_allows_worker_json_updates` 调用本符号；另有 8 处静态调用
#   - 内部调用：`migrate_general_electric`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _migrate(manager, source):
    legacy_registry, legacy_roi_dir, legacy_runtime_dir = source
    return migrate_general_electric(
        manager,
        legacy_registry_path=legacy_registry,
        legacy_roi_dir=legacy_roi_dir,
        legacy_runtime_dir=legacy_runtime_dir,
    )


# 功能：处理 `_process_migrate` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `data_root`（未显式标注）：`data_root` 对应的业务输入值
#   - `runtime_root`（未显式标注）：`runtime_root` 对应的业务输入值
#   - `source`（未显式标注）：`source` 对应的业务输入值
#   - `start_event`（未显式标注）：`start_event` 对应的业务输入值
#   - `results`（未显式标注）：`results` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`start_event.wait`、`_migrate`、`results.put`、`type`、`str`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _process_migrate(
    data_root,
    runtime_root,
    source,
    start_event,
    results,
):
    original_load = department_workspace._load_legacy_cameras

    # 功能：读取或查询 `slow_load` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `path`（未显式标注）：目标路径
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`original_load`、`time.sleep`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：验证 `test_requires_known_non_empty_department` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`require_department`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_requires_known_non_empty_department():
    for department in DEPARTMENTS:
        assert require_department(department) == department

    with pytest.raises(ValueError, match="department"):
        require_department("")
    with pytest.raises(ValueError, match="department"):
        require_department("unknown")


# 功能：验证 `test_manager_creates_all_registered_isolated_empty_workspaces` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`manager.get`、`len`、`workspace.data_dir.is_dir`、`workspace.runtime_dir.is_dir`、`workspace.roi_dir.is_dir`、`workspace.camera_runtime_dir.is_dir`、`workspace.archive_dir.is_dir`、`workspace.results_dir.is_dir`、`workspace.registry.path.is_file`
#          等共 13 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：验证 `test_legacy_data_migrates_only_to_general_electric_and_is_idempotent` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_legacy_camera`、`_write_json`、`migrate_general_electric`、`manager.get`、`general.registry.list`、`json.loads`、`general.registry.path.read_text`、`(general.data_dir
#          / '.migration-v2.json').is_file`、`(general.roi_dir / 'legacy-camera_staff_rois.json').read_text` 等共 22 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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

    for department in DEPARTMENTS:
        if department != "general_electric":
            assert manager.get(department).registry.list() == []

    assert legacy_registry.exists()
    assert (legacy_roi_dir / "legacy-camera_staff_rois.json").exists()
    for name in persistent_names:
        assert (legacy_runtime_dir / name).exists()


# 功能：验证 `test_migration_copies_only_rois_for_registered_cameras` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_legacy_camera`、`_write_json`、`migrate_general_electric`、`manager.get`、`(general.roi_dir /
#          'registered_staff_rois.json').is_file`、`(general.roi_dir / 'orphan_staff_rois.json').exists`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_migration_validates_all_json_before_replacing_targets` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_write_json`、`_legacy_camera`、`legacy_runtime_dir.mkdir`、`(legacy_runtime_dir /
#          'vlm_history.json').write_text`、`pytest.raises`、`migrate_general_electric`、`manager.get`、`general.registry.list`、`(general.data_dir
#          / '.migration-v2.json').exists` 等共 11 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_completed_marker_rejects_missing_target` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `target_name`（未显式标注）：`target_name` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`_migrate`、`manager.get`、`json.loads`、`(general.data_dir /
#          '.migration-v2.json').read_text`、`all`、`general.registry.path.unlink`、`(general.results_dir /
#          target_name).unlink`、`pytest.raises` 等共 11 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_completed_migration_allows_camera_create_and_update` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`_migrate`、`manager.get`、`general.registry.create`、`general.registry.update`、`general.registry.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：验证 `test_completed_migration_allows_worker_json_updates` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`_migrate`、`manager.get`、`_write_json`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_completed_migration_rejects_empty_active_registry` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`_migrate`、`manager.get`、`general.registry.delete`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_completed_migration_rejects_empty_active_registry(tmp_path):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    assert _migrate(manager, source) is True
    general = manager.get("general_electric")
    general.registry.delete("legacy-camera")

    with pytest.raises(RuntimeError, match="完整性"):
        _migrate(manager, source)


# 功能：验证 `test_completed_migration_allows_roi_removal_and_camera_archive` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`_migrate`、`manager.get`、`(general.roi_dir /
#          'legacy-camera_staff_rois.json').unlink`、`general.registry.delete`、`_write_json`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_completed_marker_never_recreates_missing_registry` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`_migrate`、`manager.get`、`general.registry.create`、`general.registry.delete`、`_write_json`、`general.registry.path.unlink`、`pytest.raises`、`general.registry.path.exists`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_completed_migration_survives_volatile_runtime_cleanup` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`_migrate`、`manager.get`、`(general.runtime_dir /
#          'frame_meta.json').write_text`、`shutil.rmtree`、`restored.runtime_dir.is_dir`、`(restored.runtime_dir /
#          'frame_meta.json').exists`、`(restored.results_dir / 'vlm_history.json').is_file`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_migration_and_other_registry_create_do_not_overwrite_each_other` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`manager.get`、`camera_registry.CameraRegistry`、`threading.Event`、`monkeypatch.setattr`、`ThreadPoolExecutor`、`executor.submit`、`replace_started.wait`、`time.sleep`
#          等共 15 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
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

    # 功能：实现 `pause_registry_replace` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `staged_path`（未显式标注）：`staged_path` 对应的业务输入值
    #   - `target`（未显式标注）：`target` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`replace_started.set`、`allow_replace.wait`、`original_replace`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_two_processes_migrate_only_once` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_migration_source`、`multiprocessing.get_context`、`context.Event`、`context.Queue`、`context.Process`、`range`、`process.start`、`start_event.set`、`results.get`、`process.join`
#          等共 15 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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


# 功能：验证 `test_marker_rejects_non_string_camera_id_with_runtime_error` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`_migrate`、`manager.get`、`json.loads`、`marker_path.read_text`、`_write_json`、`pytest.raises`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_marker_rejects_non_string_manifest_scope_with_runtime_error` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `invalid_scope`（未显式标注）：`invalid_scope` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`_migrate`、`manager.get`、`json.loads`、`marker_path.read_text`、`_write_json`、`pytest.raises`、`pytest.mark.parametrize`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_migration_resumes_after_each_target_replace_failure` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `failure_index`（未显式标注）：`failure_index` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`monkeypatch.setattr`、`pytest.raises`、`_migrate`、`manager.get`、`journal.is_file`、`(general.data_dir
#          / '.migration-v2.json').exists`、`journal.exists`、`len` 等共 14 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：实现 `fail_once` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `staged_path`（未显式标注）：`staged_path` 对应的业务输入值
    #   - `target`（未显式标注）：`target` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`OSError`、`original_replace`。
    # 副作用/注意事项：会修改全局或闭包状态；可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
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


# 功能：验证 `test_migration_resumes_after_complete_marker_write_failure` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`_migration_source`、`monkeypatch.setattr`、`pytest.raises`、`_migrate`、`manager.get`、`journal.is_file`、`(general.data_dir
#          / '.migration-v2.json').exists`、`journal.exists`、`len` 等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_migration_resumes_after_complete_marker_write_failure(
    tmp_path,
    monkeypatch,
):
    manager = DepartmentWorkspaceManager(tmp_path / "data", tmp_path / "runtime")
    source = _migration_source(tmp_path)
    original_write_marker = department_workspace._write_complete_marker

    # 功能：实现 `fail_marker` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`OSError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：验证 `test_corrupt_general_registry_does_not_break_other_department` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`manager.get`、`general.registry.path.write_text`、`pytest.raises`、`general.registry.list`、`electronics.registry.create`、`electronics.registry.get`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_each_workspace_has_an_independent_four_camera_limit` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`DepartmentWorkspaceManager`、`manager.get`、`range`、`general.registry.create`、`components.registry.create`、`pytest.raises`、`len`、`general.registry.list`、`components.registry.list`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
