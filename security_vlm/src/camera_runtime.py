"""安检多摄像头运行目录和子进程配置快照。"""

from __future__ import annotations

import copy
import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from camera_registry import validate_camera_id
from departments import require_department

_WORKER_SCRIPTS = (
    ("capture", "capture_worker.py"),
    ("detector", "detector_worker.py"),
    ("session", "session_worker.py"),
)
_STOP_ORDER = ("session", "detector", "capture")
_RESTART_BACKOFF_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)
LOGGER = logging.getLogger(__name__)


def resolve_path(path: str | Path, project_root: Path) -> Path:
    """所有配置路径统一相对 security_vlm 项目根解析。"""
    candidate = Path(path)
    return (
        candidate.resolve()
        if candidate.is_absolute()
        else (Path(project_root) / candidate).resolve()
    )


@dataclass(frozen=True)
class CameraRuntimePaths:
    """一台摄像头独占的运行时路径。"""

    departments_root: Path
    department: str
    camera_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "departments_root", Path(self.departments_root))
        object.__setattr__(
            self,
            "department",
            require_department(self.department),
        )
        object.__setattr__(
            self,
            "camera_id",
            validate_camera_id(self.camera_id),
        )

    @property
    def department_runtime_dir(self) -> Path:
        return self.departments_root / self.department

    @property
    def runtime_dir(self) -> Path:
        return (
            self.department_runtime_dir
            / "cameras"
            / self.camera_id
        )

    @property
    def pending_dir(self) -> Path:
        return self.runtime_dir / "pending"

    @property
    def config_path(self) -> Path:
        return self.runtime_dir / "worker_config.yaml"


def build_camera_config(
    base_cfg: dict,
    camera: dict,
    paths: CameraRuntimePaths,
) -> dict:
    """从全局配置生成一台摄像头专用且互不共享引用的配置。"""
    snapshot = copy.deepcopy(base_cfg)
    data_cfg = snapshot.setdefault("data", {})
    runtime_cfg = snapshot.setdefault("runtime", {})
    session_cfg = snapshot.setdefault("session", {})

    data_cfg["department"] = paths.department
    data_cfg["input_video"] = camera["rtsp_url"]
    data_cfg["video_id"] = camera["camera_id"]
    data_cfg["camera_name"] = camera["name"]
    runtime_cfg["dir"] = str(paths.runtime_dir)
    runtime_cfg["department_dir"] = str(paths.department_runtime_dir)
    session_cfg["pending_queue_dir"] = str(paths.pending_dir)
    return snapshot


def write_camera_config(snapshot: dict, path: Path) -> None:
    """原子写入只允许文件所有者读取的 worker 配置。"""
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = config_path.with_name(f".{config_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            yaml.safe_dump(snapshot, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.chmod(temp_path, 0o600)
        temp_path.replace(config_path)
    finally:
        temp_path.unlink(missing_ok=True)


@dataclass
class CameraRuntime:
    """一台摄像头的期望状态和子进程句柄。"""

    department: str
    camera_id: str
    config_path: Path
    desired_running: bool = False
    processes: dict[str, subprocess.Popen] = field(default_factory=dict)
    restart_attempts: int = 0
    restart_at: float | None = None
    last_error: str = ""


class CameraRuntimeManager:
    """管理每摄像头 worker 进程组以及唯一的全局 VLM worker。"""

    def __init__(
        self,
        *,
        base_cfg: dict,
        project_root: Path,
        base_config_path: Path,
        camera_provider: Callable[[str], list[dict]],
        popen_factory: Callable = subprocess.Popen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        start_monitor: bool = True,
        monitor_interval_sec: float = 1.0,
    ):
        self.base_cfg = copy.deepcopy(base_cfg)
        self.project_root = Path(project_root).resolve()
        self.base_config_path = resolve_path(base_config_path, self.project_root)
        self.camera_provider = camera_provider
        self.popen_factory = popen_factory
        self.sleep = sleep
        self.clock = clock
        self.base_runtime_dir = resolve_path(
            self.base_cfg["runtime"]["dir"],
            self.project_root,
        )
        self.legacy_camera_root = resolve_path(
            self.base_cfg["runtime"].get(
                "camera_root",
                self.base_runtime_dir / "cameras",
            ),
            self.project_root,
        )
        configured_departments_root = (
            self.base_cfg.get("departments", {}) or {}
        ).get("runtime_root")
        self.departments_root = (
            resolve_path(configured_departments_root, self.project_root)
            if configured_departments_root
            else self.base_runtime_dir / "departments"
        )
        self.max_running_cameras = int(
            self.base_cfg["runtime"].get("max_running_cameras", 16)
        )
        if self.max_running_cameras <= 0:
            raise ValueError("runtime.max_running_cameras 必须是正整数")
        self.runtimes: dict[tuple[str, str], CameraRuntime] = {}
        self.vlm_process: subprocess.Popen | None = None
        self.vlm_restart_attempts = 0
        self.vlm_restart_at: float | None = None
        self.vlm_last_error = ""
        self._lock = threading.RLock()
        self._shutting_down = False
        self._monitor_interval_sec = max(0.1, float(monitor_interval_sec))
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        if start_monitor:
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                name="security-vlm-runtime-monitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def start(self, department: str, camera_id: str) -> dict:
        department = require_department(department)
        camera_id = validate_camera_id(camera_id)
        with self._lock:
            if self._shutting_down:
                return {
                    "ok": False,
                    "department": department,
                    "camera_id": camera_id,
                    "running": False,
                    "desired_running": False,
                    "message": "运行时正在关闭，拒绝启动摄像头",
                }
            camera = self._get_camera(department, camera_id)
            if camera is None:
                return {
                    "ok": False,
                    "department": department,
                    "camera_id": camera_id,
                    "message": "摄像头不存在",
                }
            key = (department, camera_id)
            paths = self._paths(department, camera_id)
            runtime = self.runtimes.get(key)
            if runtime is None:
                if self._active_runtime_count() >= self.max_running_cameras:
                    return {
                        "ok": False,
                        "department": department,
                        "camera_id": camera_id,
                        "running": False,
                        "desired_running": False,
                        "message": (
                            "运行实例已达到总上限 "
                            f"{self.max_running_cameras}"
                        ),
                    }
                runtime = CameraRuntime(
                    department,
                    camera_id,
                    paths.config_path,
                )
                self.runtimes[key] = runtime
            elif not runtime.desired_running and (
                self._active_runtime_count() >= self.max_running_cameras
            ):
                return self._result(
                    runtime,
                    False,
                    f"运行实例已达到总上限 {self.max_running_cameras}",
                )
            runtime.desired_running = True
            runtime.restart_attempts = 0
            runtime.restart_at = None
            if self._runtime_is_running(runtime):
                return self._result(runtime, True, "already running")
            try:
                self._start_runtime(runtime, camera, paths)
                vlm_running = self._ensure_vlm()
                result = self._result(
                    runtime,
                    vlm_running,
                    "running" if vlm_running else "摄像头已运行，VLM 正在重试",
                )
                result["degraded"] = not vlm_running
                return result
            except Exception as exc:
                runtime.last_error = str(exc)
                self._terminate_runtime_processes(runtime)
                self._schedule_restart(runtime)
                LOGGER.exception(
                    "启动事业部 %s 摄像头 %s 的 worker 失败",
                    department,
                    camera_id,
                )
                return self._result(runtime, False, runtime.last_error)

    def stop(self, department: str, camera_id: str) -> dict:
        department = require_department(department)
        camera_id = validate_camera_id(camera_id)
        with self._lock:
            key = (department, camera_id)
            runtime = self.runtimes.get(key)
            if runtime is None:
                camera = self._get_camera(department, camera_id)
                if camera is None:
                    return {
                        "ok": False,
                        "department": department,
                        "camera_id": camera_id,
                        "message": "摄像头不存在",
                    }
                paths = self._paths(department, camera_id)
                runtime = CameraRuntime(
                    department,
                    camera_id,
                    paths.config_path,
                )
                self.runtimes[key] = runtime
            runtime.desired_running = False
            runtime.restart_at = None
            runtime.restart_attempts = 0
            self._terminate_runtime_processes(runtime)
            if not self._has_active_camera():
                self._stop_vlm()
            return self._result(runtime, True, "stopped")

    def restart(self, department: str, camera_id: str) -> dict:
        with self._lock:
            stopped = self.stop(department, camera_id)
            if not stopped["ok"]:
                return stopped
            return self.start(department, camera_id)

    def start_all(self, department: str) -> dict:
        department = require_department(department)
        with self._lock:
            if self._shutting_down:
                return {
                    "ok": False,
                    "department": department,
                    "message": "运行时正在关闭，拒绝全部启动",
                    "results": {},
                }
            results = {}
            for camera in self.camera_provider(department):
                camera_id = str(camera["camera_id"])
                results[camera_id] = self.start(department, camera_id)
            return {
                "ok": all(result["ok"] for result in results.values()),
                "department": department,
                "results": results,
            }

    def stop_all(self, department: str) -> dict:
        department = require_department(department)
        with self._lock:
            camera_ids = {
                str(camera["camera_id"])
                for camera in self.camera_provider(department)
            } | {
                camera_id
                for runtime_department, camera_id in self.runtimes
                if runtime_department == department
            }
            results = {
                camera_id: self.stop(department, camera_id)
                for camera_id in camera_ids
            }
            return {
                "ok": all(result["ok"] for result in results.values()),
                "department": department,
                "results": results,
            }

    def is_running(self, department: str, camera_id: str) -> bool:
        department = require_department(department)
        camera_id = validate_camera_id(camera_id)
        with self._lock:
            runtime = self.runtimes.get((department, camera_id))
            return bool(runtime and self._runtime_is_running(runtime))

    def status(self, department: str, camera_id: str) -> dict:
        department = require_department(department)
        camera_id = validate_camera_id(camera_id)
        self.reconcile()
        with self._lock:
            runtime = self.runtimes.get((department, camera_id))
            if runtime is None:
                return {
                    "department": department,
                    "camera_id": camera_id,
                    "desired_running": False,
                    "running": False,
                    "workers": {},
                    "last_error": "",
                    "restart_at": None,
                }
            return {
                "department": runtime.department,
                "camera_id": runtime.camera_id,
                "desired_running": runtime.desired_running,
                "running": self._runtime_is_running(runtime),
                "workers": {
                    name: process.poll() is None
                    for name, process in runtime.processes.items()
                },
                "last_error": runtime.last_error,
                "restart_at": runtime.restart_at,
            }

    def vlm_status(self) -> dict:
        with self._lock:
            running = (
                self.vlm_process is not None
                and self.vlm_process.poll() is None
            )
            return {
                "running": running,
                "desired_running": self._has_active_camera(),
                "restart_at": self.vlm_restart_at,
                "restart_attempts": self.vlm_restart_attempts,
                "last_error": self.vlm_last_error,
            }

    def reconcile(self) -> None:
        """检测意外退出，并按有界退避重启完整摄像头进程组。"""
        with self._lock:
            if self._shutting_down:
                return
            now = self.clock()
            for runtime in list(self.runtimes.values()):
                if not runtime.desired_running:
                    continue
                if runtime.restart_at is not None:
                    if now < runtime.restart_at:
                        continue
                    camera = self._get_camera(
                        runtime.department,
                        runtime.camera_id,
                    )
                    if camera is None:
                        runtime.desired_running = False
                        runtime.last_error = "摄像头已删除"
                        runtime.restart_at = None
                        continue
                    paths = self._paths(
                        runtime.department,
                        runtime.camera_id,
                    )
                    try:
                        runtime.restart_at = None
                        self._start_runtime(runtime, camera, paths)
                        self._ensure_vlm()
                    except Exception as exc:
                        runtime.last_error = str(exc)
                        self._terminate_runtime_processes(runtime)
                        self._schedule_restart(runtime)
                        LOGGER.exception(
                            "自动重启事业部 %s 摄像头 %s 的 worker 失败",
                            runtime.department,
                            runtime.camera_id,
                        )
                    continue

                if runtime.processes and not self._runtime_is_running(runtime):
                    exited = [
                        name
                        for name, process in runtime.processes.items()
                        if process.poll() is not None
                    ]
                    runtime.last_error = f"worker 意外退出: {', '.join(exited)}"
                    self._terminate_runtime_processes(runtime)
                    self._schedule_restart(runtime)

            if self._has_active_camera():
                self._ensure_vlm()
            else:
                self._stop_vlm()

    def shutdown(self) -> None:
        with self._lock:
            self._shutting_down = True
            self._monitor_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=self._monitor_interval_sec + 1.0)
        with self._lock:
            runtime_keys = list(self.runtimes)
            for department, camera_id in runtime_keys:
                self.stop(department, camera_id)
            self._stop_vlm()

    def _start_runtime(
        self,
        runtime: CameraRuntime,
        camera: dict,
        paths: CameraRuntimePaths,
    ) -> None:
        if runtime.processes:
            self._terminate_runtime_processes(runtime)
        snapshot = build_camera_config(self.base_cfg, camera, paths)
        write_camera_config(snapshot, paths.config_path)
        runtime.config_path = paths.config_path
        runtime.processes.clear()
        worker_python = str(self.base_cfg["envs"]["worker_python"])
        env = os.environ.copy()
        for name, script in _WORKER_SCRIPTS:
            script_path = self.project_root / "src" / script
            command = [
                worker_python,
                str(script_path),
                "--config",
                str(paths.config_path),
            ]
            runtime.processes[name] = self.popen_factory(
                command,
                cwd=str(self.project_root),
                env=env,
            )
            self.sleep(0.3)
        runtime.restart_at = None
        runtime.last_error = ""

    def _ensure_vlm(self) -> bool:
        now = self.clock()
        if self.vlm_process is not None:
            if self.vlm_process.poll() is None:
                return True
            self.vlm_last_error = (
                f"VLM worker 意外退出，退出码 {self.vlm_process.poll()}"
            )
            self.vlm_process = None
            if self.vlm_restart_at is None:
                self._schedule_vlm_restart()
                return False
        if self.vlm_restart_at is not None and now < self.vlm_restart_at:
            return False
        worker_python = str(self.base_cfg["envs"]["worker_python"])
        command = [
            worker_python,
            str(self.project_root / "src" / "vlm_worker.py"),
            "--config",
            str(self.base_config_path),
            "--departments-root",
            str(self.departments_root),
            "--camera-root",
            str(self.legacy_camera_root),
        ]
        try:
            self.vlm_process = self.popen_factory(
                command,
                cwd=str(self.project_root),
                env=os.environ.copy(),
            )
            self.vlm_restart_at = None
            self.vlm_last_error = ""
            return True
        except Exception as exc:
            self.vlm_process = None
            self.vlm_last_error = str(exc)
            self._schedule_vlm_restart()
            LOGGER.exception("启动全局 VLM worker 失败")
            return False

    def _stop_vlm(self) -> None:
        if self.vlm_process is None:
            self.vlm_restart_at = None
            self.vlm_restart_attempts = 0
            self.vlm_last_error = ""
            return
        self._terminate_process(
            self.vlm_process,
            "vlm",
            timeout=125.0,
        )
        self.vlm_process = None
        self.vlm_restart_at = None
        self.vlm_restart_attempts = 0
        self.vlm_last_error = ""

    def _terminate_runtime_processes(self, runtime: CameraRuntime) -> None:
        for name in _STOP_ORDER:
            process = runtime.processes.get(name)
            if process is not None:
                self._terminate_process(process, name)
        runtime.processes.clear()

    @staticmethod
    def _terminate_process(
        process: subprocess.Popen,
        name: str,
        timeout: float = 10.0,
    ) -> None:
        if process.poll() is None:
            try:
                process.terminate()
            except Exception:
                LOGGER.exception("终止 %s worker 失败", name)
        try:
            process.wait(timeout=timeout)
        except Exception:
            LOGGER.warning("%s worker 未及时退出，执行强制终止", name)
            try:
                process.kill()
            except Exception:
                LOGGER.exception("强制终止 %s worker 失败", name)

    def _schedule_restart(self, runtime: CameraRuntime) -> None:
        delay_index = min(
            runtime.restart_attempts,
            len(_RESTART_BACKOFF_SECONDS) - 1,
        )
        runtime.restart_at = self.clock() + _RESTART_BACKOFF_SECONDS[delay_index]
        runtime.restart_attempts += 1

    def _schedule_vlm_restart(self) -> None:
        delay_index = min(
            self.vlm_restart_attempts,
            len(_RESTART_BACKOFF_SECONDS) - 1,
        )
        self.vlm_restart_at = (
            self.clock() + _RESTART_BACKOFF_SECONDS[delay_index]
        )
        self.vlm_restart_attempts += 1

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.wait(self._monitor_interval_sec):
            try:
                self.reconcile()
            except Exception:
                LOGGER.exception("摄像头运行时后台巡检失败")

    def _has_active_camera(self) -> bool:
        return any(
            runtime.desired_running
            and (
                self._runtime_is_running(runtime)
                or runtime.restart_at is not None
            )
            for runtime in self.runtimes.values()
        )

    def _active_runtime_count(self) -> int:
        return sum(
            1
            for runtime in self.runtimes.values()
            if runtime.desired_running
        )

    @staticmethod
    def _runtime_is_running(runtime: CameraRuntime) -> bool:
        return len(runtime.processes) == len(_WORKER_SCRIPTS) and all(
            process.poll() is None for process in runtime.processes.values()
        )

    def _get_camera(self, department: str, camera_id: str) -> dict | None:
        wanted = validate_camera_id(camera_id)
        return next(
            (
                camera
                for camera in self.camera_provider(department)
                if str(camera.get("camera_id")) == wanted
            ),
            None,
        )

    def _paths(
        self,
        department: str,
        camera_id: str,
    ) -> CameraRuntimePaths:
        return CameraRuntimePaths(
            self.departments_root,
            department,
            camera_id,
        )

    @staticmethod
    def _result(runtime: CameraRuntime, ok: bool, message: str) -> dict:
        return {
            "ok": ok,
            "department": runtime.department,
            "camera_id": runtime.camera_id,
            "running": CameraRuntimeManager._runtime_is_running(runtime),
            "desired_running": runtime.desired_running,
            "message": message,
        }
