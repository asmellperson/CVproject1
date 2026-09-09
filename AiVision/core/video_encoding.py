"""确保生成的告警MP4能被浏览器<video>正常播放
主要依赖于系统两个指令：ffprobe(检查视频编码格式)
                       ffmpeg（必要时重新编码）
"""
from __future__ import annotations

import os
import subprocess
import threading
import uuid
from pathlib import Path


class VideoEncodingError(RuntimeError):
    """视频检查或者转码失败时的统一抛出的业务异常（例如ffmpeg没安装、ffprobe没安装、视频为空、转码超时、ffmpeg执行失败）"""

# 同一个AiVision进程里，一次只允许一个视频进入转码流程（这个锁是全局锁，不是按视频文件加锁）
_TRANSCODE_LOCK = threading.Lock()

def _run(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """统一执行ffmpeg/ffprobe命令的封装"""
    try:
        # subprocess.run()：python启动一个外部程序，然后等待它执行结束
        return subprocess.run(
            command,
            capture_output=True,        # 表示把外部程序的stdout和stderr全部抓回Python，后面可以result.stdout和result.sterr读取FFmpeg输出
            text=True,                  # 因为subprocess默认返回的是bytes，用了text=True，以后result.stdout直接就是str
            timeout=timeout,
            check=False,                # 外部程序失败时不要自动抛calledProcessError，而是由代码自己检查result.returncode
        )
    # ffmpeg没安装的异常
    except FileNotFoundError as exc:
        raise VideoEncodingError(f"{command[0]} 未安装，无法生成浏览器兼容视频") from exc
    # ffmpeg处理超时的异常
    except subprocess.TimeoutExpired as exc:
        raise VideoEncodingError(f"{command[0]} 处理视频超时") from exc
    # 无法启动ffmpeg的异常
    except OSError as exc:
        raise VideoEncodingError(f"无法启动 {command[0]}: {exc}") from exc


def _video_codec(path: Path) -> tuple[str | None, str | None]:
    """检查这个视频的第一路视频流到底是什么编码，调用的是ffprobe"""
    # 只拿一个结果：h264或者hevc
    result = _run(
        [
            "ffprobe",
            "-v",                   # video
            "error",
            "-select_streams",
            "v:0",                  # 第一条视频流
            "-show_entries",
            "stream=codec_name,pix_fmt",    # 只查询编码的名字
            "-of",
            "default=nokey=0:noprint_wrappers=1",
            str(path),
        ],
        timeout=10,
    )
    # ffprobe失败，表示无法确认当前编码，主函数会当成不确定性兼容，重新转码
    if result.returncode != 0:
        return None, None
    stream_info = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            stream_info[key.strip()] = value.strip().lower()
    codec = stream_info.get("codec_name") or None
    pixel_format = stream_info.get("pix_fmt") or None
    return codec, pixel_format

def ensure_browser_compatible_mp4(video_path: str | Path) -> Path:
    """
    主函数，真正对外提供的功能
    确保MP4是浏览器兼容格式
    """
    # 规范路径，变成完整绝对路径
    path = Path(video_path).expanduser().resolve()
    # 视频文件必须存在并且不是空文件
    if not path.is_file() or path.stat().st_size <= 0:
        raise VideoEncodingError(f"报警视频不存在或为空: {path}")
    # 获取转码锁
    with _TRANSCODE_LOCK:
        # 已经是H.264就直接返回
        if _video_codec(path) == ("h264", "yuv420p"):
            return path
        # 创建临时文件，之后成功确认后在替换原视频
        temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.browser.mp4")
        try:
            # FFmpeg命令
            result = _run(
                [
                    "ffmpeg",
                    "-y",                  # 如果输出文件已经存在，直接覆盖，不询问
                    "-nostdin",            # FFmpeg不要等待终端输入
                    "-hide_banner",        # 不打印FFmpeg版本、编译参数等一大堆启动信息·
                    "-loglevel",          
                    "error",               # 只输出错误级别日志
                    "-i",                  # 输入视频
                    str(path),
                    "-an",                 # 删除音频（最终输出只有画面没有声音的视频）
                    "-vf",
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2", # 把视频和高都强制调整成偶数（因为H.264+yuv420p通常要求宽、高都满足偶数尺寸）
                    "-c:v",
                    "libx264",                          # 明确指定H.264编码
                    "-preset",                          
                    "veryfast",                         # H.264编码速度/压缩率的权衡（实时业务速度优先）
                    "-crf",                             
                    "23",                               # CRF 控制H.264画质
                    "-pix_fmt",
                    "yuv420p",                          # 浏览器兼容设置，某些H.264视频可能编码成yuv444p yuv4222p，但是部门浏览器的兼容性会差，而H.264 + yuv420p是Web视频很常见的兼容组合
                    "-movflags",
                    "+faststart",                       # 网页播放的优化，MP4里有一块关键元数据叫moov atom，默认有时候在文件结尾，faststart会把这部分元数据移到前面
                    str(temporary),
                ],
                timeout=120,                           # 转码最多120秒
            )
            # 转码成功判断（FFmpeg返回成功 + 临时文件存在 + 文件大小>0）,缺一个都认为失败
            if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
                # 转码失败信息，优先取stderr、没有在stdout避免错误日志特别长
                detail = (result.stderr or result.stdout or "未知错误").strip()[:500]
                raise VideoEncodingError(f"报警视频 H.264 转码失败: {detail}")
            # 用新的转码文件替换原文件（alarm.mp4 -> .tmp.brower.mp4 -> 替换alarm.mp4）
            os.replace(temporary, path)
        finally:
            # 清理临时文件
            temporary.unlink(missing_ok=True)

    return path
