"""Probe camera stream metadata in an isolated ffprobe subprocess."""
from __future__ import annotations

import json
import re
import subprocess

FFPROBE_TIMEOUT_SECONDS = 8.0
_RTSP_CREDENTIALS = re.compile(r"(rtsp://)[^/@\s]+@")


class CameraProbeError(RuntimeError):
    """A safe, expected failure while probing camera metadata."""


def _redact_rtsp_credentials(value: str) -> str:
    return _RTSP_CREDENTIALS.sub(r"\1***:***@", value)


def probe_video_shape(
    url: str,
    *,
    timeout_seconds: float = FFPROBE_TIMEOUT_SECONDS,
) -> tuple[int, int, int]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        url,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CameraProbeError("ffprobe 未安装，无法探测摄像头") from exc
    except subprocess.TimeoutExpired as exc:
        raise CameraProbeError(
            f"ffprobe 探测超时 ({timeout_seconds:g}s)"
        ) from exc
    except OSError as exc:
        detail = _redact_rtsp_credentials(str(exc))
        raise CameraProbeError(f"无法启动 ffprobe: {detail}") from exc

    if result.returncode != 0:
        detail = _redact_rtsp_credentials(result.stderr.strip())
        if not detail:
            detail = f"退出码 {result.returncode}"
        raise CameraProbeError(f"ffprobe 探测失败: {detail[:300]}")

    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CameraProbeError("ffprobe 输出无效: 不是 JSON") from exc

    streams = payload.get("streams") if isinstance(payload, dict) else None
    stream = streams[0] if isinstance(streams, list) and streams else None
    if not isinstance(stream, dict):
        raise CameraProbeError("ffprobe 输出无效: 未找到视频流")

    width = stream.get("width")
    height = stream.get("height")
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or width <= 0
        or not isinstance(height, int)
        or isinstance(height, bool)
        or height <= 0
    ):
        raise CameraProbeError("ffprobe 输出无效: 视频宽高非法")

    return height, width, 3
