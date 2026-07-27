# Security VLM FFmpeg Capture Design

## Problem

The Security VLM page shows corrupted frames for both `/video/original` and
`/video/rule`. The camera stream is HEVC at 2560×1440. A direct FFmpeg TCP
recording from the same RTSP URL is clean, while the current
`cv2.VideoCapture(..., cv2.CAP_FFMPEG)` path produces corrupted output.

This places the fault before MJPEG overlay, proxying, and frontend rendering,
inside the Security VLM capture path. The existing FrameHub and downstream
workers should remain unchanged.

## Selected approach

Replace OpenCV RTSP decoding in `security_vlm/src/capture_worker.py` with an
FFmpeg subprocess that emits `bgr24` rawvideo over stdout.

- Probe width and height with `ffprobe`; do not hard-code the observed
  2560×1440 resolution.
- Force RTSP over TCP and apply a read timeout.
- Apply `runtime.camera_fps_hint` in FFmpeg so full-rate HEVC frames are not
  decoded and then discarded unnecessarily.
- Assemble complete raw frames even when pipe reads return partial chunks.
- Preserve the existing `RtspCapture.start/read/wait_first_frame/release`
  contract so FrameHub and all downstream workers remain untouched.
- Restart FFmpeg after EOF, short reads, or process exit.
- Drain FFmpeg stderr in a daemon thread and log decoder failures without
  printing the credential-bearing RTSP URL.

Local file inputs remain supported: TCP-specific FFmpeg/ffprobe arguments are
only added for `rtsp://` and `rtsps://` sources.

## Data flow

```text
RTSP HEVC camera
  -> ffprobe (one-time width/height detection)
  -> ffmpeg -rtsp_transport tcp -pix_fmt bgr24 -f rawvideo pipe:1
  -> complete-frame assembler
  -> latest-frame lock
  -> existing FrameHubWriter
  -> existing detector/session/VLM/MJPEG/frontend
```

## Error handling

- Probe failures raise a concise startup error.
- FFmpeg startup does not report success until a complete frame is available.
- EOF or an incomplete frame closes the old process, waits briefly, and
  reconnects.
- Shutdown terminates FFmpeg before joining the reader thread so a blocked pipe
  read cannot keep the worker alive.

## Testing

Focused unit tests cover:

1. FFmpeg command construction for RTSP TCP, raw BGR output, timeout, and FPS.
2. Complete-frame assembly from fragmented pipe reads.
3. Clean EOF handling for incomplete frames.
4. `ffprobe` dimension parsing and invalid probe output.
5. Process shutdown behavior.

Verification also compiles the modified module and runs the existing Security
VLM tests when their test runner is available.

## Scope

Modified production file:

- `security_vlm/src/capture_worker.py`

New focused test:

- `security_vlm/tests/test_capture_worker_ffmpeg.py`

No frontend, proxy, MJPEG sizing, detector, session, or VLM behavior changes.
