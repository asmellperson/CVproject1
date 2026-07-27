# Security VLM FFmpeg Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Security VLM OpenCV HEVC RTSP decoder with the FFmpeg TCP rawvideo path already proven clean against the production camera.

**Architecture:** Keep the existing `RtspCapture` public contract and FrameHub pipeline. Add small testable helpers for FFmpeg command construction, stream probing, and exact pipe reads, then use them inside the existing background capture thread with automatic process restart.

**Tech Stack:** Python 3.10, FFmpeg/ffprobe CLI, NumPy, unittest, existing FrameHub.

---

### Task 1: FFmpeg command and exact-frame helpers

**Files:**
- Create: `security_vlm/tests/test_capture_worker_ffmpeg.py`
- Modify: `security_vlm/src/capture_worker.py`

- [ ] **Step 1: Write the failing command-construction test**

```python
def test_build_ffmpeg_command_uses_tcp_rawvideo_and_target_fps(self):
    command = capture_worker.build_ffmpeg_command("rtsp://camera/stream", 10)
    self.assertIn("-rtsp_transport", command)
    self.assertIn("tcp", command)
    self.assertIn("fps=10", command)
    self.assertEqual(command[-3:], ["rawvideo", "pipe:1"])
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
/root/miniconda3/envs/security_vlm/bin/python -m unittest security_vlm.tests.test_capture_worker_ffmpeg -v
```

Expected: FAIL because `build_ffmpeg_command` does not exist.

- [ ] **Step 3: Implement command construction**

Add `build_ffmpeg_command(source, target_fps)` using:

```python
command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
if source.lower().startswith(("rtsp://", "rtsps://")):
    command.extend(["-rtsp_transport", "tcp", "-rw_timeout", "5000000"])
command.extend([
    "-i", source,
    "-an",
    "-vf", f"fps={max(1.0, float(target_fps)):g}",
    "-pix_fmt", "bgr24",
    "-f", "rawvideo",
    "pipe:1",
])
```

- [ ] **Step 4: Add fragmented-read and EOF tests**

Use a fake stream whose `read()` returns several short chunks. Assert
`read_exact()` joins a complete frame and returns `None` when EOF arrives
before the requested size.

- [ ] **Step 5: Implement `read_exact(stream, size)` and verify GREEN**

Read until exactly `size` bytes have been accumulated or return `None` on an
empty chunk. Re-run the focused unittest command and expect all helper tests to
pass.

### Task 2: Resolution probing

**Files:**
- Modify: `security_vlm/tests/test_capture_worker_ffmpeg.py`
- Modify: `security_vlm/src/capture_worker.py`

- [ ] **Step 1: Write failing probe tests**

Provide a fake runner returning:

```json
{"streams": [{"width": 2560, "height": 1440}]}
```

Assert `probe_video_shape()` returns `(1440, 2560, 3)`, includes RTSP TCP in
the probe command, and rejects empty or zero-sized stream output.

- [ ] **Step 2: Run tests and verify RED**

Expected: FAIL because `probe_video_shape` does not exist.

- [ ] **Step 3: Implement the probe helper**

Run `ffprobe` with JSON output, a 10-second timeout, and TCP arguments only for
RTSP sources. Parse the first video stream and raise `RuntimeError` for missing
or non-positive dimensions.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the unittest command from Task 1. Expect all probe and helper tests to pass.

### Task 3: Replace OpenCV capture while preserving the public contract

**Files:**
- Modify: `security_vlm/tests/test_capture_worker_ffmpeg.py`
- Modify: `security_vlm/src/capture_worker.py`

- [ ] **Step 1: Write failing lifecycle tests**

Use fake `Popen` objects to assert:

- `_open()` starts the FFmpeg command with `stdout=PIPE` and `stderr=PIPE`.
- A complete raw frame becomes a copied `numpy.uint8` array with the probed
  shape.
- `_close_process()` terminates and waits for a running process.

- [ ] **Step 2: Run tests and verify RED**

Expected: FAIL because `RtspCapture` still uses `cv2.VideoCapture`.

- [ ] **Step 3: Implement the FFmpeg-backed `RtspCapture`**

Keep `start()`, `read()`, `wait_first_frame()`, and `release()` signatures.
Replace `cap` with a subprocess, use `read_exact()` for one raw frame, copy the
reshaped NumPy array under the existing lock, drain stderr on a daemon thread,
and reconnect after incomplete frames.

- [ ] **Step 4: Pass configured FPS into the capture layer**

Change:

```python
capture = RtspCapture(source, log_prefix="[capture]")
```

to:

```python
capture = RtspCapture(source, target_fps=target_fps, log_prefix="[capture]")
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the focused unittest command. Expect all lifecycle tests to pass without
accessing a real camera.

### Task 4: Regression verification

**Files:**
- Verify: `security_vlm/src/capture_worker.py`
- Verify: `security_vlm/tests/test_capture_worker_ffmpeg.py`

- [ ] **Step 1: Compile the modified module**

```bash
/root/miniconda3/envs/security_vlm/bin/python -m py_compile security_vlm/src/capture_worker.py
```

Expected: exit code 0.

- [ ] **Step 2: Run focused tests**

```bash
/root/miniconda3/envs/security_vlm/bin/python -m unittest security_vlm.tests.test_capture_worker_ffmpeg -v
```

Expected: all tests pass.

- [ ] **Step 3: Run existing Security VLM tests where available**

Use an interpreter with pytest installed:

```bash
python -m pytest security_vlm/tests -q
```

If pytest is unavailable, report that limitation without installing a new
dependency.

- [ ] **Step 4: Inspect final scope**

```bash
git diff --check
git diff -- security_vlm/src/capture_worker.py security_vlm/tests/test_capture_worker_ffmpeg.py
```

Confirm no frontend, proxy, `max_side`, detector, session, or VLM files changed.
