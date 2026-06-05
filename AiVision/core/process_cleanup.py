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

from core.logger import logger


@dataclass(frozen=True)
class _ProcessHit:
    pid: int
    reason: str
    cmdline: str


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


def _read_cmdline(proc_dir: Path) -> str:
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return ""
    return raw.replace(b"\x00", b" ").decode(errors="replace").strip()


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


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _safe_kill(pid: int, sig: signal.Signals):
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        logger.warning(f"[StartupCleanup] 无权限结束进程 pid={pid}: {exc}")
