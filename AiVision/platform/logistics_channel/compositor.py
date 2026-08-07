"""Render already-annotated camera frames into a logistics-channel mosaic.

This module deliberately performs no inference or channel state classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import Iterable

import cv2
import numpy as np


_MAX_CAMERAS = 9
_MAX_TILE_SIDE = 4096
_DEFAULT_FILL_COLOR = (28, 28, 28)
_MAX_TEXT_LENGTH = 80


@dataclass(frozen=True)
class CameraTile:
    """The latest frame and display metadata for one camera."""

    camera_id: int
    camera_name: str
    frame: np.ndarray | None
    reason: str
    person_count: int | None
    online: bool
    detail: str = ""


def layout_for_count(count: int) -> tuple[int, int]:
    """Return the fixed rows/columns grid used for one to nine cameras."""
    if not isinstance(count, Integral) or isinstance(count, bool) or not 1 <= count <= _MAX_CAMERAS:
        raise ValueError("camera count must be an integer from 1 to 9")
    if count == 1:
        return 1, 1
    if count == 2:
        return 1, 2
    if count <= 4:
        return 2, 2
    return 3, 3


def _validated_size(target_size: tuple[int, int]) -> tuple[int, int]:
    if not isinstance(target_size, tuple) or len(target_size) != 2:
        raise ValueError("target_size must be a (width, height) tuple")
    width, height = target_size
    if (
        not isinstance(width, Integral)
        or isinstance(width, bool)
        or not isinstance(height, Integral)
        or isinstance(height, bool)
        or not 0 < width <= _MAX_TILE_SIDE
        or not 0 < height <= _MAX_TILE_SIDE
    ):
        raise ValueError(f"target_size values must be integers from 1 to {_MAX_TILE_SIDE}")
    return int(width), int(height)


def _as_bgr(frame: np.ndarray | None) -> np.ndarray:
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.size == 0:
        raise ValueError("frame must be a non-empty uint8 image")
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if frame.ndim != 3:
        raise ValueError("frame must have two dimensions or a channel dimension")
    if frame.shape[2] == 3:
        return frame.copy()
    if frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    raise ValueError("frame must have 1, 3, or 4 channels")


def letterbox(
    frame: np.ndarray | None,
    target_size: tuple[int, int] = (640, 360),
    fill_color: tuple[int, int, int] = _DEFAULT_FILL_COLOR,
) -> np.ndarray:
    """Fit a frame into ``target_size`` without stretching it."""
    target_width, target_height = _validated_size(target_size)
    if not isinstance(fill_color, tuple) or len(fill_color) != 3:
        raise ValueError("fill_color must be a BGR triple")
    try:
        bgr = _as_bgr(frame)
    except cv2.error as error:
        raise ValueError("frame could not be converted to BGR") from error

    source_height, source_width = bgr.shape[:2]
    scale = min(target_width / source_width, target_height / source_height)
    resized_width = max(1, min(target_width, round(source_width * scale)))
    resized_height = max(1, min(target_height, round(source_height * scale)))
    try:
        resized = cv2.resize(bgr, (resized_width, resized_height), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    except cv2.error as error:
        raise ValueError("frame could not be resized") from error

    canvas = np.full((target_height, target_width, 3), fill_color, dtype=np.uint8)
    x_offset = (target_width - resized_width) // 2
    y_offset = (target_height - resized_height) // 2
    canvas[y_offset : y_offset + resized_height, x_offset : x_offset + resized_width] = resized
    return np.ascontiguousarray(canvas)


def _display_text(value: object, fallback: str) -> str:
    text = str(value or fallback).replace("\n", " ").replace("\r", " ")[:_MAX_TEXT_LENGTH]
    ascii_text = text.encode("ascii", "replace").decode("ascii")
    return ascii_text if ascii_text.strip(" ?") else fallback


def render_placeholder(camera_name: str, detail: str, target_size: tuple[int, int] = (640, 360)) -> np.ndarray:
    """Create a stable BGR image for offline, waiting, or unusable frames."""
    width, height = _validated_size(target_size)
    canvas = np.full((height, width, 3), (45, 45, 45), dtype=np.uint8)
    cv2.rectangle(canvas, (0, 0), (width - 1, height - 1), (100, 100, 100), 1)
    name = _display_text(camera_name, "camera")
    explanation = _display_text(detail, "waiting for frame")
    scale = max(0.35, min(0.7, width / 640))
    cv2.putText(canvas, name, (8, max(18, height // 2 - 5)), cv2.FONT_HERSHEY_SIMPLEX, scale, (235, 235, 235), 1, cv2.LINE_AA)
    cv2.putText(canvas, explanation, (8, min(height - 8, height // 2 + 20)), cv2.FONT_HERSHEY_SIMPLEX, scale * 0.75, (180, 180, 180), 1, cv2.LINE_AA)
    return np.ascontiguousarray(canvas)


def _status_color(tile: CameraTile) -> tuple[int, int, int]:
    reason = str(tile.reason).strip().lower()
    if not tile.online or reason in {"offline", "disabled", "unconfigured", "not_configured", "not configured"}:
        return 110, 110, 110
    if tile.person_count is None or reason in {"unknown", "waiting", "pending"}:
        return 0, 165, 255
    if tile.person_count > 1 or reason in {"multiple", "multi_person", "multi-person"}:
        return 0, 0, 255
    return 0, 180, 0


def _draw_tile_overlay(image: np.ndarray, tile: CameraTile) -> None:
    height, width = image.shape[:2]
    bar_height = min(max(18, height // 7), 38)
    color = _status_color(tile)
    cv2.rectangle(image, (0, 0), (width - 1, bar_height - 1), color, -1)
    count_text = "?" if tile.person_count is None else str(tile.person_count)
    label = f"{_display_text(tile.camera_name, 'camera')}  persons:{count_text}"
    font_scale = max(0.3, min(0.55, width / 1000))
    cv2.putText(image, label[:_MAX_TEXT_LENGTH], (5, max(13, bar_height - 5)), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 1, cv2.LINE_AA)


def _render_camera_tile(tile: CameraTile, tile_size: tuple[int, int]) -> np.ndarray:
    try:
        image = letterbox(tile.frame, tile_size)
    except (ValueError, cv2.error):
        explanation = tile.detail or str(tile.reason) or "unavailable frame"
        image = render_placeholder(tile.camera_name, explanation, tile_size)
    _draw_tile_overlay(image, tile)
    return image


def compose_channel_frame(tiles: Iterable[CameraTile], tile_size: tuple[int, int] = (640, 360)) -> np.ndarray:
    """Compose the latest camera frames in input order into a fixed grid."""
    width, height = _validated_size(tile_size)
    tile_list = list(tiles)
    rows, columns = layout_for_count(len(tile_list))
    canvas = np.empty((rows * height, columns * width, 3), dtype=np.uint8)
    empty_tile = render_placeholder("unused", "no camera configured", (width, height))
    for index in range(rows * columns):
        row, column = divmod(index, columns)
        if index < len(tile_list):
            tile = tile_list[index]
            if not isinstance(tile, CameraTile):
                raise ValueError("tiles must contain CameraTile values")
            rendered = _render_camera_tile(tile, (width, height))
        else:
            rendered = empty_tile
        canvas[row * height : (row + 1) * height, column * width : (column + 1) * width] = rendered
    return np.ascontiguousarray(canvas)
