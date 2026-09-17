# 文件说明：包含告警的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

import importlib
import os
import subprocess
import threading
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("DATA_PATH", "/tmp/aivision-test-data")
os.environ.setdefault("MYSQL_DB_URL", "127.0.0.1")
os.environ.setdefault("MYSQL_DB_USER", "test")
os.environ.setdefault("MYSQL_DB_PASSWORD", "test")
os.environ.setdefault("MYSQL_DB_NAME", "test")
AlarmEvidenceRecorder = importlib.import_module(
    "AiVision.alarms.evidence.evidence_recorder"
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
    recorder.stop()


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


def test_video_workers_and_total_tasks_are_bounded(tmp_path, monkeypatch):
    module = importlib.import_module("AiVision.alarms.evidence.evidence_recorder")
    monkeypatch.setattr(module.settings.storage, "alarm_clip_max_tasks", 3)
    monkeypatch.setattr(module.settings.storage, "alarm_clip_workers", 2)
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True, post_seconds=0)
    release = threading.Event()
    both_started = threading.Event()
    lock = threading.Lock()
    active = 0
    peak = 0
    completed = []

    def slow_write(task):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                both_started.set()
        assert release.wait(3)
        with lock:
            active -= 1
            completed.append(task.video_path)

    monkeypatch.setattr(recorder, "_finish_task", slow_write)
    try:
        paths = [recorder.start_alarm("camera-1", _frame(1)) for _ in range(3)]
        assert all(paths)
        assert both_started.wait(3)
        for _ in range(50):
            assert recorder.start_alarm("camera-1", _frame(1)) is None
        assert len(recorder._writer_threads) == 2
        assert recorder._write_queue.qsize() == 1
    finally:
        release.set()
        recorder.stop()
    assert sorted(completed) == sorted(paths)
    assert peak == 2
    assert not recorder._writer_threads
    assert recorder._write_queue.unfinished_tasks == 0


def test_pending_post_frames_share_capacity_and_stop_drains_them(tmp_path, monkeypatch):
    module = importlib.import_module("AiVision.alarms.evidence.evidence_recorder")
    monkeypatch.setattr(module.settings.storage, "alarm_clip_max_tasks", 2)
    completed = []
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True, post_seconds=10)
    monkeypatch.setattr(recorder, "_finish_task", lambda task: completed.append(task.video_path))
    paths = [recorder.start_alarm("camera-1", _frame(1)) for _ in range(2)]
    assert all(paths)
    assert recorder.start_alarm("camera-2", _frame(2)) is None
    recorder.stop()
    assert sorted(completed) == sorted(paths)
    assert not recorder._tasks
    assert not recorder._buffers
    assert recorder.start_alarm("camera-1", _frame(1)) is None
    assert recorder.record_frame("camera-1", _frame(1)) is False
    recorder.start(lambda: {})
    assert recorder.start_alarm("camera-1", _frame(1)) is not None
    recorder.stop()
    assert len(completed) == 3


def test_default_clip_preserves_ten_seconds_either_side_fps_and_width(tmp_path, monkeypatch):
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True)
    assert (recorder.pre_seconds, recorder.post_seconds, recorder.fps, recorder.max_width) == (10, 10, 5, 960)
    completed = []
    monkeypatch.setattr(recorder, "_finish_task", lambda task: completed.append(task))
    frame = np.zeros((200, 1280, 3), dtype=np.uint8)
    for tick in range(51):
        recorder.record_frame("camera-1", frame, tick * 0.201)
    recorder.start_alarm("camera-1", timestamp=50 * 0.201)
    for tick in range(51, 101):
        recorder.record_frame("camera-1", frame, tick * 0.201)
    recorder.stop()
    assert len(completed) == 1
    assert len(completed[0].frames) == 100
    assert recorder._decode_frame(completed[0].frames[0]).shape == (150, 960, 3)


def test_failed_clip_releases_slot_and_reports_status(tmp_path, monkeypatch):
    module = importlib.import_module("AiVision.alarms.evidence.evidence_recorder")
    monkeypatch.setattr(module.settings.storage, "alarm_clip_max_tasks", 1)
    statuses = []
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True, post_seconds=0, status_callback=lambda *args: statuses.append(args))
    first = recorder.start_alarm("empty-1")
    recorder._write_queue.join()
    second = recorder.start_alarm("empty-2")
    recorder.stop()
    assert first and second
    assert statuses == [(first, "failed"), (second, "failed")]


def test_unexpected_encoding_error_keeps_worker_alive(tmp_path, monkeypatch):
    module = importlib.import_module("AiVision.alarms.evidence.evidence_recorder")
    monkeypatch.setattr(module.settings.storage, "alarm_clip_max_tasks", 1)
    statuses = []
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True, post_seconds=0, status_callback=lambda *args: statuses.append(args))

    def broken_encoder(task):
        raise RuntimeError("encoder failure")

    monkeypatch.setattr(recorder, "_finish_task", broken_encoder)
    first = recorder.start_alarm("camera-1", _frame(1))
    recorder._write_queue.join()
    assert all(worker.is_alive() for worker in recorder._writer_threads)
    second = recorder.start_alarm("camera-1", _frame(2))
    recorder.stop()
    assert first and second
    assert statuses == [(first, "failed"), (second, "failed")]


def test_episode_preserves_complete_stream_beyond_pre_and_post_window(tmp_path, monkeypatch):
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True, pre_seconds=1, post_seconds=1, fps=1)
    captured = []
    monkeypatch.setattr(recorder, "_finish_task", lambda task: captured.append([
        int(recorder._decode_frame(frame)[0, 0, 0]) for frame in recorder._task_frames(task)]))
    recorder.record_frame("inspection-line", _frame(10), 0.)
    token = recorder.begin_episode("inspection-line", _frame(20), 1.)
    task = recorder._episodes[token]
    for tick in range(2, 11):
        recorder.record_frame("inspection-line", _frame(20 + tick), float(tick))
    assert not captured and not task.frames
    assert len(recorder._buffers["inspection-line"]) == 2
    path = recorder.finish_episode(token)
    assert path and recorder.finish_episode(token) is None
    recorder.stop()
    assert captured == [[10, 20, *range(22, 31)]]
    assert task.spool.closed


def test_episode_finish_uses_shared_video_writer_and_status_callback(tmp_path):
    statuses = []
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True, pre_seconds=0, fps=1,
                                     status_callback=lambda *args: statuses.append(args))
    token = recorder.begin_episode("process-batch", _frame(10), 0.)
    for tick in range(1, 4):
        recorder.record_frame("process-batch", _frame(20 + tick), float(tick))
    video_path = recorder.finish_episode(token)
    recorder.stop()
    assert statuses == [(video_path, "ready")]
    capture = cv2.VideoCapture(video_path)
    try:
        assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 4
    finally:
        capture.release()


def test_episode_cancel_and_stop_release_shared_capacity_without_video(tmp_path, monkeypatch):
    module = importlib.import_module("AiVision.alarms.evidence.evidence_recorder")
    monkeypatch.setattr(module.settings.storage, "alarm_clip_max_tasks", 1)
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True)
    token = recorder.begin_episode("a", _frame(1))
    spool = recorder._episodes[token].spool
    assert recorder.begin_episode("b", _frame(2)) is None
    assert recorder.start_alarm("b", _frame(2)) is None
    assert recorder.cancel_episode(token) and spool.closed
    assert not recorder.cancel_episode(token)
    second = recorder.begin_episode("b", _frame(2))
    assert second
    second_spool = recorder._episodes[second].spool
    recorder.stop()
    assert second_spool.closed and not recorder._episodes and not recorder._writer_threads
    assert not list(recorder.output_dir.iterdir())
    assert recorder.begin_episode("c", _frame(3)) is None


def test_episode_sources_are_isolated(tmp_path, monkeypatch):
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True, pre_seconds=0, fps=1)
    captured = {}
    monkeypatch.setattr(recorder, "_finish_task", lambda task: captured.update({task.source_key: [
        int(recorder._decode_frame(frame)[0, 0, 0]) for frame in recorder._task_frames(task)]}))
    first = recorder.begin_episode("line-a", _frame(10), 0.)
    second = recorder.begin_episode("line-b", _frame(20), 0.)
    recorder.record_frame("line-b", _frame(30), 1.)
    recorder.finish_episode(first)
    recorder.finish_episode(second)
    recorder.stop()
    assert captured == {"line-a": [10], "line-b": [20, 30]}


def test_episode_disk_failure_cancels_incomplete_evidence_and_releases_slot(tmp_path, monkeypatch):
    module = importlib.import_module("AiVision.alarms.evidence.evidence_recorder")
    monkeypatch.setattr(module.settings.storage, "alarm_clip_max_tasks", 1)
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True, fps=1)
    token = recorder.begin_episode("a", _frame(1), 0.)
    spool = recorder._episodes[token].spool

    def disk_full(*args):
        raise OSError("disk full")

    with monkeypatch.context() as context:
        context.setattr(recorder, "_append_episode_frame", disk_full)
        recorder.record_frame("a", _frame(2), 1.)
    assert token not in recorder._episodes and spool.closed
    assert recorder.finish_episode(token) is None
    assert recorder.begin_episode("b", _frame(3), 2.)
    recorder.stop()


def test_corrupt_episode_is_failed_and_does_not_kill_writer(tmp_path, monkeypatch):
    module = importlib.import_module("AiVision.alarms.evidence.evidence_recorder")
    monkeypatch.setattr(module.settings.storage, "alarm_clip_max_tasks", 1)
    statuses = []
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True, status_callback=lambda *args: statuses.append(args))
    token = recorder.begin_episode("a")
    spool = recorder._episodes[token].spool
    spool.write(b"\x00\x00\x00\x10short")
    path = recorder.finish_episode(token)
    recorder._write_queue.join()
    assert statuses == [(path, "failed")] and spool.closed
    assert all(worker.is_alive() for worker in recorder._writer_threads)
    assert recorder.begin_episode("b")
    recorder.stop()


def test_clear_source_finishes_clips_cancels_episodes_and_keeps_other_sources(tmp_path, monkeypatch):
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True)
    completed = []
    monkeypatch.setattr(recorder, "_finish_task", lambda task: completed.append(task.video_path))
    clip = recorder.start_alarm("a", _frame(1))
    first = recorder.begin_episode("a")
    second = recorder.begin_episode("b", _frame(2))
    recorder.clear_source("a")
    recorder._write_queue.join()
    assert completed == [clip]
    assert first not in recorder._episodes and second in recorder._episodes
    assert "a" not in recorder._buffers and "a" not in recorder._last_sample
    assert "b" in recorder._buffers
    recorder.stop()


def test_clip_deadline_finishes_without_new_source_frames(tmp_path, monkeypatch):
    clock, completed = [0.], threading.Event()
    recorder = AlarmEvidenceRecorder(tmp_path, enabled=True, post_seconds=1, clock=lambda: clock[0])
    monkeypatch.setattr(recorder, "_finish_task", lambda task: completed.set())
    recorder.start(lambda: {})
    try:
        assert recorder.start_alarm("offline-soon", _frame(1))
        clock[0] = 2.
        assert completed.wait(2)
        assert not recorder._tasks
    finally:
        recorder.stop()
