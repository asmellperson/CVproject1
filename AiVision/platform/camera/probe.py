# 文件说明：实现`probe` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""Probe camera stream metadata in an isolated ffprobe subprocess."""
from __future__ import annotations

import json
import re
import subprocess

FFPROBE_TIMEOUT_SECONDS = 8.0
_RTSP_CREDENTIALS = re.compile(r"(rtsp://)[^/@\s]+@")


# 功能：A safe, expected failure while probing camera metadata；输入与输出详见下方说明
# 参数：无。
# 返回：CameraProbeError；返回新建的 `CameraProbeError` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/camera/probe.py` 的 `probe_video_shape` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraProbeError(RuntimeError):
    """A safe, expected failure while probing camera metadata."""


# 功能：实现 `_redact_rtsp_credentials` 对应的`probe` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（str）：待转换、校验或写入的值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/camera/probe.py` 的 `probe_video_shape` 调用本符号
#   - 内部调用：`_RTSP_CREDENTIALS.sub`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _redact_rtsp_credentials(value: str) -> str:
    return _RTSP_CREDENTIALS.sub(r"\1***:***@", value)


# 功能：实现 `probe_video_shape` 对应的`probe` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `url`（str）：目标接口、媒体流或页面地址
#   - `timeout_seconds`（float）：`timeout_seconds` 对应的时间间隔或时长；默认值为 `FFPROBE_TIMEOUT_SECONDS`
# 返回：tuple[int, int, int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`subprocess.run`、`CameraProbeError`、`_redact_rtsp_credentials`、`str`、`result.stderr.strip`、`json.loads`、`isinstance`、`payload.get`、`stream.get`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
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
