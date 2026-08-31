#!/usr/bin/env python3
# 文件说明：实现`build-overview-mascot` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""Build the transparent overview mascot WebM and final-pose PNG."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import cv2
import numpy as np


OUTPUT_SIZE = (600, 544)


# 功能：读取或查询 `read_video_metadata` 对应的`build-overview-mascot` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `source`（Path）：`source` 对应的业务输入值
# 返回：tuple[float, int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_frontend/scripts/build-overview-mascot.py` 的 `convert` 调用本符号
#   - 内部调用：`cv2.VideoCapture`、`str`、`capture.isOpened`、`RuntimeError`、`capture.get`、`int`、`capture.release`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
def read_video_metadata(source: Path) -> tuple[float, int]:
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频：{source}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.release()
    return fps, frame_count


# 功能：实现 `connected_subject` 对应的`build-overview-mascot` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `candidate`（np.ndarray）：`candidate` 对应的业务输入值
#   - `strong`（np.ndarray）：`strong` 对应的业务输入值
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_frontend/scripts/build-overview-mascot.py` 的 `build_alpha` 调用本符号
#   - 内部调用：`cv2.connectedComponentsWithStats`、`np.zeros_like`、`range`、`np.count_nonzero`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def connected_subject(candidate: np.ndarray, strong: np.ndarray) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
    subject = np.zeros_like(candidate)
    for label in range(1, count):
        area = stats[label, cv2.CC_STAT_AREA]
        if area < 180:
            continue
        component = labels == label
        if np.count_nonzero(strong[component]) >= 24:
            subject[component] = 255
    return subject


# 功能：创建或构建 `build_alpha` 对应的`build-overview-mascot` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `frame`（np.ndarray）：待处理的视频图像帧
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_frontend/scripts/build-overview-mascot.py` 的 `convert` 调用本符号
#   - 内部调用：`cv2.cvtColor`、`((saturation < 46) & (value >
#          132)).astype`、`cv2.connectedComponents`、`np.unique`、`np.concatenate`、`np.isin`、`np.where(external_background, 0,
#          255).astype`、`np.where`、`((saturation > 52) | (value < 96)).astype`、`cv2.morphologyEx` 等共 13 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def build_alpha(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    background_like = ((saturation < 46) & (value > 132)).astype(np.uint8)
    _, background_labels = cv2.connectedComponents(background_like, 8)
    border_labels = np.unique(np.concatenate((
        background_labels[0],
        background_labels[-1],
        background_labels[:, 0],
        background_labels[:, -1],
    )))
    border_labels = border_labels[border_labels != 0]
    external_background = np.isin(background_labels, border_labels)
    candidate = np.where(external_background, 0, 255).astype(np.uint8)
    strong = ((saturation > 52) | (value < 96)).astype(np.uint8) * 255

    candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    subject = connected_subject(candidate, strong)

    subject = cv2.morphologyEx(subject, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    alpha = cv2.GaussianBlur(subject, (0, 0), 1.1)
    alpha[alpha < 12] = 0
    return alpha


# 功能：处理 `place_on_canvas` 对应的`build-overview-mascot` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `frame`（np.ndarray）：待处理的视频图像帧
#   - `alpha`（np.ndarray）：`alpha` 对应的业务输入值
#   - `center_x`（float）：`center_x` 对应的业务输入值
# 返回：tuple[np.ndarray, np.ndarray]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_frontend/scripts/build-overview-mascot.py` 的 `convert` 调用本符号
#   - 内部调用：`min`、`max`、`int`、`round`、`np.zeros`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def place_on_canvas(frame: np.ndarray, alpha: np.ndarray, center_x: float) -> tuple[np.ndarray, np.ndarray]:
    canvas_width, canvas_height = OUTPUT_SIZE
    source_height, source_width = alpha.shape
    center_x = min(max(center_x, canvas_width / 2), source_width - canvas_width / 2)
    left = int(round(center_x - canvas_width / 2))
    right = left + canvas_width

    cropped_frame = frame[:canvas_height, left:right]
    cropped_alpha = alpha[:canvas_height, left:right]
    canvas = np.zeros((canvas_height, canvas_width, 4), dtype=np.uint8)
    canvas[:cropped_frame.shape[0], :cropped_frame.shape[1], :3] = cropped_frame
    canvas[:cropped_alpha.shape[0], :cropped_alpha.shape[1], 3] = cropped_alpha
    return canvas, cropped_alpha


# 功能：转换或规范化 `convert` 对应的`build-overview-mascot` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `source`（Path）：`source` 对应的业务输入值
#   - `output_dir`（Path）：`output_dir` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_frontend/scripts/build-overview-mascot.py` 的 `main` 调用本符号
#   - 内部调用：`read_video_metadata`、`output_dir.mkdir`、`str`、`subprocess.Popen`、`RuntimeError`、`cv2.VideoCapture`、`capture.read`、`build_alpha`、`cv2.findNonZero`、`cv2.boundingRect`
#          等共 20 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
def convert(source: Path, output_dir: Path) -> None:
    fps, expected_frames = read_video_metadata(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    webm_path = output_dir / "overview-mascot-alpha.webm"
    final_pose_path = output_dir / "overview-mascot-final.png"

    width, height = OUTPUT_SIZE
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}",
        "-r", f"{fps:.6f}", "-i", "-", "-an",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
        "-crf", "24", "-b:v", "0", "-auto-alt-ref", "0",
        str(webm_path),
    ]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
    if encoder.stdin is None:
        raise RuntimeError("无法启动 FFmpeg 编码器")

    capture = cv2.VideoCapture(str(source))
    smoothed_center: float | None = None
    last_canvas: np.ndarray | None = None
    written = 0
    try:
        while True:
            ok, raw_frame = capture.read()
            if not ok:
                break
            frame = raw_frame[:, 6:-6]
            alpha = build_alpha(frame)
            points = cv2.findNonZero(alpha)
            detected_center = frame.shape[1] / 2 if points is None else cv2.boundingRect(points)[0] + cv2.boundingRect(points)[2] / 2
            smoothed_center = detected_center if smoothed_center is None else smoothed_center * 0.72 + detected_center * 0.28
            canvas, _ = place_on_canvas(frame, alpha, smoothed_center)
            rgba = cv2.cvtColor(canvas, cv2.COLOR_BGRA2RGBA)
            encoder.stdin.write(rgba.tobytes())
            last_canvas = canvas
            written += 1
    finally:
        capture.release()
        encoder.stdin.close()
        return_code = encoder.wait()

    if return_code != 0:
        raise RuntimeError(f"FFmpeg 编码失败，退出码：{return_code}")
    if written == 0 or last_canvas is None:
        raise RuntimeError("没有生成任何透明帧")
    if expected_frames and abs(written - expected_frames) > 1:
        raise RuntimeError(f"帧数不完整：期望 {expected_frames}，实际 {written}")
    if not cv2.imwrite(str(final_pose_path), last_canvas):
        raise RuntimeError(f"无法写入末帧：{final_pose_path}")
    print(f"已生成 {webm_path}（{written} 帧，{fps:.2f} FPS）")
    print(f"已生成 {final_pose_path}")


# 功能：实现 `main` 对应的`build-overview-mascot` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`argparse.ArgumentParser`、`parser.add_argument`、`parser.parse_args`、`convert`、`args.source.resolve`、`args.output_dir.resolve`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    convert(args.source.resolve(), args.output_dir.resolve())


if __name__ == "__main__":
    main()
