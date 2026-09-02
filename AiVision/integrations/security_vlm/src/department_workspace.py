# 文件说明：实现部门相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""安检事业部隔离工作区及旧全局数据迁移。"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from AiVision.integrations.security_vlm.src.camera_registry import CameraRegistry
from AiVision.integrations.security_vlm.src.departments import require_department
from AiVision.integrations.security_vlm.src.frame_hub import ResultStore


GENERAL_ELECTRIC = "general_electric"
MIGRATION_MARKER = ".migration-v2.json"
MIGRATION_JOURNAL = ".migration-v2.in-progress.json"
MIGRATION_LOCK = ".migration-v2.lock"
PERSISTENT_RESULT_FILES = (
    "vlm_state.json",
    "vlm_history.json",
    "vlm_latest_stats.json",
    "vlm_budget.json",
)


# 功能：单个安检事业部的持久数据和运行时路径；输入与输出详见下方说明
# 参数：
#   - `department`（str）：业务部门名称或标识
#   - `data_dir`（Path）：`data_dir` 对应的业务输入值
#   - `runtime_dir`（Path）：`runtime_dir` 对应的业务输入值
#   - `registry`（CameraRegistry）：`registry` 对应的业务输入值
#   - `roi_dir`（Path）：`roi_dir` 对应的业务输入值
#   - `camera_runtime_dir`（Path）：`camera_runtime_dir` 对应的业务输入值
#   - `archive_dir`（Path）：`archive_dir` 对应的业务输入值
#   - `results_dir`（Path）：`results_dir` 对应的业务输入值
#   - `result_store`（ResultStore）：`result_store` 对应的业务输入值
# 返回：DepartmentWorkspace；返回新建的 `DepartmentWorkspace` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `DepartmentWorkspaceManager::get` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class DepartmentWorkspace:
    """单个安检事业部的持久数据和运行时路径。"""

    department: str
    data_dir: Path
    runtime_dir: Path
    registry: CameraRegistry
    roi_dir: Path
    camera_runtime_dir: Path
    archive_dir: Path
    results_dir: Path
    result_store: ResultStore


# 功能：按白名单创建互不重合的事业部工作区；输入与输出详见下方说明
# 参数：
#   - `data_root`（Path）：`data_root` 对应的业务输入值
#   - `runtime_root`（Path）：`runtime_root` 对应的业务输入值
# 返回：DepartmentWorkspaceManager；返回新建的 `DepartmentWorkspaceManager` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的 `_process_migrate`
#         实例化本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_manager_creates_four_isolated_empty_workspaces`
#         实例化本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_legacy_data_migrates_only_to_general_electric_and_is_idempotent`
#         实例化本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
#         `test_migration_copies_only_rois_for_registered_cameras` 实例化本符号；另有 17 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DepartmentWorkspaceManager:
    """按白名单创建互不重合的事业部工作区。"""

    # 功能：初始化或配置 `__init__` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `data_root`（Path）：`data_root` 对应的业务输入值
    #   - `runtime_root`（Path）：`runtime_root` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path(data_root).resolve`、`Path`、`Path(runtime_root).resolve`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, data_root: Path, runtime_root: Path):
        self.data_root = Path(data_root).resolve()
        self.runtime_root = Path(runtime_root).resolve()

    # 功能：读取或查询 `get` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：DepartmentWorkspace；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_department`、`path.mkdir`、`CameraRegistry`、`marker_path.exists`、`registry.path.is_file`、`RuntimeError`、`registry.initialize`、`DepartmentWorkspace`、`ResultStore`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
    def get(self, department: str) -> DepartmentWorkspace:
        department = require_department(department)
        data_dir = self.data_root / department
        runtime_dir = self.runtime_root / department
        roi_dir = data_dir / "rois"
        camera_runtime_dir = runtime_dir / "cameras"
        archive_dir = data_dir / "archive"
        results_dir = data_dir / "results"
        for path in (
            data_dir,
            runtime_dir,
            roi_dir,
            camera_runtime_dir,
            archive_dir,
            results_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        registry = CameraRegistry(
            data_dir / "cameras.json",
            department=department,
        )
        marker_path = data_dir / MIGRATION_MARKER
        if marker_path.exists() and not registry.path.is_file():
            raise RuntimeError(
                f"事业部迁移完整性校验失败: cameras.json 缺失 ({department})"
            )
        registry.initialize()
        return DepartmentWorkspace(
            department=department,
            data_dir=data_dir,
            runtime_dir=runtime_dir,
            registry=registry,
            roi_dir=roi_dir,
            camera_runtime_dir=camera_runtime_dir,
            archive_dir=archive_dir,
            results_dir=results_dir,
            result_store=ResultStore(results_dir),
        )

    # 功能：实现 `migrate_general_electric` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `legacy_registry_path`（Path）：`legacy_registry_path` 对应的业务输入值
    #   - `legacy_roi_dir`（Path）：`legacy_roi_dir` 对应的业务输入值
    #   - `legacy_runtime_dir`（Path）：`legacy_runtime_dir` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`migrate_general_electric`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def migrate_general_electric(
        self,
        *,
        legacy_registry_path: Path,
        legacy_roi_dir: Path,
        legacy_runtime_dir: Path,
    ) -> bool:
        return migrate_general_electric(
            self,
            legacy_registry_path=legacy_registry_path,
            legacy_roi_dir=legacy_roi_dir,
            legacy_runtime_dir=legacy_runtime_dir,
        )


# 功能：把旧全局持久数据一次性迁移到通用电气工作区；输入与输出详见下方说明
# 参数：
#   - `manager`（DepartmentWorkspaceManager）：`manager` 对应的业务输入值
#   - `legacy_registry_path`（Path）：`legacy_registry_path` 对应的业务输入值
#   - `legacy_roi_dir`（Path）：`legacy_roi_dir` 对应的业务输入值
#   - `legacy_runtime_dir`（Path）：`legacy_runtime_dir` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`data_dir.mkdir`、`_migration_lock`、`manager.get`、`workspace.registry.lock`、`_migrate_general_electric_locked`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def migrate_general_electric(
    manager: DepartmentWorkspaceManager,
    *,
    legacy_registry_path: Path,
    legacy_roi_dir: Path,
    legacy_runtime_dir: Path,
) -> bool:
    """把旧全局持久数据一次性迁移到通用电气工作区。"""
    data_dir = manager.data_root / GENERAL_ELECTRIC
    data_dir.mkdir(parents=True, exist_ok=True)
    with _migration_lock(data_dir):
        workspace = manager.get(GENERAL_ELECTRIC)
        with workspace.registry.lock(exclusive=True):
            return _migrate_general_electric_locked(
                workspace,
                legacy_registry_path=legacy_registry_path,
                legacy_roi_dir=legacy_roi_dir,
                legacy_runtime_dir=legacy_runtime_dir,
            )


# 功能：实现 `_migrate_general_electric_locked` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `workspace`（DepartmentWorkspace）：`workspace` 对应的业务输入值
#   - `legacy_registry_path`（Path）：`legacy_registry_path` 对应的业务输入值
#   - `legacy_roi_dir`（Path）：`legacy_roi_dir` 对应的业务输入值
#   - `legacy_runtime_dir`（Path）：`legacy_runtime_dir` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `migrate_general_electric` 调用本符号
#   - 内部调用：`marker_path.exists`、`_validate_completed_migration`、`journal_path.unlink`、`journal_path.exists`、`workspace.registry._read_unlocked`、`RuntimeError`、`_load_legacy_cameras`、`Path`、`_require_legacy_camera_id`、`_stage_validated_registry`
#          等共 21 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
def _migrate_general_electric_locked(
    workspace: DepartmentWorkspace,
    *,
    legacy_registry_path: Path,
    legacy_roi_dir: Path,
    legacy_runtime_dir: Path,
) -> bool:
    marker_path = workspace.data_dir / MIGRATION_MARKER
    journal_path = workspace.data_dir / MIGRATION_JOURNAL
    if marker_path.exists():
        _validate_completed_migration(marker_path, workspace)
        journal_path.unlink(missing_ok=True)
        return False

    if (
        not journal_path.exists()
        and workspace.registry._read_unlocked()["cameras"]
    ):
        raise RuntimeError("通用电气目标注册表非空，拒绝覆盖未标记数据")

    cameras = _load_legacy_cameras(Path(legacy_registry_path))
    registry_payload = {
        "version": CameraRegistry.VERSION,
        "department": GENERAL_ELECTRIC,
        "cameras": cameras,
    }
    migrated_camera_ids = [
        _require_legacy_camera_id(camera)
        for camera in cameras
    ]
    staged_files: list[tuple[Path, Path, dict]] = []
    try:
        registry_target = workspace.registry.path
        registry_staged = _stage_validated_registry(
            registry_payload,
            registry_target,
        )
        staged_files.append(
            (
                registry_staged,
                registry_target,
                _manifest_entry(
                    registry_staged,
                    scope="data",
                    relative_path="cameras.json",
                ),
            )
        )

        legacy_roi_dir = Path(legacy_roi_dir)
        for camera_id in migrated_camera_ids:
            roi_name = f"{camera_id}_staff_rois.json"
            source = legacy_roi_dir / roi_name
            if source.is_file():
                target = workspace.roi_dir / roi_name
                staged = _stage_json_copy(source, target)
                staged_files.append(
                    (
                        staged,
                        target,
                        _manifest_entry(
                            staged,
                            scope="data",
                            relative_path=f"rois/{roi_name}",
                        ),
                    )
                )

        legacy_runtime_dir = Path(legacy_runtime_dir)
        for name in PERSISTENT_RESULT_FILES:
            source = legacy_runtime_dir / name
            if source.is_file():
                target = workspace.results_dir / name
                staged = _stage_json_copy(source, target)
                staged_files.append(
                    (
                        staged,
                        target,
                        _manifest_entry(
                            staged,
                            scope="results",
                            relative_path=name,
                        ),
                    )
                )

        manifest = [entry for _staged, _target, entry in staged_files]
        journal = _migration_record(
            "in_progress",
            manifest,
            migrated_camera_ids,
        )
        if journal_path.exists():
            existing_journal = _read_migration_record(
                journal_path,
                expected_state="in_progress",
            )
            if (
                existing_journal["files"] != manifest
                or existing_journal["migrated_camera_ids"]
                != migrated_camera_ids
            ):
                raise RuntimeError("事业部迁移 journal 与当前源文件不一致")
        else:
            _write_json_atomically(journal_path, journal, mode=0o600)

        for temp_path, target, _entry in staged_files:
            _replace_staged_file(temp_path, target)

        _validate_manifest_targets(manifest, workspace)
        _write_complete_marker(
            marker_path,
            manifest,
            migrated_camera_ids,
        )
        journal_path.unlink(missing_ok=True)
    finally:
        for temp_path, _target, _entry in staged_files:
            temp_path.unlink(missing_ok=True)
    return True


# 功能：读取或查询 `_load_legacy_cameras` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
# 返回：list[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked` 调用本符号
#   - 内部调用：`json.loads`、`path.read_text`、`RuntimeError`、`isinstance`、`payload.get`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _load_legacy_cameras(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"旧摄像头注册表读取失败: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("cameras"), list):
        raise RuntimeError("旧摄像头注册表格式无效")
    version = payload.get("version")
    if version == 2 and payload.get("department") != GENERAL_ELECTRIC:
        raise RuntimeError("旧摄像头注册表事业部不是通用电气")
    if version not in {1, 2}:
        raise RuntimeError("旧摄像头注册表格式无效")
    return payload["cameras"]


# 功能：实现 `_require_legacy_camera_id` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `camera`（dict）：摄像头配置或实体
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked` 调用本符号
#   - 内部调用：`CameraRegistry.validate_camera_id`、`camera.get`、`isinstance`、`RuntimeError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _require_legacy_camera_id(camera: dict) -> str:
    try:
        return CameraRegistry.validate_camera_id(camera.get("camera_id"))
    except (AttributeError, ValueError) as exc:
        camera_id = camera.get("camera_id") if isinstance(camera, dict) else None
        raise RuntimeError(f"旧摄像头 camera_id 无效: {camera_id!r}") from exc


# 功能：实现 `_stage_validated_registry` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（dict）：接口或事件携带的业务数据
#   - `target`（Path）：`target` 对应的业务输入值
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked` 调用本符号
#   - 内部调用：`Path`、`target.parent.mkdir`、`_temp_sibling`、`temp_path.write_text`、`json.dumps`、`os.chmod`、`CameraRegistry`、`registry._read_unlocked`、`temp_path.unlink`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
def _stage_validated_registry(payload: dict, target: Path) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_sibling(target)
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.chmod(temp_path, 0o600)
        registry = CameraRegistry(
            temp_path,
            department=GENERAL_ELECTRIC,
        )
        registry._read_unlocked()
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


# 功能：实现 `_stage_json_copy` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `source`（Path）：`source` 对应的业务输入值
#   - `target`（Path）：`target` 对应的业务输入值
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked` 调用本符号
#   - 内部调用：`Path`、`target.parent.mkdir`、`_temp_sibling`、`shutil.copy2`、`json.loads`、`temp_path.read_text`、`temp_path.unlink`、`RuntimeError`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
def _stage_json_copy(source: Path, target: Path) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_sibling(target)
    try:
        shutil.copy2(source, temp_path)
        json.loads(temp_path.read_text(encoding="utf-8"))
        return temp_path
    except (OSError, json.JSONDecodeError) as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"迁移 JSON 文件失败 {source}: {exc}") from exc


# 功能：更新或保存 `_write_json_atomically` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `target`（Path）：`target` 对应的业务输入值
#   - `payload`（dict）：接口或事件携带的业务数据
#   - `mode`（int | None）：`mode` 对应的业务输入值；默认值为 `None`
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked`
#         调用本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_write_complete_marker` 调用本符号
#   - 内部调用：`Path`、`target.parent.mkdir`、`_temp_sibling`、`temp_path.write_text`、`json.dumps`、`json.loads`、`temp_path.read_text`、`os.chmod`、`temp_path.replace`、`temp_path.unlink`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _write_json_atomically(
    target: Path,
    payload: dict,
    *,
    mode: int | None = None,
) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_sibling(target)
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        json.loads(temp_path.read_text(encoding="utf-8"))
        if mode is not None:
            os.chmod(temp_path, mode)
        temp_path.replace(target)
    finally:
        temp_path.unlink(missing_ok=True)


# 功能：实现 `_manifest_entry` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
#   - `scope`（str）：`scope` 对应的业务输入值
#   - `relative_path`（str）：`relative_path` 对应的业务输入值
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked` 调用本符号
#   - 内部调用：`_sha256`、`path.stat`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _manifest_entry(
    path: Path,
    *,
    scope: str,
    relative_path: str,
) -> dict:
    return {
        "scope": scope,
        "path": relative_path,
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


# 功能：实现 `_migration_record` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `state`（str）：`state` 对应的业务输入值
#   - `manifest`（list[dict]）：`manifest` 对应的业务输入值
#   - `migrated_camera_ids`（list[str]）：`migrated_camera_ids` 对应的业务输入值
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked`
#         调用本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_write_complete_marker` 调用本符号
#   - 内部调用：`time.time`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _migration_record(
    state: str,
    manifest: list[dict],
    migrated_camera_ids: list[str],
) -> dict:
    timestamp_key = "completed_at" if state == "complete" else "started_at"
    return {
        "version": 2,
        "department": GENERAL_ELECTRIC,
        "state": state,
        "files": manifest,
        "migrated_camera_ids": migrated_camera_ids,
        timestamp_key: time.time(),
    }


# 功能：读取或查询 `_read_migration_record` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
#   - `expected_state`（str）：`expected_state` 对应的业务输入值
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked`
#         调用本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_validate_completed_migration` 调用本符号
#   - 内部调用：`json.loads`、`path.read_text`、`RuntimeError`、`isinstance`、`payload.get`、`_validate_manifest`、`_validate_migrated_camera_ids`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _read_migration_record(path: Path, *, expected_state: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"事业部迁移记录读取失败: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 2
        or payload.get("department") != GENERAL_ELECTRIC
        or payload.get("state") != expected_state
        or not isinstance(payload.get("files"), list)
        or not isinstance(payload.get("migrated_camera_ids"), list)
    ):
        raise RuntimeError("事业部迁移记录格式无效")
    _validate_manifest(payload["files"])
    _validate_migrated_camera_ids(payload["migrated_camera_ids"])
    return payload


# 功能：检查或判断 `_validate_completed_migration` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `marker_path`（Path）：`marker_path` 对应的业务输入值
#   - `workspace`（DepartmentWorkspace）：`workspace` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked` 调用本符号
#   - 内部调用：`_read_migration_record`、`_validate_completed_targets`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _validate_completed_migration(
    marker_path: Path,
    workspace: DepartmentWorkspace,
) -> None:
    marker = _read_migration_record(
        marker_path,
        expected_state="complete",
    )
    _validate_completed_targets(marker, workspace)


# 功能：检查或判断 `_validate_migrated_camera_ids` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `camera_ids`（list[str]）：`camera_ids` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_read_migration_record` 调用本符号
#   - 内部调用：`validated.append`、`CameraRegistry.validate_camera_id`、`RuntimeError`、`len`、`set`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _validate_migrated_camera_ids(camera_ids: list[str]) -> None:
    validated: list[str] = []
    try:
        for camera_id in camera_ids:
            validated.append(CameraRegistry.validate_camera_id(camera_id))
    except ValueError as exc:
        raise RuntimeError("事业部迁移记录 camera_id 无效") from exc
    if len(validated) != len(set(validated)):
        raise RuntimeError("事业部迁移记录 camera_id 重复")


# 功能：检查或判断 `_validate_completed_targets` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `marker`（dict）：`marker` 对应的业务输入值
#   - `workspace`（DepartmentWorkspace）：`workspace` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_validate_completed_migration` 调用本符号
#   - 内部调用：`_validate_manifest`、`workspace.registry._read_unlocked`、`RuntimeError`、`archive_path.is_dir`、`_manifest_target`、`target.is_file`、`json.loads`、`target.read_text`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _validate_completed_targets(
    marker: dict,
    workspace: DepartmentWorkspace,
) -> None:
    manifest = marker["files"]
    _validate_manifest(manifest)
    try:
        active_camera_ids = {
            camera["camera_id"]
            for camera in workspace.registry._read_unlocked()["cameras"]
        }
    except (KeyError, RuntimeError) as exc:
        raise RuntimeError("事业部迁移完整性校验失败: cameras.json") from exc

    for camera_id in marker["migrated_camera_ids"]:
        archive_path = workspace.archive_dir / camera_id
        if camera_id not in active_camera_ids and not archive_path.is_dir():
            raise RuntimeError(
                f"事业部迁移完整性校验失败: camera_id {camera_id}"
            )

    for entry in manifest:
        if entry["scope"] != "results":
            continue
        target = _manifest_target(entry, workspace)
        if not target.is_file():
            raise RuntimeError(
                f"事业部迁移完整性校验失败: results:{entry['path']}"
            )
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"事业部迁移完整性校验失败: results:{entry['path']}"
            ) from exc


# 功能：检查或判断 `_validate_manifest` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `manifest`（list[dict]）：`manifest` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_read_migration_record`
#         调用本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_validate_completed_targets`
#         调用本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_validate_manifest_targets` 调用本符号
#   - 内部调用：`set`、`isinstance`、`RuntimeError`、`entry.get`、`len`、`type`、`PurePosixPath`、`relative.is_absolute`、`relative.as_posix`、`_is_allowed_manifest_target`
#          等共 11 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _validate_manifest(manifest: list[dict]) -> None:
    seen: set[tuple[str, str]] = set()
    has_registry = False
    for entry in manifest:
        if not isinstance(entry, dict):
            raise RuntimeError("事业部迁移记录格式无效")
        scope = entry.get("scope")
        relative_path = entry.get("path")
        digest = entry.get("sha256")
        size = entry.get("size")
        if not isinstance(scope, str) or scope not in {"data", "results"}:
            raise RuntimeError("事业部迁移记录格式无效: scope 无效")
        if not isinstance(relative_path, str):
            raise RuntimeError("事业部迁移记录格式无效: path 必须是字符串")
        if not isinstance(digest, str) or len(digest) != 64:
            raise RuntimeError("事业部迁移记录格式无效: sha256 无效")
        if type(size) is not int or size < 0:
            raise RuntimeError("事业部迁移记录格式无效: size 无效")
        relative = PurePosixPath(relative_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative_path != relative.as_posix()
        ):
            raise RuntimeError("事业部迁移记录路径无效")
        key = (scope, relative_path)
        if key in seen or not _is_allowed_manifest_target(scope, relative_path):
            raise RuntimeError("事业部迁移记录路径无效")
        seen.add(key)
        has_registry = has_registry or key == ("data", "cameras.json")
    if not has_registry:
        raise RuntimeError("事业部迁移记录完整性无效: 缺少 cameras.json")


# 功能：检查或判断 `_is_allowed_manifest_target` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `scope`（str）：`scope` 对应的业务输入值
#   - `relative_path`（str）：`relative_path` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_validate_manifest` 调用本符号
#   - 内部调用：`PurePosixPath`、`len`、`relative.name.endswith`、`CameraRegistry.validate_camera_id`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _is_allowed_manifest_target(scope: str, relative_path: str) -> bool:
    if scope == "results":
        return relative_path in PERSISTENT_RESULT_FILES
    if relative_path == "cameras.json":
        return True
    relative = PurePosixPath(relative_path)
    if len(relative.parts) != 2 or relative.parts[0] != "rois":
        return False
    suffix = "_staff_rois.json"
    if not relative.name.endswith(suffix):
        return False
    camera_id = relative.name[:-len(suffix)]
    try:
        CameraRegistry.validate_camera_id(camera_id)
    except ValueError:
        return False
    return True


# 功能：检查或判断 `_validate_manifest_targets` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `manifest`（list[dict]）：`manifest` 对应的业务输入值
#   - `workspace`（DepartmentWorkspace）：`workspace` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked` 调用本符号
#   - 内部调用：`_validate_manifest`、`_manifest_target`、`target.is_file`、`target.stat`、`_sha256`、`RuntimeError`、`workspace.registry._read_unlocked`、`json.loads`、`target.read_text`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _validate_manifest_targets(
    manifest: list[dict],
    workspace: DepartmentWorkspace,
) -> None:
    _validate_manifest(manifest)
    for entry in manifest:
        target = _manifest_target(entry, workspace)
        if (
            not target.is_file()
            or target.stat().st_size != entry["size"]
            or _sha256(target) != entry["sha256"]
        ):
            raise RuntimeError(
                f"事业部迁移完整性校验失败: {entry['scope']}:{entry['path']}"
            )
        try:
            if entry["scope"] == "data" and entry["path"] == "cameras.json":
                workspace.registry._read_unlocked()
            else:
                json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            raise RuntimeError(
                f"事业部迁移完整性校验失败: {entry['scope']}:{entry['path']}"
            ) from exc


# 功能：实现 `_manifest_target` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `entry`（dict）：`entry` 对应的业务输入值
#   - `workspace`（DepartmentWorkspace）：`workspace` 对应的业务输入值
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_validate_completed_targets`
#         调用本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_validate_manifest_targets` 调用本符号
#   - 内部调用：`root.joinpath`、`PurePosixPath`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def _manifest_target(entry: dict, workspace: DepartmentWorkspace) -> Path:
    root = workspace.data_dir if entry["scope"] == "data" else workspace.results_dir
    return root.joinpath(*PurePosixPath(entry["path"]).parts)


# 功能：实现 `_replace_staged_file` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `staged_path`（Path）：`staged_path` 对应的业务输入值
#   - `target`（Path）：`target` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked` 调用本符号
#   - 内部调用：`staged_path.replace`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _replace_staged_file(staged_path: Path, target: Path) -> None:
    staged_path.replace(target)


# 功能：更新或保存 `_write_complete_marker` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `marker_path`（Path）：`marker_path` 对应的业务输入值
#   - `manifest`（list[dict]）：`manifest` 对应的业务输入值
#   - `migrated_camera_ids`（list[str]）：`migrated_camera_ids` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_migrate_general_electric_locked` 调用本符号
#   - 内部调用：`_write_json_atomically`、`_migration_record`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _write_complete_marker(
    marker_path: Path,
    manifest: list[dict],
    migrated_camera_ids: list[str],
) -> None:
    _write_json_atomically(
        marker_path,
        _migration_record(
            "complete",
            manifest,
            migrated_camera_ids,
        ),
        mode=0o600,
    )


# 功能：实现 `_sha256` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_manifest_entry`
#         调用本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_validate_manifest_targets` 调用本符号
#   - 内部调用：`hashlib.sha256`、`path.open`、`iter`、`source.read`、`digest.update`、`digest.hexdigest`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 功能：实现 `_migration_lock` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `data_dir`（Path）：`data_dir` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `migrate_general_electric` 调用本符号
#   - 内部调用：`Path`、`os.open`、`os.fchmod`、`fcntl.flock`、`os.close`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
@contextmanager
def _migration_lock(data_dir: Path):
    lock_path = Path(data_dir) / MIGRATION_LOCK
    descriptor = os.open(
        lock_path,
        os.O_CREAT | os.O_RDWR,
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


# 功能：实现 `_temp_sibling` 对应的部门逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `target`（Path）：`target` 对应的业务输入值
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_stage_validated_registry`
#         调用本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_stage_json_copy`
#         调用本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_write_json_atomically` 调用本符号
#   - 内部调用：`target.with_name`、`uuid.uuid4`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _temp_sibling(target: Path) -> Path:
    return target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
