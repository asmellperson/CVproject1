# 文件说明：包含告警的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("DATA_PATH", "/tmp/aivision-test-data")
os.environ.setdefault("MYSQL_DB_URL", "127.0.0.1")
os.environ.setdefault("MYSQL_DB_USER", "test")
os.environ.setdefault("MYSQL_DB_PASSWORD", "test")
os.environ.setdefault("MYSQL_DB_NAME", "test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.pop("platform", None)

AlarmEvidenceRecorder = importlib.import_module(
    "platform.violation.evidence_recorder"
).AlarmEvidenceRecorder


# 功能：实现 `_frame` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（int）：待转换、校验或写入的值
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_alarm_evidence_recorder.py` 的 `test_recorder_keeps_pre_and_post_alarm_frames`
#         调用本符号；`AiVision/tests/test_alarm_evidence_recorder.py` 的 `test_recorder_throttles_samples_and_discards_expired_prebuffer`
#         调用本符号
#   - 内部调用：`np.full`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _frame(value: int) -> np.ndarray:
    return np.full((24, 32, 3), value, dtype=np.uint8)


# 功能：验证 `test_recorder_keeps_pre_and_post_alarm_frames` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AlarmEvidenceRecorder`、`statuses.append`、`recorder.record_frame`、`_frame`、`recorder.start_alarm`、`range`、`time.sleep`、`Path(video_path).is_file`、`Path`、`subprocess.run(['ffprobe',
#          '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name', '-of',
#          'default=nokey=1:noprint_wrappers=1', video_path], capture_output=True, check=True, text=True).stdout.strip` 等共 15 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_recorder_keeps_pre_and_post_alarm_frames(tmp_path):
    statuses = []
    recorder = AlarmEvidenceRecorder(
        tmp_path,
        enabled=True,
        pre_seconds=2,
        post_seconds=1,
        fps=2,
        max_width=32,
        status_callback=lambda path, status: statuses.append((path, status)),
    )

    recorder.record_frame("camera-1", _frame(10), 1.0)
    recorder.record_frame("camera-1", _frame(20), 2.0)
    recorder.record_frame("camera-1", _frame(30), 3.0)
    video_path = recorder.start_alarm("camera-1", _frame(40), 3.5)
    recorder.record_frame("camera-1", _frame(50), 4.0)
    recorder.record_frame("camera-1", _frame(60), 4.5)

    assert video_path is not None
    for _attempt in range(100):
        if statuses:
            break
        import time

        time.sleep(0.01)

    assert statuses == [(video_path, "ready")]
    assert Path(video_path).is_file()
    codec = subprocess.run(
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
            video_path,
        ],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    assert codec == "h264"
    capture = cv2.VideoCapture(video_path)
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    assert frame_count >= 4


# 功能：验证 `test_recorder_throttles_samples_and_discards_expired_prebuffer` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AlarmEvidenceRecorder`、`recorder.record_frame`、`_frame`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_recorder_throttles_samples_and_discards_expired_prebuffer(tmp_path):
    recorder = AlarmEvidenceRecorder(
        tmp_path,
        enabled=True,
        pre_seconds=1,
        post_seconds=1,
        fps=2,
        max_width=32,
    )

    assert recorder.record_frame("camera-1", _frame(10), 1.0) is True
    assert recorder.record_frame("camera-1", _frame(20), 1.1) is False
    assert recorder.record_frame("camera-1", _frame(30), 3.0) is True

    buffered = recorder._buffers["camera-1"]
    assert len(buffered) == 1
    assert buffered[0][0] == 3.0
