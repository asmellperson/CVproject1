"""Linux 启动前残留进程清理，匹配当前配置对应的采集、模型和 FFmpeg 管线。

扫描 /proc 后按摄像头共享内存名、模型名称及受约束的采集命令匹配，跳过当前进程。
先 SIGTERM 等待，再按需要 SIGKILL；该过程会真正结束进程，不是只读健康检查。
输出命令摘要前先脱敏 URL，返回值表示匹配数量，不保证所有对象均成功退出。
"""
from __future__ import annotations

import os
import re
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from AiVision.core.logger import logger

_URL_USERINFO_PATTERN = re.compile(
    r"\b((?:https?|rtsps?)://)[^/\s]*@",
    re.IGNORECASE,
)
_URL_QUERY_CREDENTIAL_PATTERN = re.compile(
    r"([?&](?:user(?:name)?|password|passwd|token|api[_-]?key)=)[^&\s]*",
    re.IGNORECASE,
)

# 发现的疑似残留进程
@dataclass(frozen=True)
class _ProcessHit:
    """记录候选进程的 PID、匹配原因和原始命令行；原始命令行必须脱敏后才能输出。"""
    pid: int
    reason: str                           # 为什么属于AiVision
    cmdline: str                          # 这个进程真实的命令行


def cleanup_aivision_residual_processes(
    camera_shm_names: Iterable[str],         # 摄像头共享内存名
    camera_urls: Iterable[str],              # 摄像头URL
    model_names: Iterable[str],              # 模型名称
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
    # 将共享内存名、摄像头URL、模型名称全部转换为set（过滤掉None/''、全部转换成字符串、自动去重）
    camera_keys = {str(item) for item in camera_shm_names if item}
    urls = {str(item) for item in camera_urls if item}
    models = {str(item) for item in model_names if item}
    # 什么配置都没有就不扫描
    if not camera_keys and not urls and not models:
        return 0
    # 扫描系统当前所有进程，并判断哪些像是Aivision上一次留下来的
    hits = _find_residual_processes(camera_keys, urls, models)
    if not hits:
        return 0
    # 第一阶段：先发SIGTERM（SIGTERM表示请你正常退出）
    for hit in hits:
        safe_cmdline = _redact_cmdline(hit.cmdline)
        logger.warning(f"[StartupCleanup] 清理残留进程 pid={hit.pid} reason={hit.reason}: {safe_cmdline[:300]}")
        _safe_kill(hit.pid, signal.SIGTERM)
    # 最多等待terminate_timeout秒
    deadline = time.time() + max(0.0, terminate_timeout)
    pending = {hit.pid for hit in hits}          # 已经发了SIGTERM，但是还要确认有没有真正退出的PID
    # 每0.1秒检查一次
    while pending and time.time() < deadline:
        pending = {pid for pid in pending if _is_alive(pid)}
        if pending:
            time.sleep(0.1)
    # SIGKILL相当于Linux：kill -9 PID
    for pid in list(pending):
        logger.warning(f"[StartupCleanup] 残留进程未退出,强制结束 pid={pid}")
        _safe_kill(pid, signal.SIGKILL)
    # 返回一共匹配到多少个残留进程（不是成功杀死多少个）
    return len(hits)

def _redact_cmdline(cmdline: str) -> str:
    """隐藏 URL 用户信息与敏感查询参数，保留其余命令结构用于排障。"""
    redacted = _URL_USERINFO_PATTERN.sub(r"\1***:***@", cmdline)
    return _URL_QUERY_CREDENTIAL_PATTERN.sub(r"\1***", redacted)

def _find_residual_processes(camera_keys: set[str], urls: set[str], models: set[str]) -> list[_ProcessHit]:
    # 当前Aivision进程PID（不允许杀当前的自己）
    """扫描 Linux 进程并按当前资源标识匹配候选，跳过自身、不可读条目和重复 PID。"""
    current_pid = os.getpid()
    hits: list[_ProcessHit] = []
    seen: set[int] = set()
    # Linux专用实现，Linux有/proc/1/、/proc/123/....数字目录就是PID
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():           # 只看数字目录
            continue
        pid = int(proc_dir.name)
        if pid == current_pid:                   # 不允许杀当前Aivision的PID
            continue
        # 读取/proc/PID/cmdline，这个里面就是这个进程的启动命令，linux参数之间不是普通空格，而是NULL字符 \x00
        cmdline = _read_cmdline(proc_dir)
        if not cmdline:
            continue
        reason = _match_process(cmdline, camera_keys, urls, models)
        if reason and pid not in seen:
            # 避免一个PID被重复加入
            seen.add(pid)
            hits.append(_ProcessHit(pid=pid, reason=reason, cmdline=cmdline))
    return hits

def _read_cmdline(proc_dir: Path) -> str:
    """读取 /proc 中的空字节分隔参数；进程消失或无权限时返回空字符串。"""
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    # 扫描/proc的过程中，进程可能刚刚还存在，下一秒自己就退出了，pid突然没了，所以FileNotFoundError, ProcessLookupError直接忽略
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return ""
    # python\x00main.py\x00--xxx\x00123变成python main.py --xxx 123
    return raw.replace(b"\x00", b" ").decode(errors="replace").strip()

def _match_process(cmdline: str, camera_keys: set[str], urls: set[str], models: set[str]) -> str:
    """匹配残留进程"""
    # Camera[{shm_name}认为这是上一轮的残留进程
    for shm_name in camera_keys:
        if f"Camera[{shm_name}]" in cmdline:
            return f"Camera[{shm_name}]"
    # 匹配当前的模型，也认为是上一轮的残留进程
    for model_name in models:
        if f"ModelWorker[{model_name}]" in cmdline:
            return f"ModelWorker[{model_name}]"
    # 同时要求ffmpeg + rtsp_transport + rawvideo
    if "ffmpeg" in cmdline and "rtsp_transport" in cmdline and "rawvideo" in cmdline:
        # 配置里的某一个RTSP URL
        for url in urls:
            if url and url in cmdline:
                return "ffmpeg-rtsp-rawvideo"

    return ""


def _is_alive(pid: int) -> bool:
    """通过零号信号检查进程是否仍存在，权限不足按存活处理，避免误判已退出。"""
    try:
        # 这里不是杀进程：signal 0的意义是：检查这个PID是否存在，以及能不能向它发送信号
        os.kill(pid, 0)
        return True
    # PID已经不存在
    except ProcessLookupError:
        return False
    # 没有权限给它发信号，但是这个PID存在
    except PermissionError:
        return True

def _safe_kill(pid: int, sig: signal.Signals):
    """向指定 PID 发送退出信号，容忍进程已消失并记录权限等发送失败。"""
    try:
        os.kill(pid, sig)
    # 进程自己没了不报错
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        logger.warning(f"[StartupCleanup] 无权限结束进程 pid={pid}: {exc}")
