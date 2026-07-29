"""安检事业部隔离工作区及旧全局数据迁移。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from camera_registry import CameraRegistry
from departments import require_department
from frame_hub import ResultStore


GENERAL_ELECTRIC = "general_electric"
MIGRATION_MARKER = ".migration-v2.json"
MIGRATION_JOURNAL = ".migration-v2.in-progress.json"
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
    journal_path = workspace.data_dir / MIGRATION_JOURNAL
    if marker_path.exists():
        _validate_completed_migration(marker_path, workspace)
        journal_path.unlink(missing_ok=True)
        return False

    if not journal_path.exists() and workspace.registry.list():
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
        for name in PERSISTENT_RUNTIME_FILES:
            source = legacy_runtime_dir / name
            if source.is_file():
                target = workspace.runtime_dir / name
                staged = _stage_json_copy(source, target)
                staged_files.append(
                    (
                        staged,
                        target,
                        _manifest_entry(
                            staged,
                            scope="runtime",
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


def _require_legacy_camera_id(camera: dict) -> str:
    try:
        return CameraRegistry.validate_camera_id(camera.get("camera_id"))
    except (AttributeError, ValueError) as exc:
        camera_id = camera.get("camera_id") if isinstance(camera, dict) else None
        raise RuntimeError(f"旧摄像头 camera_id 无效: {camera_id!r}") from exc


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


def _validate_completed_migration(
    marker_path: Path,
    workspace: DepartmentWorkspace,
) -> None:
    marker = _read_migration_record(
        marker_path,
        expected_state="complete",
    )
    _validate_completed_targets(marker, workspace)


def _validate_migrated_camera_ids(camera_ids: list[str]) -> None:
    if len(camera_ids) != len(set(camera_ids)):
        raise RuntimeError("事业部迁移记录 camera_id 重复")
    try:
        for camera_id in camera_ids:
            CameraRegistry.validate_camera_id(camera_id)
    except ValueError as exc:
        raise RuntimeError("事业部迁移记录 camera_id 无效") from exc


def _validate_completed_targets(
    marker: dict,
    workspace: DepartmentWorkspace,
) -> None:
    manifest = marker["files"]
    _validate_manifest(manifest)
    try:
        active_camera_ids = {
            camera["camera_id"]
            for camera in workspace.registry.list()
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
        if entry["scope"] != "runtime":
            continue
        target = _manifest_target(entry, workspace)
        if not target.is_file():
            raise RuntimeError(
                f"事业部迁移完整性校验失败: runtime:{entry['path']}"
            )
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"事业部迁移完整性校验失败: runtime:{entry['path']}"
            ) from exc


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
        if (
            scope not in {"data", "runtime"}
            or not isinstance(relative_path, str)
            or not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(size, int)
            or size < 0
        ):
            raise RuntimeError("事业部迁移记录格式无效")
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


def _is_allowed_manifest_target(scope: str, relative_path: str) -> bool:
    if scope == "runtime":
        return relative_path in PERSISTENT_RUNTIME_FILES
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
                CameraRegistry(
                    target,
                    department=GENERAL_ELECTRIC,
                ).list()
            else:
                json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            raise RuntimeError(
                f"事业部迁移完整性校验失败: {entry['scope']}:{entry['path']}"
            ) from exc


def _manifest_target(entry: dict, workspace: DepartmentWorkspace) -> Path:
    root = workspace.data_dir if entry["scope"] == "data" else workspace.runtime_dir
    return root.joinpath(*PurePosixPath(entry["path"]).parts)


def _replace_staged_file(staged_path: Path, target: Path) -> None:
    staged_path.replace(target)


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _temp_sibling(target: Path) -> Path:
    return target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
