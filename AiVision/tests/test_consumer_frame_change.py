from types import SimpleNamespace

import cv2
import numpy as np

from features._base.consumer import BaseFunctionConsumer


class FrameChangeConsumer(BaseFunctionConsumer):
    def _process(self, roi_list, camera_id):
        return []

    def post_process(self, camera_id, result):
        return None


def _consumer() -> FrameChangeConsumer:
    return FrameChangeConsumer(
        spec=SimpleNamespace(name="frame-change-test"),
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _name: True,
    )


def _high_contrast_frame() -> np.ndarray:
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[:, 16:32] = 255
    frame[:, 48:64] = 255
    return frame


def test_identical_high_contrast_frame_is_not_reported_as_changed():
    consumer = _consumer()
    frame = _high_contrast_frame()

    assert consumer._frame_changed(1, [frame]) is True
    assert consumer._frame_changed(1, [frame.copy()]) is False


def test_unchanged_frame_only_blurs_downsampled_comparison_image(monkeypatch):
    consumer = _consumer()
    frame = _high_contrast_frame()
    blurred_shapes: list[tuple[int, ...]] = []
    real_gaussian_blur = cv2.GaussianBlur

    def recording_gaussian_blur(image, kernel_size, sigma):
        blurred_shapes.append(image.shape)
        return real_gaussian_blur(image, kernel_size, sigma)

    monkeypatch.setattr(cv2, "GaussianBlur", recording_gaussian_blur)

    assert consumer._frame_changed(1, [frame]) is True
    full_resolution_blurs = blurred_shapes.count(frame.shape)
    assert consumer._frame_changed(1, [frame.copy()]) is False

    assert blurred_shapes.count(frame.shape) == full_resolution_blurs
    assert consumer.blur_roi[1][0].shape == frame.shape


def test_visibly_changed_frame_refreshes_full_resolution_blur():
    consumer = _consumer()
    frame = _high_contrast_frame()
    changed = 255 - frame

    assert consumer._frame_changed(1, [frame]) is True
    previous_blur = consumer.blur_roi[1][0].copy()

    assert consumer._frame_changed(1, [changed]) is True
    assert not np.array_equal(consumer.blur_roi[1][0], previous_blur)
