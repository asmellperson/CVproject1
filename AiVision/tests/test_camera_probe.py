# 文件说明：包含摄像头的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import importlib
import threading
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.modules.pop("platform", None)


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
        return importlib.import_module("platform.camera.probe")
    except ModuleNotFoundError:
        pytest.fail("platform.camera.probe API is missing")


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
    runtime_module = importlib.import_module("platform.camera.runtime")
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
    manager_module = importlib.import_module("platform.camera.runtime_manager")
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
