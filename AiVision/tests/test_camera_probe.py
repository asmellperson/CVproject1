# 文件说明：包含摄像头的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import importlib
import threading
import json
import subprocess
import os
import multiprocessing
import queue
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import numpy as np
import pytest



# 功能：实现 `_probe_module` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_camera_probe.py` 的 `test_probe_video_shape_returns_bgr_shape`
#         调用本符号；`AiVision/tests/test_camera_probe.py` 的 `test_probe_video_shape_uses_bounded_ffprobe_command`
#         调用本符号；`AiVision/tests/test_camera_probe.py` 的 `test_probe_video_shape_reports_missing_ffprobe`
#         调用本符号；`AiVision/tests/test_camera_probe.py` 的 `test_probe_video_shape_reports_timeout_without_url` 调用本符号；另有 3 处静态调用
#   - 内部调用：`importlib.import_module`、`pytest.fail`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _probe_module():
    try:
        return importlib.import_module("AiVision.platform.camera.probe")
    except ModuleNotFoundError:
        pytest.fail("AiVision.platform.camera.probe API is missing")


# 功能：验证 `test_probe_video_shape_returns_bgr_shape` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_probe_module`、`SimpleNamespace`、`json.dumps`、`monkeypatch.setattr`、`probe.probe_video_shape`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_probe_video_shape_returns_bgr_shape(monkeypatch):
    probe = _probe_module()
    completed = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"streams": [{"width": 1920, "height": 1080}]}),
        stderr="",
    )
    monkeypatch.setattr(probe.subprocess, "run", lambda *args, **kwargs: completed)

    assert probe.probe_video_shape("rtsp://camera/stream") == (1080, 1920, 3)


# 功能：验证 `test_probe_video_shape_uses_bounded_ffprobe_command` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_probe_module`、`monkeypatch.setattr`、`probe.probe_video_shape`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_probe_video_shape_uses_bounded_ffprobe_command(monkeypatch):
    probe = _probe_module()
    observed = {}

    # 功能：启动或执行 `fake_run` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `command`（未显式标注）：`command` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`SimpleNamespace`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout='{"streams":[{"width":1280,"height":720}]}',
            stderr="",
        )

    monkeypatch.setattr(probe.subprocess, "run", fake_run)

    probe.probe_video_shape("rtsp://camera/stream", timeout_seconds=4.5)

    assert observed["command"] == [
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
        "rtsp://camera/stream",
    ]
    assert observed["kwargs"] == {
        "capture_output": True,
        "text": True,
        "timeout": 4.5,
        "check": False,
    }


# 功能：验证 `test_probe_video_shape_reports_missing_ffprobe` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_probe_module`、`monkeypatch.setattr`、`pytest.raises`、`probe.probe_video_shape`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_probe_video_shape_reports_missing_ffprobe(monkeypatch):
    probe = _probe_module()

    # 功能：实现 `missing` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`FileNotFoundError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def missing(*args, **kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(probe.subprocess, "run", missing)

    with pytest.raises(probe.CameraProbeError, match="ffprobe 未安装"):
        probe.probe_video_shape("rtsp://camera/stream")


# 功能：验证 `test_probe_video_shape_reports_timeout_without_url` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_probe_module`、`monkeypatch.setattr`、`pytest.raises`、`probe.probe_video_shape`、`str`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_probe_video_shape_reports_timeout_without_url(monkeypatch):
    probe = _probe_module()
    url = "rtsp://admin:secret@camera/stream"

    # 功能：实现 `timeout` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `command`（未显式标注）：`command` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`subprocess.TimeoutExpired`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(probe.subprocess, "run", timeout)

    with pytest.raises(probe.CameraProbeError, match="探测超时") as exc_info:
        probe.probe_video_shape(url)
    assert url not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


# 功能：验证 `test_probe_video_shape_redacts_credentials_from_ffprobe_error` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_probe_module`、`SimpleNamespace`、`monkeypatch.setattr`、`pytest.raises`、`probe.probe_video_shape`、`str`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_probe_video_shape_redacts_credentials_from_ffprobe_error(monkeypatch):
    probe = _probe_module()
    completed = SimpleNamespace(
        returncode=1,
        stdout="",
        stderr="rtsp://admin:secret@camera/stream: Connection refused",
    )
    monkeypatch.setattr(probe.subprocess, "run", lambda *args, **kwargs: completed)

    with pytest.raises(probe.CameraProbeError) as exc_info:
        probe.probe_video_shape("rtsp://admin:secret@camera/stream")
    message = str(exc_info.value)
    assert "admin" not in message
    assert "secret" not in message
    assert "rtsp://***:***@camera/stream" in message


# 功能：验证 `test_probe_video_shape_rejects_invalid_output` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `stdout`（未显式标注）：`stdout` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_probe_module`、`SimpleNamespace`、`monkeypatch.setattr`、`pytest.raises`、`probe.probe_video_shape`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    "stdout",
    [
        "not-json",
        "{}",
        '{"streams":[]}',
        '{"streams":[{"width":0,"height":1080}]}',
        '{"streams":[{"width":1920,"height":-1}]}',
        '{"streams":[{"width":"1920","height":1080}]}',
    ],
)
def test_probe_video_shape_rejects_invalid_output(monkeypatch, stdout):
    probe = _probe_module()
    completed = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(probe.subprocess, "run", lambda *args, **kwargs: completed)

    with pytest.raises(probe.CameraProbeError, match="输出无效"):
        probe.probe_video_shape("rtsp://camera/stream")


# 功能：验证 `test_camera_runtime_probe_failure_does_not_call_opencv` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`importlib.import_module`、`_probe_module`、`monkeypatch.setattr`、`runtime_module.CameraRuntime`、`SimpleNamespace`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_runtime_probe_failure_does_not_call_opencv(monkeypatch):
    runtime_module = importlib.import_module("AiVision.platform.camera.runtime")
    probe = _probe_module()

    # 功能：实现 `fail_probe` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `url`（未显式标注）：目标接口、媒体流或页面地址
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`probe.CameraProbeError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def fail_probe(url):
        raise probe.CameraProbeError("ffprobe 探测超时 (8s)")

    # 功能：实现 `forbidden_opencv_probe` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `url`（未显式标注）：目标接口、媒体流或页面地址
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`pytest.fail`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def forbidden_opencv_probe(url):
        pytest.fail("CameraRuntime must not probe RTSP through OpenCV")

    monkeypatch.setattr(
        runtime_module,
        "probe_video_shape",
        fail_probe,
        raising=False,
    )
    monkeypatch.setattr(
        runtime_module.cv2,
        "VideoCapture",
        forbidden_opencv_probe,
    )

    runtime = runtime_module.CameraRuntime(
        {
            "name": "offline-camera",
            "shm_name": "offline_camera",
            "url": "rtsp://admin:secret@camera/stream",
            "fps": 5,
            "max_restart": 3,
            "enable": True,
        },
        active_index=SimpleNamespace(value=0),
        frame_seq=SimpleNamespace(value=0),
    )

    assert runtime.status is False
    assert runtime.shape == (0, 0, 0)
    assert "ffprobe 探测超时" in runtime.msg
    assert "secret" not in runtime.msg


# 功能：验证 `test_camera_retry_logs_without_sending_a_separate_alert` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`importlib.import_module`、`object.__new__`、`threading.Lock`、`SimpleNamespace`、`monkeypatch.setattr`、`start_calls.append`、`alert_calls.append`、`manager._retry_missing_enabled`、`len`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_camera_retry_logs_without_sending_a_separate_alert(monkeypatch):
    manager_module = importlib.import_module("AiVision.platform.camera.runtime_manager")
    manager = object.__new__(manager_module.CameraRuntimeManager)
    manager._lock = threading.Lock()
    manager._shared_configs = {
        "offline_camera": (
            {"name": "offline-camera", "enable": True},
            SimpleNamespace(value=0),
            SimpleNamespace(value=0),
        )
    }
    manager._runtimes = {}
    manager._last_start_attempts = {"offline_camera": 0.0}
    manager._restart_retry_interval = 30.0

    start_calls = []
    alert_calls = []
    monkeypatch.setattr(
        manager,
        "_start_one",
        lambda *args: start_calls.append(args),
    )
    monkeypatch.setattr(
        manager,
        "_notify_runtime_alert",
        lambda **kwargs: alert_calls.append(kwargs),
    )

    manager._retry_missing_enabled(now=31.0)

    assert len(start_calls) == 1
    assert alert_calls == []


@pytest.fixture
def camera_runtime_factory(monkeypatch):
    module = importlib.import_module("AiVision.platform.camera.runtime")
    monkeypatch.setattr(module, "probe_video_shape", lambda url: (8, 8, 3))
    monkeypatch.setitem(sys.modules, "setproctitle", SimpleNamespace(setproctitle=lambda title: None))

    def create(**overrides):
        config = dict(name="test-camera", shm_name=f"test_camera_{uuid4().hex}", url="rtsp://camera/stream", fps=5)
        config.update(overrides)
        return module.CameraRuntime(config, SimpleNamespace(value=0), SimpleNamespace(value=0))

    return module, create


@pytest.mark.parametrize("running", [False, True])
def test_runtime_stop_escalates_to_kill_even_if_running_flag_is_false(camera_runtime_factory, running):
    _, create = camera_runtime_factory
    runtime = create()
    calls = []
    proc = SimpleNamespace(pid=123, alive=True)
    proc.join = lambda timeout: calls.append(("join", timeout))
    proc.is_alive = lambda: proc.alive
    proc.terminate = lambda: calls.append("terminate")

    def kill():
        calls.append("kill")
        proc.alive = False

    proc.kill = kill
    runtime.proc = proc
    runtime.running = running
    runtime.pipe = Mock()
    runtime.stop()

    assert runtime.stop_event.is_set()
    assert calls == [("join", 5.0), "terminate", ("join", 5.0), "kill", ("join", 2.0)]
    assert runtime.proc is None
    assert runtime.running is False
    runtime.pipe.terminate.assert_not_called()


def test_runtime_start_timeout_reaps_capture_process(camera_runtime_factory, monkeypatch):
    module, create = camera_runtime_factory
    runtime = create()
    proc = Mock(pid=123)
    proc.is_alive.side_effect = [True, False, False]
    monkeypatch.setattr(module, "Process", lambda **kwargs: proc)

    with pytest.raises(TimeoutError, match="初始化超时"):
        runtime.start(runtime.active_index, timeout=0.001, max_count=1)

    proc.start.assert_called_once()
    proc.terminate.assert_called_once()
    assert proc.join.call_count == 2
    assert runtime.proc is None
    assert runtime.running is False


def test_runtime_stop_retains_unreaped_process_for_retry(camera_runtime_factory):
    _, create = camera_runtime_factory
    runtime = create()
    runtime.proc = Mock(pid=123)
    runtime.proc.is_alive.return_value = True
    proc = runtime.proc
    with pytest.raises(RuntimeError, match="kill 后仍未退出"):
        runtime.stop()
    assert runtime.proc is proc


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX process-group lifecycle")
@pytest.mark.parametrize("stop_mode", ["cooperative", "terminate", "kill"])
def test_runtime_timeout_reaps_real_capture_and_ffmpeg_processes(camera_runtime_factory, monkeypatch, stop_mode):
    module, create = camera_runtime_factory
    context = multiprocessing.get_context("fork")
    monkeypatch.setattr(module, "Process", context.Process)
    monkeypatch.setattr(module, "_CAPTURE_JOIN_SECONDS", 0.15)
    monkeypatch.setattr(module, "_CAPTURE_TERMINATE_SECONDS", 0.3)
    monkeypatch.setattr(module, "_FFMPEG_STOP_SECONDS", 0.1)
    runtime = create()
    ffmpeg_pid = context.Value("i", 0)
    capture_pid = context.Value("i", 0)
    command = [
        sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
    ]

    def start_standin():
        runtime.pipe = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        ffmpeg_pid.value = runtime.pipe.pid
        capture_pid.value = os.getpid()

    def blocked_read(_frame_size):
        if stop_mode == "kill":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            time.sleep(0.05)

    monkeypatch.setattr(runtime, "_start_ffmpeg", start_standin)
    if stop_mode != "cooperative":
        monkeypatch.setattr(runtime, "_read_frame", blocked_read)

    def still_executing(pid):
        try:
            return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0] != "Z"
        except FileNotFoundError:
            return False

    try:
        with pytest.raises(TimeoutError, match="初始化超时"):
            runtime.start(runtime.active_index, timeout=0.8, max_count=1)
        assert capture_pid.value > 0 and ffmpeg_pid.value > 0
        assert runtime.proc is None
        assert not Path(f"/proc/{capture_pid.value}").exists()
        _wait_for(lambda: not still_executing(ffmpeg_pid.value))
        for suffix in ("_0", "_1"):
            with pytest.raises(FileNotFoundError):
                module.shared_memory.SharedMemory(name=runtime.shm_name + suffix)
    finally:
        runtime.stop()
        if ffmpeg_pid.value and still_executing(ffmpeg_pid.value):
            os.kill(ffmpeg_pid.value, signal.SIGKILL)


def test_runtime_diff_threshold_has_ratio_units(camera_runtime_factory):
    _, create = camera_runtime_factory
    assert create().diff_threshold == 0.7
    assert create(diff_threshold=0.25).diff_threshold == 0.25
    for invalid in (-0.1, 70, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="ratio between 0 and 1"):
            create(diff_threshold=invalid)


def test_runtime_read_frame_assembles_partial_reads_and_classifies_eof(camera_runtime_factory):
    module, create = camera_runtime_factory
    runtime = create()
    read_fd, write_fd = os.pipe()
    stdout = os.fdopen(read_fd, "rb", buffering=0)
    runtime.pipe = SimpleNamespace(stdout=stdout)
    result = []
    worker = threading.Thread(target=lambda: result.append(runtime._read_frame(6)))
    try:
        worker.start()
        os.write(write_fd, b"abc")
        os.write(write_fd, b"def")
        worker.join(timeout=1)
        assert result == [b"abcdef"]
        os.close(write_fd)
        write_fd = None
        with pytest.raises(module.CameraStreamError, match="stream closed"):
            runtime._read_frame(6)
    finally:
        runtime.stop_event.set()
        worker.join(timeout=1)
        stdout.close()
        if write_fd is not None:
            os.close(write_fd)


def test_runtime_read_frame_can_stop_without_any_stream_bytes(camera_runtime_factory):
    _, create = camera_runtime_factory
    runtime = create()
    read_fd, write_fd = os.pipe()
    stdout = os.fdopen(read_fd, "rb", buffering=0)
    runtime.pipe = SimpleNamespace(stdout=stdout)
    result = []
    worker = threading.Thread(target=lambda: result.append(runtime._read_frame(6)))
    try:
        worker.start()
        runtime.stop_event.set()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert result == [None]
    finally:
        runtime.stop_event.set()
        worker.join(timeout=1)
        stdout.close()
        os.close(write_fd)


def test_runtime_read_io_errors_are_distinct_from_program_errors(camera_runtime_factory, monkeypatch):
    module, create = camera_runtime_factory
    runtime = create()
    stdout = Mock()
    runtime.pipe = SimpleNamespace(stdout=stdout)
    monkeypatch.setattr(module.select, "select", Mock(return_value=([stdout], [], [])))
    monkeypatch.setattr(module.os, "read", Mock(side_effect=OSError("broken pipe")))
    with pytest.raises(module.CameraStreamError, match="管道读取失败"):
        runtime._read_frame(3)
    monkeypatch.setattr(module.os, "read", Mock(side_effect=TypeError("bad argument")))
    with pytest.raises(TypeError, match="bad argument"):
        runtime._read_frame(3)


def test_runtime_ffmpeg_cleanup_waits_after_kill(camera_runtime_factory):
    _, create = camera_runtime_factory
    runtime = create()
    pipe = Mock()
    pipe.wait.side_effect = [subprocess.TimeoutExpired("ffmpeg", 2), 0]
    runtime.pipe = pipe
    runtime._stop_ffmpeg()
    pipe.terminate.assert_called_once()
    pipe.kill.assert_called_once()
    assert pipe.wait.call_count == 2
    pipe.stdout.close.assert_called_once()
    assert runtime.pipe is None


def _capture_with_fake_shms(monkeypatch, runtime):
    shms = [SimpleNamespace(buf=bytearray(8 * 8 * 3), close=Mock(), unlink=Mock()) for _ in range(2)]
    monkeypatch.setattr(runtime, "_create_or_attach_shm", Mock(side_effect=shms))
    monkeypatch.setattr(runtime, "_start_ffmpeg", Mock())
    monkeypatch.setattr(runtime, "_stop_ffmpeg", Mock())
    monkeypatch.setattr(runtime, "_restart_ffmpeg", Mock())
    runtime.frame_interval = 0
    runtime.event_queue = queue.Queue()
    return shms


@pytest.mark.parametrize("threshold, expected_frames", [(0.7, 2), (1.0, 3), (0.0, 2)])
def test_runtime_scene_change_uses_ratio_and_recovers_next_stable_frame(
    camera_runtime_factory, monkeypatch, threshold, expected_frames,
):
    _, create = camera_runtime_factory
    runtime = create(diff_threshold=threshold)
    shms = _capture_with_fake_shms(monkeypatch, runtime)
    black = np.zeros((8, 8, 3), dtype=np.uint8).tobytes()
    white = np.full((8, 8, 3), 255, dtype=np.uint8).tobytes()
    monkeypatch.setattr(runtime, "_read_frame", Mock(side_effect=[black, white, white, None]))
    runtime._capture_loop(runtime.active_index, runtime.frame_seq)
    assert runtime.frame_seq.value == expected_frames
    assert runtime.ready_event.is_set()
    runtime._restart_ffmpeg.assert_not_called()
    runtime._stop_ffmpeg.assert_called_once()
    for shm in shms:
        shm.close.assert_called_once()
        shm.unlink.assert_called_once()


def test_runtime_only_stream_errors_spend_ffmpeg_restart_budget(camera_runtime_factory, monkeypatch):
    module, create = camera_runtime_factory
    runtime = create(max_restart=1)
    _capture_with_fake_shms(monkeypatch, runtime)
    monkeypatch.setattr(runtime, "_read_frame", Mock(side_effect=module.CameraStreamError("closed")))
    runtime._capture_loop(runtime.active_index, runtime.frame_seq)
    runtime._restart_ffmpeg.assert_called_once()
    assert runtime.event_queue.qsize() == 2
    assert all(runtime.event_queue.get_nowait()["event_type"] == "视频流异常" for _ in range(2))


def test_runtime_program_error_exits_without_restarting_ffmpeg(camera_runtime_factory, monkeypatch):
    _, create = camera_runtime_factory
    runtime = create()
    shms = _capture_with_fake_shms(monkeypatch, runtime)
    monkeypatch.setattr(runtime, "_read_frame", Mock(side_effect=TypeError("program bug")))
    with pytest.raises(TypeError, match="program bug"):
        runtime._capture_loop(runtime.active_index, runtime.frame_seq)
    runtime._restart_ffmpeg.assert_not_called()
    runtime._stop_ffmpeg.assert_called_once()
    assert runtime.event_queue.get_nowait()["event_type"] == "采集程序异常"
    assert all(shm.unlink.call_count == 1 for shm in shms)


@pytest.mark.parametrize("failure_stage", ["second_shm", "ffmpeg_start"])
def test_runtime_partial_startup_releases_allocated_resources(camera_runtime_factory, monkeypatch, failure_stage):
    _, create = camera_runtime_factory
    runtime = create()
    shms = _capture_with_fake_shms(monkeypatch, runtime)
    if failure_stage == "second_shm":
        runtime._create_or_attach_shm.side_effect = [shms[0], OSError("no shm")]
    else:
        runtime._start_ffmpeg.side_effect = FileNotFoundError("ffmpeg")
    with pytest.raises(OSError):
        runtime._capture_loop(runtime.active_index, runtime.frame_seq)
    shms[0].close.assert_called_once()
    shms[0].unlink.assert_called_once()
    assert shms[1].unlink.call_count == (failure_stage == "ffmpeg_start")
    runtime._stop_ffmpeg.assert_called_once()


@pytest.mark.parametrize("error, log_method", [(queue.Full(), "warning"), (BrokenPipeError(), "exception")])
def test_runtime_event_delivery_failures_are_logged_nonblocking(camera_runtime_factory, monkeypatch, error, log_method):
    module, create = camera_runtime_factory
    runtime = create()
    runtime.event_queue = Mock()
    runtime.event_queue.put_nowait.side_effect = error
    log = Mock()
    monkeypatch.setattr(module, "logger", log)
    runtime._emit_runtime_event("test", "detail")
    runtime.event_queue.put_nowait.assert_called_once()
    runtime.event_queue.put.assert_not_called()
    getattr(log, log_method).assert_called_once()


@pytest.fixture
def frame_registry(monkeypatch):
    module = importlib.import_module("AiVision.platform.camera.frame_reader")
    attachments = []

    def attach(name):
        shm = SimpleNamespace(name=name, buf=bytearray(12), close=Mock())
        attachments.append(shm)
        return shm

    monkeypatch.setattr(module.shared_memory, "SharedMemory", attach)
    registry = module.FrameReaderRegistry()
    yield module, registry, attachments
    registry.stop_all()


def _wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("timed out waiting for camera test worker")
        time.sleep(0.005)


def test_frame_register_reports_failure_and_closes_partial_attachment(frame_registry, monkeypatch):
    module, registry, attachments = frame_registry
    attach = module.shared_memory.SharedMemory

    def fail_second(name):
        if name.endswith("_1"):
            raise FileNotFoundError(name)
        return attach(name)

    monkeypatch.setattr(module.shared_memory, "SharedMemory", fail_second)
    assert registry.register("camera", (2, 2, 3), SimpleNamespace(value=0), SimpleNamespace(value=1)) is False
    assert not registry.is_active("camera")
    attachments[0].close.assert_called_once()


@pytest.mark.parametrize("start_threads", [False, True])
def test_frame_unregister_and_stop_all_release_four_tuple_views(frame_registry, start_threads):
    _, registry, attachments = frame_registry
    for name in ("camera", "other"):
        assert registry.register(name, (2, 2, 3), SimpleNamespace(value=0), SimpleNamespace(value=1)) is True
    if start_threads:
        registry.start_all()
        _wait_for(lambda: len(registry.latest_frames) == 2)
    thread = registry._threads.get("camera")
    registry.unregister("camera")
    assert not registry.is_active("camera")
    assert "camera" not in registry.latest_frames
    assert "camera" not in registry.latest_frame_times
    assert "camera" not in registry.latest_frame_seq
    if thread is not None:
        assert not thread.is_alive()
    assert registry.is_active("other")
    registry.stop_all()
    assert registry._threads == registry._shm_views == registry._stop_events == {}
    assert registry.latest_frames == registry.latest_frame_times == registry.latest_frame_seq == {}
    for attachment in attachments:
        attachment.close.assert_called_once()


def test_frame_registry_publishes_only_real_read_only_snapshots(frame_registry):
    _, registry, attachments = frame_registry
    seq = SimpleNamespace(value=0)
    assert registry.register("camera", (2, 2, 3), SimpleNamespace(value=0), seq)
    registry.start_all()
    time.sleep(0.12)
    assert "camera" not in registry.latest_frame_times
    attachments[0].buf[:] = bytes([7]) * 12
    seq.value = 1
    _wait_for(lambda: "camera" in registry.latest_frames)
    frame = registry.latest_frames["camera"]
    assert np.all(frame == 7)
    with pytest.raises(ValueError, match="read-only"):
        frame[:] = 255
    attachments[0].buf[:] = bytes([9]) * 12
    assert np.all(frame == 7)


def test_frame_reregister_stops_old_thread_and_uses_new_view(frame_registry):
    _, registry, attachments = frame_registry
    registry.start_all()
    assert registry.register("camera", (2, 2, 3), SimpleNamespace(value=0), SimpleNamespace(value=1))
    _wait_for(lambda: "camera" in registry.latest_frames)
    old_thread = registry._threads["camera"]
    assert registry.register("camera", (2, 2, 3), SimpleNamespace(value=0), SimpleNamespace(value=2))
    assert not old_thread.is_alive()
    _wait_for(lambda: registry.latest_frame_seq.get("camera") == 2)
    assert registry._threads["camera"] is not old_thread
    for attachment in attachments[:2]:
        attachment.close.assert_called_once()


def test_frame_register_reports_thread_start_failure(frame_registry, monkeypatch):
    module, registry, attachments = frame_registry
    registry.start_all()
    monkeypatch.setattr(module.threading.Thread, "start", Mock(side_effect=RuntimeError("thread limit")))
    assert registry.register("camera", (2, 2, 3), SimpleNamespace(value=0), SimpleNamespace(value=1)) is False
    assert registry._threads == registry._shm_views == registry._stop_events == {}
    assert all(shm.close.call_count == 1 for shm in attachments)


@pytest.fixture
def runtime_manager(monkeypatch):
    module = importlib.import_module("AiVision.platform.camera.runtime_manager")
    mp_manager = SimpleNamespace(dict=dict, Value=lambda kind, value: SimpleNamespace(value=value), Queue=queue.Queue)
    manager = module.CameraRuntimeManager(mp_manager)
    manager.initialize_configs([dict(name="camera", shm_name="camera", url="rtsp://camera", enable=True, fps=5)])
    reader = SimpleNamespace(register=Mock(return_value=True), unregister=Mock(), latest_frame_times={})
    monkeypatch.setattr(module, "frame_reader_registry", reader)
    runtimes = []

    def create(config, active_index, frame_seq, event_queue):
        runtime = SimpleNamespace(
            cfg=config, name=config["name"], status=True, shape=(2, 2, 3),
            start=Mock(), stop=Mock(), proc=SimpleNamespace(is_alive=lambda: True),
        )
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(module, "CameraRuntime", create)
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 100.0, sleep=lambda seconds: None))
    monkeypatch.setattr(manager, "_notify_runtime_alert", Mock())
    return module, manager, reader, runtimes


@pytest.mark.parametrize("register_raises", [False, True])
def test_runtime_manager_registration_failure_stops_capture(runtime_manager, register_raises):
    _, manager, reader, runtimes = runtime_manager
    if register_raises:
        reader.register.side_effect = OSError("attach failed")
    else:
        reader.register.return_value = False
    assert manager.start_camera("camera") is False
    runtimes[0].stop.assert_called_once()
    reader.unregister.assert_called_once_with("camera")
    assert not manager.is_running("camera")
    assert "camera" not in manager._runtime_started_at
    assert "注册失败" in manager._notify_runtime_alert.call_args.kwargs["detail"]


def test_runtime_manager_config_update_takes_effect_on_restart_only(runtime_manager):
    _, manager, _, runtimes = runtime_manager
    assert manager.start_camera("camera")
    manager.update_camera_config("camera", {"fps": 9})
    assert runtimes[0].cfg["fps"] == 5
    assert manager._shared_configs["camera"][0]["fps"] == 9
    assert len(runtimes) == 1
    manager._restart_one("camera")
    runtimes[0].stop.assert_called_once()
    assert runtimes[1].cfg["fps"] == 9


@pytest.mark.parametrize("now, last_frame, expected_restart", [(114.0, None, False), (116.0, None, True), (116.0, 115.0, False), (140.0, 120.0, True)])
def test_runtime_manager_watchdog_detects_missing_first_frame(runtime_manager, monkeypatch, now, last_frame, expected_restart):
    module, manager, reader, _ = runtime_manager
    assert manager.start_camera("camera")
    assert manager._runtime_started_at["camera"] == 100.0
    if last_frame is not None:
        reader.latest_frame_times["camera"] = last_frame
    monkeypatch.setattr(manager, "_restart_one", Mock())
    monkeypatch.setattr(manager, "_retry_missing_enabled", lambda now: setattr(manager, "_watchdog_running", False))
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: now, sleep=lambda seconds: None))
    manager._watchdog_running = True
    manager._watchdog_loop()
    assert manager._restart_one.called is expected_restart


def test_runtime_manager_stops_capture_even_when_reader_cleanup_fails(runtime_manager):
    _, manager, reader, runtimes = runtime_manager
    assert manager.start_camera("camera")
    reader.unregister.side_effect = RuntimeError("reader failed")
    with pytest.raises(RuntimeError, match="reader failed"):
        manager.stop_camera("camera")
    runtimes[0].stop.assert_called_once()
    assert not manager.is_running("camera")


def test_runtime_manager_deleted_config_cannot_be_started_from_watchdog_snapshot(runtime_manager):
    _, manager, reader, runtimes = runtime_manager
    stale_item = manager._shared_configs["camera"]
    assert manager.start_camera("camera")
    manager.remove_camera_config("camera")
    assert not manager._start_one("camera", *stale_item)
    manager._retry_missing_enabled(now=200.0)
    assert len(runtimes) == 1
    runtimes[0].stop.assert_called_once()
    assert "camera" not in manager._shared_configs
    assert "camera" not in manager._runtime_started_at
    assert "camera" not in manager._last_start_attempts


def test_runtime_manager_serializes_camera_deletion_against_inflight_start(runtime_manager, monkeypatch):
    module, manager, _, runtimes = runtime_manager
    entered = threading.Event()
    release = threading.Event()
    removed = threading.Event()
    create = module.CameraRuntime

    def slow_create(*args, **kwargs):
        runtime = create(*args, **kwargs)
        runtime.start.side_effect = lambda index: (entered.set(), release.wait(timeout=2))
        return runtime

    monkeypatch.setattr(module, "CameraRuntime", slow_create)
    starter = threading.Thread(target=manager.start_camera, args=("camera",))
    deleter = threading.Thread(target=lambda: (manager.remove_camera_config("camera"), removed.set()))
    try:
        starter.start()
        assert entered.wait(timeout=1)
        deleter.start()
        assert not removed.wait(timeout=0.05)
        release.set()
        starter.join(timeout=2)
        deleter.join(timeout=2)
        assert removed.is_set()
        assert "camera" not in manager._shared_configs
        assert not manager.is_running("camera")
        runtimes[0].stop.assert_called_once()
    finally:
        release.set()
        starter.join(timeout=2)
        if deleter.ident is not None:
            deleter.join(timeout=2)


def test_runtime_manager_stop_all_waits_for_inflight_start_and_blocks_retry(runtime_manager, monkeypatch):
    module, manager, _, runtimes = runtime_manager
    entered = threading.Event()
    release = threading.Event()
    stopped = threading.Event()
    create = module.CameraRuntime

    def slow_create(*args, **kwargs):
        runtime = create(*args, **kwargs)
        runtime.start.side_effect = lambda index: (entered.set(), release.wait(timeout=2))
        return runtime

    monkeypatch.setattr(module, "CameraRuntime", slow_create)
    starter = threading.Thread(target=manager.start_camera, args=("camera",))
    stopper = threading.Thread(target=lambda: (manager.stop_all(), stopped.set()))
    try:
        starter.start()
        assert entered.wait(timeout=1)
        stopper.start()
        assert not stopped.wait(timeout=0.05)
        release.set()
        starter.join(timeout=2)
        stopper.join(timeout=2)
        assert stopped.is_set()
        assert manager._runtimes == {}
        runtimes[0].stop.assert_called_once()
        manager._retry_missing_enabled(now=200.0)
        assert len(runtimes) == 1
    finally:
        release.set()
        starter.join(timeout=2)
        if stopper.ident is not None:
            stopper.join(timeout=2)


def test_runtime_manager_watchdog_does_not_restart_after_stop_during_sleep(runtime_manager, monkeypatch):
    module, manager, _, _ = runtime_manager
    monkeypatch.setattr(manager, "_retry_missing_enabled", Mock())
    monkeypatch.setattr(manager, "_drain_runtime_events", Mock())
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(manager, "_watchdog_running", False))
    manager._watchdog_running = True
    manager._watchdog_loop()
    manager._retry_missing_enabled.assert_not_called()
    manager._drain_runtime_events.assert_not_called()
