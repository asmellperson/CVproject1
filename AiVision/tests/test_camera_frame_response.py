import importlib
import sys

import numpy as np
import pytest


sys.modules.pop("platform", None)
cameras_module = importlib.import_module("api.v2.cameras")
compat_module = importlib.import_module("api.compat")
get_camera_frame_jpg = cameras_module.get_camera_frame_jpg
compat_get_camera_frame_jpg = compat_module.compat_get_camera_frame_jpg


class FrameOrchestrator:
    def __init__(self, frame):
        self.frame = frame

    def get_camera_frame_info(self, key, feature=None):
        return self.frame, 123.0


@pytest.mark.parametrize(
    "handler",
    [get_camera_frame_jpg, compat_get_camera_frame_jpg],
)
def test_frame_response_exposes_original_dimensions_when_preview_is_resized(handler):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    response = handler(
        key="camera-1",
        feature="detect_human",
        quality=72,
        max_width=960,
        max_height=None,
        orchestrator=FrameOrchestrator(frame),
    )

    assert response.headers["x-frame-width"] == "1920"
    assert response.headers["x-frame-height"] == "1080"


def test_slow_frame_response_logs_lookup_and_encode_timings(monkeypatch):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    warnings: list[str] = []
    monotonic_values = iter([0.0, 0.2, 0.2, 1.5, 1.5])

    monkeypatch.setattr(cameras_module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(cameras_module, "encode_frame_to_jpeg", lambda *args, **kwargs: b"jpeg")
    monkeypatch.setattr(cameras_module.logger, "warning", warnings.append)
    monkeypatch.setattr(cameras_module.settings.runtime, "slow_frame_log_seconds", 1.0)

    response = cameras_module.build_camera_frame_response(
        key="camera-1",
        feature="detect_human",
        quality=72,
        max_width=960,
        max_height=None,
        orchestrator=FrameOrchestrator(frame),
    )

    assert response.body == b"jpeg"
    assert len(warnings) == 1
    assert "key=camera-1" in warnings[0]
    assert "lookup=0.200s" in warnings[0]
    assert "encode=1.300s" in warnings[0]
    assert "total=1.500s" in warnings[0]
