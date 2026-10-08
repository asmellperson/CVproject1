"""
检查摄像头能否正常解析，并拿到视频分辨率
三大部分：
    1、CameraProbeError:统一探测失败异常
    2、_redact_rtsp_credentials(): 错误日志里隐藏RTSP用户名密码
    3、probe_video_shape():真正调用ffprobe分辨率
"""
from __future__ import annotations

import json
import re
import subprocess
# 一次摄像头探测最多等8秒
FFPROBE_TIMEOUT_SECONDS = 8.0
# 正则匹配
_RTSP_CREDENTIALS = re.compile(r"(rtsp://)[^/@\s]+@")

class CameraProbeError(RuntimeError):
    """统一表达探测程序、视频流或分辨率解析失败，供摄像头启动流程分类处理。"""

def _redact_rtsp_credentials(value: str) -> str:
    """把错误信息里的RTSP账号密码脱敏，将账号密码改为***:***"""
    return _RTSP_CREDENTIALS.sub(r"\1***:***@", value)

def probe_video_shape(
    url: str,
    *,
    timeout_seconds: float = FFPROBE_TIMEOUT_SECONDS,
) -> tuple[int, int, int]:
    """用ffprobe读取摄像头第一路视频流的宽、高，然后返回(H,W,3)"""
    # ffprobe很适合做视频编码、分辨率、帧率、音视频信息元数据探测
    command = [
        "ffprobe",
        "-v",
        "error",            # -v error:只输出错误
        "-rtsp_transport",  
        "tcp",              # -rtsp_transport tcp: RTSP用TCP传输
        "-select_streams",
        "v:0",              # -select_streams v:0: 第一条视频流
        "-show_entries",
        "stream=width,height",   # 只取宽、高
        "-of",
        "json",      # -of json : 要求ffprobe输出json格式
        url,
    ]
    try:
        # Python启动一个ffprobe字进程，并等待结果
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    # 三类启动异常
    # 1、ffprobe没装
    except FileNotFoundError as exc:
        raise CameraProbeError("ffprobe 未安装，无法探测摄像头") from exc
    # 2、超时
    except subprocess.TimeoutExpired as exc:
        raise CameraProbeError(
            f"ffprobe 探测超时 ({timeout_seconds:g}s)"
        ) from exc
    # 3、系统启动失败，确保及时异常里面带RTSP URL 也不会泄露密码
    except OSError as exc:
        detail = _redact_rtsp_credentials(str(exc))
        raise CameraProbeError(f"无法启动 ffprobe: {detail}") from exc
    # 启动成功但返回失败
    if result.returncode != 0:
        detail = _redact_rtsp_credentials(result.stderr.strip())
        if not detail:
            detail = f"退出码 {result.returncode}"
        raise CameraProbeError(f"ffprobe 探测失败: {detail[:300]}")      # 最多保留300个字符，避免错误信息太长 

    try:
        # 解析JSON
        payload = json.loads(result.stdout)
    # 如果输出不是合法JSON就报输出无效
    except (TypeError, json.JSONDecodeError) as exc:
        raise CameraProbeError("ffprobe 输出无效: 不是 JSON") from exc
    # 找第一条视频流
    streams = payload.get("streams") if isinstance(payload, dict) else None
    stream = streams[0] if isinstance(streams, list) and streams else None
    if not isinstance(stream, dict):
        raise CameraProbeError("ffprobe 输出无效: 未找到视频流")
    # 取宽高
    width = stream.get("width")
    height = stream.get("height")
    if (
        # 严格校验
        not isinstance(width, int)
        or isinstance(width, bool)
        or width <= 0
        or not isinstance(height, int)
        or isinstance(height, bool)
        or height <= 0
    ):
        raise CameraProbeError("ffprobe 输出无效: 视频宽高非法")

    return height, width, 3
