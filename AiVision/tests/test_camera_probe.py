import importlib
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.modules.pop("platform", None)


def _probe_module():
    try:
        return importlib.import_module("platform.camera.probe")
    except ModuleNotFoundError:
        pytest.fail("platform.camera.probe API is missing")


def test_probe_video_shape_returns_bgr_shape(monkeypatch):
    probe = _probe_module()
    completed = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"streams": [{"width": 1920, "height": 1080}]}),
        stderr="",
    )
    monkeypatch.setattr(probe.subprocess, "run", lambda *args, **kwargs: completed)

    assert probe.probe_video_shape("rtsp://camera/stream") == (1080, 1920, 3)


def test_probe_video_shape_uses_bounded_ffprobe_command(monkeypatch):
    probe = _probe_module()
    observed = {}

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


def test_probe_video_shape_reports_missing_ffprobe(monkeypatch):
    probe = _probe_module()

    def missing(*args, **kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(probe.subprocess, "run", missing)

    with pytest.raises(probe.CameraProbeError, match="ffprobe 未安装"):
        probe.probe_video_shape("rtsp://camera/stream")


def test_probe_video_shape_reports_timeout_without_url(monkeypatch):
    probe = _probe_module()
    url = "rtsp://admin:secret@camera/stream"

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(probe.subprocess, "run", timeout)

    with pytest.raises(probe.CameraProbeError, match="探测超时") as exc_info:
        probe.probe_video_shape(url)
    assert url not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


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


def test_camera_runtime_probe_failure_does_not_call_opencv(monkeypatch):
    runtime_module = importlib.import_module("platform.camera.runtime")
    probe = _probe_module()

    def fail_probe(url):
        raise probe.CameraProbeError("ffprobe 探测超时 (8s)")

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
