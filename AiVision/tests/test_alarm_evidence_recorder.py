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


def _frame(value: int) -> np.ndarray:
    return np.full((24, 32, 3), value, dtype=np.uint8)


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
