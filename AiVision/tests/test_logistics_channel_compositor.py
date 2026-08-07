from dataclasses import FrozenInstanceError

import numpy as np
import pytest

import platform.logistics_channel.compositor as compositor
from platform.logistics_channel.compositor import (
    CameraTile,
    compose_channel_frame,
    layout_for_count,
    letterbox,
    render_placeholder,
)


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, (1, 1)), (2, (1, 2)), (3, (2, 2)), (4, (2, 2)), (5, (3, 3)), (9, (3, 3))],
)
def test_layout_for_count_uses_defined_channel_grid(count, expected):
    assert layout_for_count(count) == expected


@pytest.mark.parametrize("count", [0, 10])
def test_layout_for_count_rejects_out_of_range_counts(count):
    with pytest.raises(ValueError):
        layout_for_count(count)


def test_camera_tile_is_immutable():
    tile = CameraTile(1, "入口", None, "waiting", None, False)

    with pytest.raises(FrozenInstanceError):
        tile.camera_name = "changed"


def test_letterbox_preserves_landscape_content_ratio_and_input():
    frame = np.full((20, 80, 3), (12, 34, 56), dtype=np.uint8)
    original = frame.copy()

    result = letterbox(frame, target_size=(100, 100), fill_color=(1, 2, 3))

    assert result.shape == (100, 100, 3)
    assert np.array_equal(frame, original)
    assert np.all(result[:37] == (1, 2, 3))
    assert np.all(result[37:62] == (12, 34, 56))
    assert np.all(result[62:] == (1, 2, 3))


def test_letterbox_preserves_portrait_content_ratio():
    frame = np.full((80, 20, 3), 99, dtype=np.uint8)

    result = letterbox(frame, target_size=(100, 100), fill_color=(0, 0, 0))

    assert np.all(result[:, :37] == 0)
    assert np.all(result[:, 37:62] == 99)
    assert np.all(result[:, 62:] == 0)


@pytest.mark.parametrize(
    "frame",
    [None, np.empty((0, 0, 3), dtype=np.uint8), np.ones((4, 4, 3), dtype=np.float32)],
)
def test_letterbox_rejects_missing_or_invalid_frames(frame):
    with pytest.raises(ValueError):
        letterbox(frame)


def test_render_placeholder_is_nonempty_bgr_for_unicode_text():
    result = render_placeholder("东门摄像头", "等待视频流", (120, 60))

    assert result.shape == (60, 120, 3)
    assert result.dtype == np.uint8
    assert result.flags.c_contiguous
    assert np.any(result)


@pytest.mark.parametrize(
    ("count", "expected_shape"),
    [
        (1, (30, 40, 3)),
        (2, (30, 80, 3)),
        (3, (60, 80, 3)),
        (4, (60, 80, 3)),
        (5, (90, 120, 3)),
        (9, (90, 120, 3)),
    ],
)
def test_compose_channel_frame_uses_expected_grid_shapes(count, expected_shape):
    tiles = [CameraTile(i, f"cam-{i}", np.full((10, 10, 3), i, np.uint8), "normal", 1, True) for i in range(count)]

    result = compose_channel_frame(tiles, tile_size=(40, 30))

    assert result.shape == expected_shape
    assert result.dtype == np.uint8
    assert result.flags.c_contiguous


@pytest.mark.parametrize("tiles", [[], [CameraTile(i, str(i), None, "waiting", None, False) for i in range(10)]])
def test_compose_channel_frame_rejects_empty_or_too_many_tiles(tiles):
    with pytest.raises(ValueError):
        compose_channel_frame(tiles)


def test_compose_channel_frame_places_tiles_in_input_order_away_from_overlay():
    colors = [(10, 20, 30), (40, 50, 60)]
    tiles = [CameraTile(index, str(index), np.full((20, 20, 3), color, np.uint8), "normal", 1, True) for index, color in enumerate(colors)]

    result = compose_channel_frame(tiles, tile_size=(40, 30))

    assert tuple(result[25, 20]) == colors[0]
    assert tuple(result[25, 60]) == colors[1]


def test_compose_channel_frame_replaces_invalid_frame_without_losing_other_tile():
    valid = np.full((20, 20, 3), (7, 8, 9), np.uint8)
    tiles = [
        CameraTile(1, "坏帧", None, "offline", None, False, "network disconnected"),
        CameraTile(2, "正常", valid, "normal", 1, True),
    ]

    result = compose_channel_frame(tiles, tile_size=(40, 30))

    assert np.any(result[:, :40])
    assert tuple(result[25, 60]) == (7, 8, 9)


@pytest.mark.parametrize("frame", [np.full((8, 8), 128, np.uint8), np.full((8, 8, 4), 128, np.uint8)])
def test_compose_channel_frame_accepts_grayscale_and_bgra_frames(frame):
    result = compose_channel_frame([CameraTile(1, "very-long-camera-name-" * 20, frame, "unknown", None, True, "detail-" * 100)], tile_size=(40, 30))

    assert result.shape == (30, 40, 3)
    assert result.dtype == np.uint8


@pytest.mark.parametrize("tile_size", [(0, 10), (10, 0), (4097, 10), (10, 4097), (10,), "bad"])
def test_compose_channel_frame_rejects_invalid_tile_size(tile_size):
    with pytest.raises(ValueError):
        compose_channel_frame([CameraTile(1, "cam", None, "waiting", None, False)], tile_size=tile_size)


def test_placeholder_preserves_unicode_camera_name_and_actual_reason_in_text_renderer(monkeypatch):
    rendered_text = []

    def record_text(image, text, *args, **kwargs):
        rendered_text.append(text)
        return image

    monkeypatch.setattr(compositor, "_draw_text", record_text, raising=False)

    render_placeholder("一号物流通道摄像头", "离线/等待画面", (240, 100))

    assert "一号物流通道摄像头" in rendered_text
    assert "离线/等待画面" in rendered_text


def test_overlay_renders_camera_name_person_count_status_and_detail(monkeypatch):
    rendered_text = []

    def record_text(image, text, *args, **kwargs):
        rendered_text.append(text)
        return image

    monkeypatch.setattr(compositor, "_draw_text", record_text, raising=False)
    tile = CameraTile(1, "一号物流通道摄像头", None, "multiple", 2, True, "离线/等待画面")

    compose_channel_frame([tile], tile_size=(240, 100))

    assert "一号物流通道摄像头" in rendered_text
    assert "人数: 2" in rendered_text
    assert any("多人异常" in text for text in rendered_text)
    assert any("离线/等待画面" in text for text in rendered_text)


def test_text_renderer_survives_missing_explicit_font():
    image = np.zeros((80, 240, 3), dtype=np.uint8)

    result = compositor._draw_text(
        image,
        "一号物流通道摄像头",
        (5, 25),
        (255, 255, 255),
        font_path="/definitely/missing/font.ttf",
    )

    assert result.shape == image.shape
    assert result.dtype == np.uint8
    assert result.flags.c_contiguous
