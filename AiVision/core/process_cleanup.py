# 文件说明：实现资源清理相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
core/process_cleanup.py
启动前清理上一轮 AiVision 遗留的采集/推理子进程。
"""
from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from AiVision.core.logger import logger


# 功能：定义 `_ProcessHit` 类，封装资源清理相关的状态、约束与操作
# 参数：
#   - `pid`（int）：`pid` 对应的业务输入值
#   - `reason`（str）：`reason` 对应的业务输入值
#   - `cmdline`（str）：`cmdline` 对应的业务输入值
# 返回：_ProcessHit；返回新建的 `_ProcessHit` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/process_cleanup.py` 的 `_find_residual_processes` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _ProcessHit:
    pid: int
    reason: str
    cmdline: str


# 功能：清理本项目上一轮残留的 Camera/ModelWorker/ffmpeg 进程；输入与输出详见下方说明
# 参数：
#   - `camera_shm_names`（Iterable[str]）：`camera_shm_names` 对应的业务输入值
#   - `camera_urls`（Iterable[str]）：`camera_urls` 对应的业务输入值
#   - `model_names`（Iterable[str]）：`model_names` 对应的业务输入值
#   - `terminate_timeout`（float）：`terminate_timeout` 对应的业务输入值；默认值为 `3.0`
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::start` 调用本符号
#   - 内部调用：`str`、`_find_residual_processes`、`logger.warning`、`_safe_kill`、`time.time`、`max`、`_is_alive`、`time.sleep`、`list`、`len`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
def cleanup_aivision_residual_processes(
    camera_shm_names: Iterable[str],
    camera_urls: Iterable[str],
    model_names: Iterable[str],
    *,
    terminate_timeout: float = 3.0,
) -> int:
    """
    清理本项目上一轮残留的 Camera/ModelWorker/ffmpeg 进程。

    匹配范围刻意收窄:
        - Camera 进程: setproctitle 后包含 Camera[shm_name]
        - ModelWorker 进程: setproctitle 后包含 ModelWorker[model_name]
        - ffmpeg 进程: 命令行包含当前摄像头 URL,且是 rawvideo 拉流管线
    """
    camera_keys = {str(item) for item in camera_shm_names if item}
    urls = {str(item) for item in camera_urls if item}
    models = {str(item) for item in model_names if item}
    if not camera_keys and not urls and not models:
        return 0

    hits = _find_residual_processes(camera_keys, urls, models)
    if not hits:
        return 0

    for hit in hits:
        logger.warning(f"[StartupCleanup] 清理残留进程 pid={hit.pid} reason={hit.reason}: {hit.cmdline[:300]}")
        _safe_kill(hit.pid, signal.SIGTERM)

    deadline = time.time() + max(0.0, terminate_timeout)
    pending = {hit.pid for hit in hits}
    while pending and time.time() < deadline:
        pending = {pid for pid in pending if _is_alive(pid)}
        if pending:
            time.sleep(0.1)

    for pid in list(pending):
        logger.warning(f"[StartupCleanup] 残留进程未退出,强制结束 pid={pid}")
        _safe_kill(pid, signal.SIGKILL)

    return len(hits)


# 功能：读取或查询 `_find_residual_processes` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `camera_keys`（set[str]）：`camera_keys` 对应的业务输入值
#   - `urls`（set[str]）：`urls` 对应的业务输入值
#   - `models`（set[str]）：`models` 对应的业务输入值
# 返回：list[_ProcessHit]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/core/process_cleanup.py` 的 `cleanup_aivision_residual_processes` 调用本符号
#   - 内部调用：`os.getpid`、`set`、`Path('/proc').iterdir`、`Path`、`proc_dir.name.isdigit`、`int`、`_read_cmdline`、`_match_process`、`seen.add`、`hits.append`
#          等共 11 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def _find_residual_processes(camera_keys: set[str], urls: set[str], models: set[str]) -> list[_ProcessHit]:
    current_pid = os.getpid()
    hits: list[_ProcessHit] = []
    seen: set[int] = set()

    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        pid = int(proc_dir.name)
        if pid == current_pid:
            continue
        cmdline = _read_cmdline(proc_dir)
        if not cmdline:
            continue
        reason = _match_process(cmdline, camera_keys, urls, models)
        if reason and pid not in seen:
            seen.add(pid)
            hits.append(_ProcessHit(pid=pid, reason=reason, cmdline=cmdline))
    return hits


# 功能：读取或查询 `_read_cmdline` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `proc_dir`（Path）：`proc_dir` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/core/process_cleanup.py` 的 `_find_residual_processes` 调用本符号
#   - 内部调用：`(proc_dir / 'cmdline').read_bytes`、`raw.replace(b'\x00', b' ').decode(errors='replace').strip`、`raw.replace(b'\x00', b'
#          ').decode`、`raw.replace`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _read_cmdline(proc_dir: Path) -> str:
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return ""
    return raw.replace(b"\x00", b" ").decode(errors="replace").strip()


# 功能：处理 `_match_process` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `cmdline`（str）：`cmdline` 对应的业务输入值
#   - `camera_keys`（set[str]）：`camera_keys` 对应的业务输入值
#   - `urls`（set[str]）：`urls` 对应的业务输入值
#   - `models`（set[str]）：`models` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/core/process_cleanup.py` 的 `_find_residual_processes` 调用本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _match_process(cmdline: str, camera_keys: set[str], urls: set[str], models: set[str]) -> str:
    for shm_name in camera_keys:
        if f"Camera[{shm_name}]" in cmdline:
            return f"Camera[{shm_name}]"

    for model_name in models:
        if f"ModelWorker[{model_name}]" in cmdline:
            return f"ModelWorker[{model_name}]"

    if "ffmpeg" in cmdline and "rtsp_transport" in cmdline and "rawvideo" in cmdline:
        for url in urls:
            if url and url in cmdline:
                return "ffmpeg-rtsp-rawvideo"

    return ""


# 功能：检查或判断 `_is_alive` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `pid`（int）：`pid` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/core/process_cleanup.py` 的 `cleanup_aivision_residual_processes` 调用本符号
#   - 内部调用：`os.kill`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


# 功能：实现 `_safe_kill` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `pid`（int）：`pid` 对应的业务输入值
#   - `sig`（signal.Signals）：`sig` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：`AiVision/core/process_cleanup.py` 的 `cleanup_aivision_residual_processes` 调用本符号
#   - 内部调用：`os.kill`、`logger.warning`。
# 副作用/注意事项：会向日志系统输出运行或异常信息。
def _safe_kill(pid: int, sig: signal.Signals):
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        logger.warning(f"[StartupCleanup] 无权限结束进程 pid={pid}: {exc}")
