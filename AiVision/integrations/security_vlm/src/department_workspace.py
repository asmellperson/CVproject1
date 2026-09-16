
"""安检事业部隔离工作区。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from AiVision.integrations.security_vlm.src.camera_registry import CameraRegistry
from AiVision.integrations.security_vlm.src.departments import require_department
from AiVision.integrations.security_vlm.src.frame_hub import ResultStore


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


class DepartmentWorkspaceManager:
    """按正式目录创建互不重合的事业部工作区。"""

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
