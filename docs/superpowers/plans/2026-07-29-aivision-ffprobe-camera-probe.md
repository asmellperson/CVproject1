# AiVision FFprobe Camera Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace AiVision's in-process OpenCV RTSP metadata probe with a timeout-bounded `ffprobe` subprocess so an unreachable camera cannot segfault the API process.

**Architecture:** A focused `platform.camera.probe` module owns external process execution, JSON parsing, timeout handling, and credential-safe errors. `CameraRuntime` consumes only its `(height, width, channels)` result and converts expected probe failures into the existing per-camera unavailable state; capture-process frame handling continues to use OpenCV.

**Tech Stack:** Python 3.10, `subprocess`, `ffprobe`, pytest, existing AiVision `uv` environment

---

### Task 1: Add the isolated FFprobe adapter

**Files:**
- Create: `AiVision/platform/camera/probe.py`
- Create: `AiVision/tests/test_camera_probe.py`

- [ ] **Step 1: Write failing adapter tests**

Create `AiVision/tests/test_camera_probe.py` with tests that import the wished-for
API inside each test, keeping the initial missing module as an assertion failure
rather than a collection error:

```python
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
```

- [ ] **Step 2: Run the adapter tests and verify RED**

Run:

```bash
cd AiVision
uv run --extra dev pytest tests/test_camera_probe.py -q
```

Expected: tests fail with `platform.camera.probe API is missing`.

- [ ] **Step 3: Implement the minimal FFprobe adapter**

Create `AiVision/platform/camera/probe.py`:

```python
"""Probe camera stream metadata in an isolated ffprobe subprocess."""
from __future__ import annotations

import json
import re
import subprocess


FFPROBE_TIMEOUT_SECONDS = 8.0
_RTSP_CREDENTIALS = re.compile(r"(rtsp://)[^/@\s]+@")


class CameraProbeError(RuntimeError):
    """A safe, expected failure while probing camera metadata."""


def _redact_rtsp_credentials(value: str) -> str:
    return _RTSP_CREDENTIALS.sub(r"\1***:***@", value)


def probe_video_shape(
    url: str,
    *,
    timeout_seconds: float = FFPROBE_TIMEOUT_SECONDS,
) -> tuple[int, int, int]:
    command = [
        "ffprobe",
        "-v",
        "error",
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
```

- [ ] **Step 4: Run the adapter tests and verify GREEN**

Run:

```bash
cd AiVision
uv run --extra dev pytest tests/test_camera_probe.py -q
```

Expected: all adapter tests pass.

### Task 2: Route CameraRuntime metadata probes through the adapter

**Files:**
- Modify: `AiVision/platform/camera/runtime.py:12-99`
- Modify: `AiVision/tests/test_camera_probe.py`

- [ ] **Step 1: Write the failing CameraRuntime regression test**

Append to `AiVision/tests/test_camera_probe.py`:

```python
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
```

- [ ] **Step 2: Run the regression test and verify RED**

Run:

```bash
cd AiVision
uv run --extra dev pytest \
  tests/test_camera_probe.py::test_camera_runtime_probe_failure_does_not_call_opencv \
  -q
```

Expected: FAIL with `CameraRuntime must not probe RTSP through OpenCV`.

- [ ] **Step 3: Replace the in-process OpenCV metadata probe**

In `AiVision/platform/camera/runtime.py`:

1. Remove imports `os` and `contextmanager`.
2. Remove `_suppress_native_stderr`.
3. Add:

```python
from .probe import CameraProbeError, probe_video_shape
```

4. Replace `_probe_size` with:

```python
    def _probe_size(self):
        """通过隔离的 ffprobe 子进程获取视频分辨率。"""
        try:
            self.shape = probe_video_shape(self.url)
            self.height, self.width, self.channels = self.shape
        except CameraProbeError as exc:
            logger.warning(f"[Camera:{self.name}] 获取分辨率失败: {exc}")
            self.status = False
            self.msg = f"[{self.name}] 获取分辨率异常: {exc}"
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
cd AiVision
uv run --extra dev pytest tests/test_camera_probe.py -q
```

Expected: all probe and CameraRuntime tests pass.

### Task 3: Verify scope and regressions

**Files:**
- Verify: `AiVision/platform/camera/probe.py`
- Verify: `AiVision/platform/camera/runtime.py`
- Verify: `AiVision/tests/test_camera_probe.py`
- Verify: `docs/superpowers/plans/2026-07-29-aivision-ffprobe-camera-probe.md`

- [ ] **Step 1: Run Ruff on changed Python files**

Run:

```bash
cd AiVision
uv run --extra dev ruff check \
  platform/camera/probe.py \
  platform/camera/runtime.py \
  tests/test_camera_probe.py
```

Expected: exit 0 with no lint errors.

- [ ] **Step 2: Run Python compile validation**

Run:

```bash
cd AiVision
uv run python -m py_compile \
  platform/camera/probe.py \
  platform/camera/runtime.py \
  tests/test_camera_probe.py
```

Expected: exit 0 with no output.

- [ ] **Step 3: Run the full AiVision test suite**

Run:

```bash
cd AiVision
uv run --extra dev pytest -q
```

Expected: all AiVision tests pass.

- [ ] **Step 4: Inspect the final diff and sensitive-data scope**

Run:

```bash
git diff --check
git diff -- \
  AiVision/platform/camera/probe.py \
  AiVision/platform/camera/runtime.py \
  AiVision/tests/test_camera_probe.py \
  docs/superpowers/plans/2026-07-29-aivision-ffprobe-camera-probe.md
git status --short
```

Expected: only this task's files are included; existing unrelated
`auth/auth_users.json`, `AGENTS.md`, and the earlier untracked plan remain untouched.

- [ ] **Step 5: Commit only the implementation files**

```bash
git add -- \
  AiVision/platform/camera/probe.py \
  AiVision/platform/camera/runtime.py \
  AiVision/tests/test_camera_probe.py \
  docs/superpowers/plans/2026-07-29-aivision-ffprobe-camera-probe.md
git commit -m "修复 AiVision 摄像头探测段错误"
```

Expected: one focused implementation commit with no unrelated files.

- [ ] **Step 6: Publish the verified commit through V4**

Follow `clean-ai-project`:

```bash
git tag -f V4 HEAD
ss -xl
```

Select the currently listening `vscode-git-*.sock`, notify the user that authentication
may appear, set `VSCODE_GIT_IPC_HANDLE` only for the push command, then run:

```bash
git push origin V4 --force
git rev-parse HEAD V4
git ls-remote origin refs/tags/V4
```

Expected: local `HEAD`, local `V4`, and remote `refs/tags/V4` resolve to the same SHA.

### Task 4: Validate on the target server

**Files:**
- Deploy: V4 tag to `/srv/Fuda_CVPreject`

- [ ] **Step 1: Check for target-server local changes**

Run on the target server:

```bash
cd /srv/Fuda_CVPreject
git status --short
```

If there are local changes, preserve them before updating:

```bash
git stash push -u -m "before-V4-update"
```

- [ ] **Step 2: Fetch and switch to the new V4 tag**

Run:

```bash
git fetch origin --tags --force
git switch --detach V4
git log -1 --oneline
command -v ffprobe
```

Expected: the implementation commit is checked out and `ffprobe` resolves to an executable.

- [ ] **Step 3: Restart AiVision and observe two retry cycles**

Restart only AiVision using the deployment's existing tmux command. Then run:

```bash
curl -sS http://127.0.0.1:7862/api/v2/runtime/health | python3 -m json.tool
sleep 35
curl -sS http://127.0.0.1:7862/api/v2/runtime/health | python3 -m json.tool
sleep 35
curl -sS http://127.0.0.1:7862/api/v2/runtime/health | python3 -m json.tool
dmesg -T |
  grep -Ei 'segfault|cv2\.abi3\.so' |
  tail -20
```

Expected: health remains reachable after at least two 30-second watchdog retries, while the
offline camera may continue to report a safe initialization failure and no new AiVision
`cv2.abi3.so` segfault appears.
