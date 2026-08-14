"""Browser-compatible alarm video encoding helpers."""
from __future__ import annotations

import os
import subprocess
import threading
import uuid
from pathlib import Path


class VideoEncodingError(RuntimeError):
    """Raised when an alarm video cannot be converted for browser playback."""


_TRANSCODE_LOCK = threading.Lock()


def _run(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise VideoEncodingError(f"{command[0]} 未安装，无法生成浏览器兼容视频") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoEncodingError(f"{command[0]} 处理视频超时") from exc
    except OSError as exc:
        raise VideoEncodingError(f"无法启动 {command[0]}: {exc}") from exc


def _video_codec(path: Path) -> str | None:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(path),
        ],
        timeout=10,
    )
    if result.returncode != 0:
        return None
    codec = result.stdout.strip().lower()
    return codec or None


def ensure_browser_compatible_mp4(video_path: str | Path) -> Path:
    """Ensure an MP4 uses H.264/yuv420p and is suitable for HTML video playback.

    Existing H.264 files are returned unchanged. Other codecs are transcoded to
    a temporary sibling and atomically replace the source only after FFmpeg
    succeeds, so an interrupted conversion cannot corrupt the alarm evidence.
    """
    path = Path(video_path).expanduser().resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise VideoEncodingError(f"报警视频不存在或为空: {path}")

    with _TRANSCODE_LOCK:
        if _video_codec(path) == "h264":
            return path

        temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.browser.mp4")
        try:
            result = _run(
                [
                    "ffmpeg",
                    "-y",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-an",
                    "-vf",
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(temporary),
                ],
                timeout=120,
            )
            if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
                detail = (result.stderr or result.stdout or "未知错误").strip()[:500]
                raise VideoEncodingError(f"报警视频 H.264 转码失败: {detail}")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    return path
