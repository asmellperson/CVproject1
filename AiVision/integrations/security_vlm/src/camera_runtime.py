# 文件说明：实现摄像头、运行时相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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
from departments import SECURITY_DEPARTMENTS, require_department
from frame_hub import reset_frame_hub

_WORKER_SCRIPTS = (
    ("capture", "capture_worker.py"),
    ("detector", "detector_worker.py"),
    ("session", "session_worker.py"),
)
_STOP_ORDER = ("session", "detector", "capture")
_RESTART_BACKOFF_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)
LOGGER = logging.getLogger(__name__)


# 功能：所有配置路径统一相对 security_vlm 项目根解析；输入与输出详见下方说明
# 参数：
#   - `path`（str | Path）：目标路径
#   - `project_root`（Path）：`project_root` 对应的业务输入值
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Path`、`candidate.is_absolute`、`candidate.resolve`、`(Path(project_root) / candidate).resolve`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def resolve_path(path: str | Path, project_root: Path) -> Path:
    """所有配置路径统一相对 security_vlm 项目根解析。"""
    candidate = Path(path)
    return (
        candidate.resolve()
        if candidate.is_absolute()
        else (Path(project_root) / candidate).resolve()
    )


# 功能：一台摄像头独占的运行时路径；输入与输出详见下方说明
# 参数：
#   - `departments_root`（Path）：`departments_root` 对应的业务输入值
#   - `department`（str）：业务部门名称或标识
#   - `camera_id`（str）：摄像头唯一标识
# 返回：CameraRuntimePaths；返回新建的 `CameraRuntimePaths` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::_paths`
#         实例化本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::camera_runtime_dir` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class CameraRuntimePaths:
    """一台摄像头独占的运行时路径。"""

    departments_root: Path
    department: str
    camera_id: str

    # 功能：初始化或配置 `__post_init__` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`object.__setattr__`、`Path`、`require_department`、`validate_camera_id`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：实现 `department_runtime_dir` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def department_runtime_dir(self) -> Path:
        return self.departments_root / self.department

    # 功能：实现 `runtime_dir` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def runtime_dir(self) -> Path:
        return (
            self.department_runtime_dir
            / "cameras"
            / self.camera_id
        )

    # 功能：实现 `pending_dir` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def pending_dir(self) -> Path:
        return self.runtime_dir / "pending"

    # 功能：实现 `config_path` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def config_path(self) -> Path:
        return self.runtime_dir / "worker_config.yaml"


# 功能：从全局配置生成一台摄像头专用且互不共享引用的配置；输入与输出详见下方说明
# 参数：
#   - `base_cfg`（dict）：`base_cfg` 对应的业务输入值
#   - `camera`（dict）：摄像头配置或实体
#   - `paths`（CameraRuntimePaths）：`paths` 对应的业务输入值
#   - `staff_identity_dir`（Path | None）：`staff_identity_dir` 对应的业务输入值；默认值为 `None`
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::_start_runtime` 调用本符号
#   - 内部调用：`copy.deepcopy`、`snapshot.setdefault`、`str`、`Path(staff_identity_dir).resolve`、`Path`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def build_camera_config(
    base_cfg: dict,
    camera: dict,
    paths: CameraRuntimePaths,
    *,
    staff_identity_dir: Path | None = None,
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
    if staff_identity_dir is not None:
        data_cfg["staff_identity_dir"] = str(Path(staff_identity_dir).resolve())
    runtime_cfg["dir"] = str(paths.runtime_dir)
    runtime_cfg["department_dir"] = str(paths.department_runtime_dir)
    session_cfg["pending_queue_dir"] = str(paths.pending_dir)
    return snapshot


# 功能：原子写入只允许文件所有者读取的 worker 配置；输入与输出详见下方说明
# 参数：
#   - `snapshot`（dict）：`snapshot` 对应的业务输入值
#   - `path`（Path）：目标路径
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::_start_runtime` 调用本符号
#   - 内部调用：`Path`、`config_path.parent.mkdir`、`config_path.with_name`、`uuid.uuid4`、`temp_path.write_text`、`yaml.safe_dump`、`os.chmod`、`temp_path.replace`、`temp_path.unlink`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：一台摄像头的期望状态和子进程句柄；输入与输出详见下方说明
# 参数：
#   - `department`（str）：业务部门名称或标识
#   - `camera_id`（str）：摄像头唯一标识
#   - `config_path`（Path）：`config_path` 对应的业务输入值
#   - `desired_running`（bool）：`desired_running` 对应的业务输入值
#   - `processes`（dict[str, subprocess.Popen]）：`processes` 对应的业务输入值
#   - `restart_attempts`（int）：`restart_attempts` 对应的业务输入值
#   - `restart_at`（float | None）：`restart_at` 对应的业务输入值
#   - `last_error`（str）：`last_error` 对应的业务输入值
# 返回：CameraRuntime；返回新建的 `CameraRuntime` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：管理每摄像头 worker 进程组以及唯一的全局 VLM worker；输入与输出详见下方说明
# 参数：
#   - `base_cfg`（dict）：`base_cfg` 对应的业务输入值
#   - `project_root`（Path）：`project_root` 对应的业务输入值
#   - `base_config_path`（Path）：`base_config_path` 对应的业务输入值
#   - `camera_provider`（Callable[[str], list[dict]]）：`camera_provider` 对应的业务输入值
#   - `popen_factory`（Callable）：`popen_factory` 对应的业务输入值；默认值为 `subprocess.Popen`
#   - `sleep`（Callable[[float], None]）：`sleep` 对应的业务输入值；默认值为 `time.sleep`
#   - `clock`（Callable[[], float]）：`clock` 对应的业务输入值；默认值为 `time.time`
#   - `start_monitor`（bool）：`start_monitor` 对应的业务输入值；默认值为 `True`
#   - `monitor_interval_sec`（float）：`monitor_interval_sec` 对应的时间间隔或时长；默认值为 `1.0`
# 返回：CameraRuntimeManager；返回新建的 `CameraRuntimeManager` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::__init__` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraRuntimeManager:
    """管理每摄像头 worker 进程组以及唯一的全局 VLM worker。"""

    # 功能：初始化或配置 `__init__` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `base_cfg`（dict）：`base_cfg` 对应的业务输入值
    #   - `project_root`（Path）：`project_root` 对应的业务输入值
    #   - `base_config_path`（Path）：`base_config_path` 对应的业务输入值
    #   - `camera_provider`（Callable[[str], list[dict]]）：`camera_provider` 对应的业务输入值
    #   - `popen_factory`（Callable）：`popen_factory` 对应的业务输入值；默认值为 `subprocess.Popen`
    #   - `sleep`（Callable[[float], None]）：`sleep` 对应的业务输入值；默认值为 `time.sleep`
    #   - `clock`（Callable[[], float]）：`clock` 对应的业务输入值；默认值为 `time.time`
    #   - `start_monitor`（bool）：`start_monitor` 对应的业务输入值；默认值为 `True`
    #   - `monitor_interval_sec`（float）：`monitor_interval_sec` 对应的时间间隔或时长；默认值为 `1.0`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`copy.deepcopy`、`Path(project_root).resolve`、`Path`、`resolve_path`、`self.base_cfg['runtime'].get`、`(self.base_cfg.get('departments',
    #          {}) or {}).get`、`self.base_cfg.get`、`int`、`ValueError`、`threading.RLock` 等共 15 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
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
        configured_departments_data_root = (
            self.base_cfg.get("departments", {}) or {}
        ).get("data_root", "data/departments")
        self.departments_data_root = resolve_path(
            configured_departments_data_root,
            self.project_root,
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
        self._department_gates = {
            department: threading.RLock() for department in SECURITY_DEPARTMENTS
        }
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

    # 功能：启动或执行 `start` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::restart`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start_all` 调用本符号
    #   - 内部调用：`require_department`、`validate_camera_id`、`self._get_camera`、`self._paths`、`self.runtimes.get`、`self._active_runtime_count`、`CameraRuntime`、`self._result`、`self._runtime_is_running`、`self._detach_runtime_processes`
    #          等共 16 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def start(self, department: str, camera_id: str) -> dict:
        department = require_department(department)
        camera_id = validate_camera_id(camera_id)
        with self._department_gates[department]:
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
                stale_processes = self._detach_runtime_processes(runtime)

            # 旧进程组可能等待数十秒，绝不能占用跨事业部全局锁。
            self._terminate_processes(stale_processes)

            failed_processes = {}
            with self._lock:
                if self._shutting_down or not runtime.desired_running:
                    runtime.desired_running = False
                    return self._result(
                        runtime,
                        False,
                        "运行时正在关闭，拒绝启动摄像头",
                    )
                try:
                    self._start_runtime(runtime, camera, paths)
                    vlm_running = self._ensure_vlm()
                    result = self._result(
                        runtime,
                        vlm_running,
                        (
                            "running"
                            if vlm_running
                            else "摄像头已运行，VLM 正在重试"
                        ),
                    )
                    result["degraded"] = not vlm_running
                except Exception as exc:
                    runtime.last_error = str(exc)
                    failed_processes = self._detach_runtime_processes(runtime)
                    self._schedule_restart(runtime)
                    LOGGER.exception(
                        "启动事业部 %s 摄像头 %s 的 worker 失败",
                        department,
                        camera_id,
                    )
                    result = self._result(
                        runtime,
                        False,
                        runtime.last_error,
                    )
            self._terminate_processes(failed_processes)
            return result

    # 功能：停止并释放 `stop` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::restart`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::stop_all` 调用本符号
    #   - 内部调用：`require_department`、`validate_camera_id`、`self.runtimes.get`、`self._get_camera`、`self._paths`、`CameraRuntime`、`self._detach_runtime_processes`、`self._has_active_camera`、`self._detach_vlm`、`self._result`
    #          等共 12 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def stop(self, department: str, camera_id: str) -> dict:
        department = require_department(department)
        camera_id = validate_camera_id(camera_id)
        with self._department_gates[department], self._lock:
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
            processes = self._detach_runtime_processes(runtime)
            if not self._has_active_camera():
                vlm = self._detach_vlm()
            else:
                vlm = None
            result = self._result(runtime, True, "stopped")
        self._terminate_processes(processes)
        if vlm is not None:
            self._terminate_process(vlm, "vlm", timeout=125.0)
        return result

    # 功能：实现 `restart` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_department`、`self.stop`、`self.start`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def restart(self, department: str, camera_id: str) -> dict:
        department = require_department(department)
        with self._department_gates[department]:
            stopped = self.stop(department, camera_id)
            if not stopped["ok"]:
                return stopped
            return self.start(department, camera_id)

    # 功能：启动或执行 `start_all` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_department`、`list`、`self.camera_provider`、`str`、`self.start`、`all`、`results.values`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def start_all(self, department: str) -> dict:
        department = require_department(department)
        with self._department_gates[department]:
            with self._lock:
                if self._shutting_down:
                    return {
                        "ok": False,
                        "department": department,
                        "message": "运行时正在关闭，拒绝全部启动",
                        "results": {},
                    }
                cameras = list(self.camera_provider(department))
            results = {
                str(camera["camera_id"]): self.start(
                    department,
                    str(camera["camera_id"]),
                )
                for camera in cameras
            }
        return {
            "ok": all(result["ok"] for result in results.values()),
            "department": department,
            "results": results,
        }

    # 功能：停止并释放 `stop_all` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_department`、`str`、`self.camera_provider`、`self.stop`、`all`、`results.values`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def stop_all(self, department: str) -> dict:
        department = require_department(department)
        with self._department_gates[department]:
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

    # 功能：检查或判断 `is_running` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_department`、`validate_camera_id`、`self.runtimes.get`、`bool`、`self._runtime_is_running`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_running(self, department: str, camera_id: str) -> bool:
        department = require_department(department)
        camera_id = validate_camera_id(camera_id)
        with self._lock:
            runtime = self.runtimes.get((department, camera_id))
            return bool(runtime and self._runtime_is_running(runtime))

    # 功能：实现 `status` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_department`、`validate_camera_id`、`self.runtimes.get`、`self._runtime_is_running`、`process.poll`、`runtime.processes.items`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def status(self, department: str, camera_id: str) -> dict:
        department = require_department(department)
        camera_id = validate_camera_id(camera_id)
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

    # 功能：实现 `vlm_status` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_camera_runtime.py` 的
    #         `test_vlm_start_failure_marks_camera_start_degraded_and_schedules_retry`
    #         调用本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::get_state` 调用本符号
    #   - 内部调用：`self.vlm_process.poll`、`self._has_active_camera`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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

    # 功能：检测意外退出，并按有界退避重启完整摄像头进程组；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::_monitor_loop` 调用本符号
    #   - 内部调用：`self.clock`、`self.runtimes.values`、`self._get_camera`、`self._paths`、`self._start_runtime`、`self._ensure_vlm`、`str`、`process_groups.append`、`self._detach_runtime_processes`、`self._schedule_restart`
    #          等共 19 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def reconcile(self) -> None:
        """检测意外退出，并按有界退避重启完整摄像头进程组。"""
        now = self.clock()
        for department in SECURITY_DEPARTMENTS:
            process_groups = []
            with self._department_gates[department]:
                with self._lock:
                    if self._shutting_down:
                        return
                    department_runtimes = [
                        runtime
                        for runtime in self.runtimes.values()
                        if runtime.department == department
                    ]
                    for runtime in department_runtimes:
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
                                process_groups.append(
                                    self._detach_runtime_processes(runtime)
                                )
                                self._schedule_restart(runtime)
                                LOGGER.exception(
                                    "自动重启事业部 %s 摄像头 %s 的 worker 失败",
                                    runtime.department,
                                    runtime.camera_id,
                                )
                            continue

                        if (
                            runtime.processes
                            and not self._runtime_is_running(runtime)
                        ):
                            exited = [
                                name
                                for name, process in runtime.processes.items()
                                if process.poll() is not None
                            ]
                            runtime.last_error = (
                                f"worker 意外退出: {', '.join(exited)}"
                            )
                            process_groups.append(
                                self._detach_runtime_processes(runtime)
                            )
                            self._schedule_restart(runtime)

                # 同事业部 gate 保持到旧进程完全退出，禁止新旧组重叠。
                for processes in process_groups:
                    self._terminate_processes(processes)

        vlm_to_stop = None
        with self._lock:
            if self._shutting_down:
                return
            if self._has_active_camera():
                self._ensure_vlm()
            else:
                vlm_to_stop = self._detach_vlm()
        if vlm_to_stop is not None:
            self._terminate_process(vlm_to_stop, "vlm", timeout=125.0)

    # 功能：停止并释放 `shutdown` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._monitor_stop.set`、`self._monitor_thread.join`、`self.runtimes.values`、`process_groups.append`、`self._detach_runtime_processes`、`self._detach_vlm`、`self._terminate_processes`、`self._terminate_process`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def shutdown(self) -> None:
        with self._lock:
            self._shutting_down = True
            self._monitor_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=self._monitor_interval_sec + 1.0)
        with self._lock:
            process_groups = []
            for runtime in self.runtimes.values():
                runtime.desired_running = False
                runtime.restart_at = None
                process_groups.append(self._detach_runtime_processes(runtime))
            vlm = self._detach_vlm()
        for processes in process_groups:
            self._terminate_processes(processes)
        if vlm is not None:
            self._terminate_process(vlm, "vlm", timeout=125.0)

    # 功能：启动或执行 `_start_runtime` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `runtime`（CameraRuntime）：`runtime` 对应的业务输入值
    #   - `camera`（dict）：摄像头配置或实体
    #   - `paths`（CameraRuntimePaths）：`paths` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile` 调用本符号
    #   - 内部调用：`RuntimeError`、`reset_frame_hub`、`build_camera_config`、`write_camera_config`、`runtime.processes.clear`、`str`、`os.environ.copy`、`self.popen_factory`、`self.sleep`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
    def _start_runtime(
        self,
        runtime: CameraRuntime,
        camera: dict,
        paths: CameraRuntimePaths,
    ) -> None:
        if runtime.processes:
            raise RuntimeError("旧摄像头进程组尚未摘取")
        # 必须在启动 capture/detector/session 前撤下旧 meta。否则分辨率变化时，
        # detector 可能先读取上一轮尺寸，并在 capture 缩小 slot 后触发 SIGBUS。
        reset_frame_hub(paths.runtime_dir)
        snapshot = build_camera_config(
            self.base_cfg,
            camera,
            paths,
            staff_identity_dir=(
                self.departments_data_root / paths.department / "rois"
            ),
        )
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

    # 功能：检查或判断 `_ensure_vlm` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile` 调用本符号
    #   - 内部调用：`self.clock`、`self.vlm_process.poll`、`self._schedule_vlm_restart`、`str`、`self.popen_factory`、`os.environ.copy`、`LOGGER.exception`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
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

    # 功能：停止并释放 `_stop_vlm` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._terminate_process`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：实现 `_detach_vlm` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::stop`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::shutdown` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def _detach_vlm(self):
        process = self.vlm_process
        self.vlm_process = None
        self.vlm_restart_at = None
        self.vlm_restart_attempts = 0
        self.vlm_last_error = ""
        return process

    # 功能：实现 `_terminate_processes` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `processes`（dict[str, subprocess.Popen]）：`processes` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::stop`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::shutdown` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`processes.get`、`CameraRuntimeManager._terminate_process`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    @staticmethod
    def _terminate_processes(processes: dict[str, subprocess.Popen]) -> None:
        for name in _STOP_ORDER:
            process = processes.get(name)
            if process is not None:
                CameraRuntimeManager._terminate_process(process, name)

    # 功能：实现 `_detach_runtime_processes` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `runtime`（CameraRuntime）：`runtime` 对应的业务输入值
    # 返回：dict[str, subprocess.Popen]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::stop`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::shutdown` 调用本符号；另有 1 处静态调用
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _detach_runtime_processes(runtime: CameraRuntime) -> dict[str, subprocess.Popen]:
        processes = runtime.processes
        runtime.processes = {}
        return processes

    # 功能：实现 `_terminate_runtime_processes` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `runtime`（CameraRuntime）：`runtime` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._terminate_processes`、`self._detach_runtime_processes`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def _terminate_runtime_processes(self, runtime: CameraRuntime) -> None:
        self._terminate_processes(self._detach_runtime_processes(runtime))

    # 功能：处理 `_terminate_process` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `process`（subprocess.Popen）：`process` 对应的业务输入值
    #   - `name`（str）：业务对象名称
    #   - `timeout`（float）：允许操作等待的最长秒数；默认值为 `10.0`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::stop`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::shutdown`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::_stop_vlm` 调用本符号；另有 2 处静态调用
    #   - 内部调用：`process.poll`、`process.terminate`、`LOGGER.exception`、`process.wait`、`LOGGER.warning`、`process.kill`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
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
                return
            try:
                process.wait(timeout=2.0)
            except Exception:
                LOGGER.exception("强制终止后回收 %s worker 失败", name)

    # 功能：实现 `_schedule_restart` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `runtime`（CameraRuntime）：`runtime` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile` 调用本符号
    #   - 内部调用：`min`、`len`、`self.clock`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _schedule_restart(self, runtime: CameraRuntime) -> None:
        delay_index = min(
            runtime.restart_attempts,
            len(_RESTART_BACKOFF_SECONDS) - 1,
        )
        runtime.restart_at = self.clock() + _RESTART_BACKOFF_SECONDS[delay_index]
        runtime.restart_attempts += 1

    # 功能：实现 `_schedule_vlm_restart` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::_ensure_vlm` 调用本符号
    #   - 内部调用：`min`、`len`、`self.clock`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def _schedule_vlm_restart(self) -> None:
        delay_index = min(
            self.vlm_restart_attempts,
            len(_RESTART_BACKOFF_SECONDS) - 1,
        )
        self.vlm_restart_at = (
            self.clock() + _RESTART_BACKOFF_SECONDS[delay_index]
        )
        self.vlm_restart_attempts += 1

    # 功能：实现 `_monitor_loop` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._monitor_stop.wait`、`self.reconcile`、`LOGGER.exception`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _monitor_loop(self) -> None:
        while not self._monitor_stop.wait(self._monitor_interval_sec):
            try:
                self.reconcile()
            except Exception:
                LOGGER.exception("摄像头运行时后台巡检失败")

    # 功能：检查或判断 `_has_active_camera` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::stop`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::vlm_status`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile` 调用本符号
    #   - 内部调用：`any`、`self._runtime_is_running`、`self.runtimes.values`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _has_active_camera(self) -> bool:
        return any(
            runtime.desired_running
            and (
                self._runtime_is_running(runtime)
                or runtime.restart_at is not None
            )
            for runtime in self.runtimes.values()
        )

    # 功能：实现 `_active_runtime_count` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start` 调用本符号
    #   - 内部调用：`sum`、`self.runtimes.values`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _active_runtime_count(self) -> int:
        return sum(
            1
            for runtime in self.runtimes.values()
            if runtime.desired_running
        )

    # 功能：检查或判断 `_runtime_is_running` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `runtime`（CameraRuntime）：`runtime` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::is_running`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::status`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile` 调用本符号；另有 2 处静态调用
    #   - 内部调用：`len`、`all`、`process.poll`、`runtime.processes.values`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    @staticmethod
    def _runtime_is_running(runtime: CameraRuntime) -> bool:
        return len(runtime.processes) == len(_WORKER_SCRIPTS) and all(
            process.poll() is None for process in runtime.processes.values()
        )

    # 功能：读取或查询 `_get_camera` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::stop`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile` 调用本符号
    #   - 内部调用：`validate_camera_id`、`next`、`self.camera_provider`、`str`、`camera.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：实现 `_paths` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：CameraRuntimePaths；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::stop`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::reconcile`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_camera_runtime.py` 的
    #         `test_manager_removes_stale_framehub_before_starting_workers` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`CameraRuntimePaths`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：实现 `_result` 对应的摄像头、运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `runtime`（CameraRuntime）：`runtime` 对应的业务输入值
    #   - `ok`（bool）：`ok` 对应的业务输入值
    #   - `message`（str）：用于展示、记录或发送的文本消息
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_runtime.py` 的 `CameraRuntimeManager::stop` 调用本符号
    #   - 内部调用：`CameraRuntimeManager._runtime_is_running`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
