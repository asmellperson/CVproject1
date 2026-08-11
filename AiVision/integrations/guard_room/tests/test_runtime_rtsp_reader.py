import os
import sys
import threading
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.runtime import LatestFrameBuffer, RTSPReader, cv2


def test_rtsp_reader_opens_stream_with_ffmpeg_tcp_options(monkeypatch):
    monkeypatch.delenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", raising=False)
    monkeypatch.delenv("OPENCV_FFMPEG_READ_ATTEMPTS", raising=False)

    calls = []
    stop_event = threading.Event()

    class FakeCapture:
        def __init__(self, *args):
            calls.append(args)

        def set(self, *_args):
            return True

        def isOpened(self):
            return True

        def get(self, _prop):
            return 0

        def read(self):
            stop_event.set()
            return True, np.zeros((8, 8, 3), dtype=np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", FakeCapture)

    reader = RTSPReader(
        camera_name="cam1",
        source="rtsp://camera/stream",
        frame_width=1920,
        frame_height=1080,
        reconnect_seconds=0,
        camera_buffer_size=1,
        buffer=LatestFrameBuffer(),
        stop_event=stop_event,
    )

    reader.run()

    assert calls == [("rtsp://camera/stream", cv2.CAP_FFMPEG)]
    ffmpeg_options = os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]
    assert "rtsp_transport;tcp" in ffmpeg_options
    assert "timeout;5000000" in ffmpeg_options
    assert os.environ["OPENCV_FFMPEG_READ_ATTEMPTS"] == "10000"
