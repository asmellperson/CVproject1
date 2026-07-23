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
