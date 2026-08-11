from types import SimpleNamespace

import numpy as np

from features._base.consumer import BaseFunctionConsumer


class RoiConsumer(BaseFunctionConsumer):
    def _process(self, roi_list, camera_id):
        return []

    def post_process(self, camera_id, result):
        return None


def _consumer() -> RoiConsumer:
    return RoiConsumer(
        spec=SimpleNamespace(name="roi-test"),
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _name: True,
    )


def _set_roi(consumer: RoiConsumer, camera_id: int, points: list[list[int]]) -> None:
    consumer.config_cache[camera_id] = {"value": {"roi_pos": [points]}}


def test_roi_outside_camera_frame_is_clipped_before_masking():
    consumer = _consumer()
    _set_roi(
        consumer,
        camera_id=1,
        points=[[650, 500], [800, 500], [800, 700], [650, 700]],
    )
    frame = np.full((576, 704, 3), 127, dtype=np.uint8)

    roi_list = consumer._get_roi(1, frame)

    assert len(roi_list) == 1
    assert roi_list[0].shape == (76, 54, 3)
    assert consumer._masks[1][0][0].shape == roi_list[0].shape[:2]


def test_roi_mask_is_rebuilt_when_same_camera_frame_shape_changes():
    consumer = _consumer()
    _set_roi(
        consumer,
        camera_id=1,
        points=[[600, 400], [1000, 400], [1000, 700], [600, 700]],
    )

    large_roi = consumer._get_roi(1, np.zeros((720, 1280, 3), dtype=np.uint8))
    small_roi = consumer._get_roi(1, np.zeros((576, 704, 3), dtype=np.uint8))

    assert large_roi[0].shape == (300, 400, 3)
    assert small_roi[0].shape == (176, 104, 3)
    assert consumer._masks_frame_shape[1] == (576, 704)
    assert consumer._masks[1][0][0].shape == small_roi[0].shape[:2]


def test_roi_masks_are_isolated_by_camera_frame_shape():
    consumer = _consumer()
    points = [[100, 100], [900, 100], [900, 650], [100, 650]]
    _set_roi(consumer, camera_id=1, points=points)
    _set_roi(consumer, camera_id=2, points=points)

    first_camera_roi = consumer._get_roi(1, np.zeros((576, 704, 3), dtype=np.uint8))
    second_camera_roi = consumer._get_roi(2, np.zeros((720, 1280, 3), dtype=np.uint8))

    assert first_camera_roi[0].shape == (476, 604, 3)
    assert second_camera_roi[0].shape == (550, 800, 3)
    assert consumer._masks_frame_shape == {1: (576, 704), 2: (720, 1280)}
