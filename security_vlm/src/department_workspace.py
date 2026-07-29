"""安检事业部隔离工作区及旧全局数据迁移。"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from camera_registry import CameraRegistry
from departments import require_department
from frame_hub import ResultStore


GENERAL_ELECTRIC = "general_electric"
MIGRATION_MARKER = ".migration-v2.json"
PERSISTENT_RUNTIME_FILES = (
    "vlm_state.json",
    "vlm_history.json",
    "vlm_latest_stats.json",
    "vlm_budget.json",
)


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
    result_store: ResultStore


class DepartmentWorkspaceManager:
    """按白名单创建互不重合的事业部工作区。"""

    def __init__(self, data_root: Path, runtime_root: Path):
        self.data_root = Path(data_root).resolve()
        self.runtime_root = Path(runtime_root).resolve()

    def get(self, department: str) -> DepartmentWorkspace:
        department = require_department(department)
        data_dir = self.data_root / department
        runtime_dir = self.runtime_root / department
        roi_dir = data_dir / "rois"
        camera_runtime_dir = runtime_dir / "cameras"
        archive_dir = data_dir / "archive"
        for path in (
            data_dir,
            runtime_dir,
            roi_dir,
            camera_runtime_dir,
            archive_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        registry = CameraRegistry(
            data_dir / "cameras.json",
            department=department,
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
            result_store=ResultStore(runtime_dir),
        )

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


def migrate_general_electric(
    manager: DepartmentWorkspaceManager,
    *,
    legacy_registry_path: Path,
    legacy_roi_dir: Path,
    legacy_runtime_dir: Path,
) -> bool:
    """把旧全局持久数据一次性迁移到通用电气工作区。"""
    workspace = manager.get(GENERAL_ELECTRIC)
    marker_path = workspace.data_dir / MIGRATION_MARKER
    if marker_path.exists():
        _validate_migration_marker(marker_path)
        return False

    if workspace.registry.list():
        raise RuntimeError("通用电气目标注册表非空，拒绝覆盖未标记数据")

    cameras = _load_legacy_cameras(Path(legacy_registry_path))
    registry_payload = {
        "version": CameraRegistry.VERSION,
        "department": GENERAL_ELECTRIC,
        "cameras": cameras,
    }
    staged_files: list[tuple[Path, Path]] = []
    try:
        staged_files.append(
            (
                _stage_validated_registry(
                    registry_payload,
                    workspace.registry.path,
                ),
                workspace.registry.path,
            )
        )

        legacy_roi_dir = Path(legacy_roi_dir)
        for camera in cameras:
            camera_id = str(camera.get("camera_id", ""))
            roi_name = f"{camera_id}_staff_rois.json"
            if not camera_id or Path(roi_name).name != roi_name:
                raise RuntimeError(f"旧摄像头 ID 无效: {camera_id!r}")
            source = legacy_roi_dir / roi_name
            if source.is_file():
                target = workspace.roi_dir / roi_name
                staged_files.append((_stage_json_copy(source, target), target))

        legacy_runtime_dir = Path(legacy_runtime_dir)
        for name in PERSISTENT_RUNTIME_FILES:
            source = legacy_runtime_dir / name
            if source.is_file():
                target = workspace.runtime_dir / name
                staged_files.append((_stage_json_copy(source, target), target))

        for temp_path, target in staged_files:
            temp_path.replace(target)

        _write_json_atomically(
            marker_path,
            {
                "version": 2,
                "department": GENERAL_ELECTRIC,
                "completed_at": time.time(),
            },
            mode=0o600,
        )
    finally:
        for temp_path, _target in staged_files:
            temp_path.unlink(missing_ok=True)
    return True


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
        CameraRegistry(
            temp_path,
            department=GENERAL_ELECTRIC,
        ).list()
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


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


def _validate_migration_marker(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"事业部迁移标记读取失败: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 2
        or payload.get("department") != GENERAL_ELECTRIC
    ):
        raise RuntimeError("事业部迁移标记格式无效")


def _temp_sibling(target: Path) -> Path:
    return target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
