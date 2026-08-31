# 文件说明：实现`video_encoding` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""Browser-compatible alarm video encoding helpers."""
from __future__ import annotations

import os
import subprocess
import threading
import uuid
from pathlib import Path


# 功能：Raised when an alarm video cannot be converted for browser playback；输入与输出详见下方说明
# 参数：无。
# 返回：VideoEncodingError；返回新建的 `VideoEncodingError` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/video_encoding.py` 的 `_run` 实例化本符号；`AiVision/core/video_encoding.py` 的 `ensure_browser_compatible_mp4`
#         实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class VideoEncodingError(RuntimeError):
    """Raised when an alarm video cannot be converted for browser playback."""


_TRANSCODE_LOCK = threading.Lock()


# 功能：启动或执行 `_run` 对应的`video_encoding` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `command`（list[str]）：`command` 对应的业务输入值
#   - `timeout`（float）：允许操作等待的最长秒数
# 返回：subprocess.CompletedProcess[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`subprocess.run`、`VideoEncodingError`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
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


# 功能：实现 `_video_codec` 对应的`video_encoding` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
# 返回：str | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/core/video_encoding.py` 的 `ensure_browser_compatible_mp4` 调用本符号
#   - 内部调用：`_run`、`str`、`result.stdout.strip().lower`、`result.stdout.strip`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：Ensure an MP4 uses H.264/yuv420p and is suitable for HTML video playback；输入与输出详见下方说明
# 参数：
#   - `video_path`（str | Path）：`video_path` 对应的业务输入值
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/violation/evidence_recorder.py` 的 `AlarmEvidenceRecorder::_finish_task`
#         调用本符号；`AiVision/integrations/guard_room/src/server.py` 的 `create_app::get_site_alarm_video`
#         调用本符号；`AiVision/integrations/guard_room/src/server.py` 的 `create_app::get_alarm_video` 调用本符号；`AiVision/api/v2/alarms.py` 的
#         `alarm_video` 调用本符号
#   - 内部调用：`Path(video_path).expanduser().resolve`、`Path(video_path).expanduser`、`Path`、`path.is_file`、`path.stat`、`VideoEncodingError`、`_video_codec`、`path.with_name`、`uuid.uuid4`、`_run`
#          等共 16 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
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
