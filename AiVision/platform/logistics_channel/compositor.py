# 文件说明：实现`compositor` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""Render already-annotated camera frames into a logistics-channel mosaic.

This module deliberately performs no inference or channel state classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
from numbers import Integral
from pathlib import Path
from typing import Iterable
import unicodedata

import cv2
import numpy as np

try:  # Pillow is optional: this module remains usable in the minimal runtime.
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - exercised in deployments without Pillow.
    Image = ImageDraw = ImageFont = None


_MAX_CAMERAS = 9
_MAX_TILE_SIDE = 4096
_DEFAULT_FILL_COLOR = (28, 28, 28)
_MAX_TEXT_LENGTH = 80
_LOGGER = logging.getLogger(__name__)
_CJK_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
)
# 功能：The latest frame and display metadata for one camera；输入与输出详见下方说明
# 参数：
#   - `camera_id`（int）：摄像头唯一标识
#   - `camera_name`（str）：`camera_name` 对应的业务输入值
#   - `frame`（np.ndarray | None）：待处理的视频图像帧
#   - `reason`（str）：`reason` 对应的业务输入值
#   - `person_count`（int | None）：`person_count` 对应的数量或大小
#   - `online`（bool）：`online` 对应的业务输入值
#   - `detail`（str）：`detail` 对应的业务输入值
# 返回：CameraTile；返回新建的 `CameraTile` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_camera_tile_is_immutable`
#         实例化本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_compose_channel_frame_uses_expected_grid_shapes`
#         实例化本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_compose_channel_frame_places_tiles_in_input_order`
#         实例化本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的
#         `test_live_camera_frame_top_pixels_are_not_covered_by_status_banner` 实例化本符号；另有 5 处静态调用
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：Return the fixed rows/columns grid used for one to nine cameras；输入与输出详见下方说明
# 参数：
#   - `count`（int）：`count` 对应的数量或大小
# 返回：tuple[int, int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `compose_channel_frame`
#         调用本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_layout_for_count_uses_defined_channel_grid`
#         调用本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_layout_for_count_rejects_out_of_range_counts` 调用本符号
#   - 内部调用：`isinstance`、`ValueError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：实现 `_validated_size` 对应的`compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `target_size`（tuple[int, int]）：`target_size` 对应的数量或大小
# 返回：tuple[int, int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `letterbox`
#         调用本符号；`AiVision/platform/logistics_channel/compositor.py` 的 `render_placeholder`
#         调用本符号；`AiVision/platform/logistics_channel/compositor.py` 的 `compose_channel_frame` 调用本符号
#   - 内部调用：`isinstance`、`len`、`ValueError`、`int`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：实现 `_as_bgr` 对应的`compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `frame`（np.ndarray | None）：待处理的视频图像帧
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `letterbox` 调用本符号
#   - 内部调用：`isinstance`、`ValueError`、`cv2.cvtColor`、`frame.copy`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：Fit a frame into ``target_size`` without stretching it；输入与输出详见下方说明
# 参数：
#   - `frame`（np.ndarray | None）：待处理的视频图像帧
#   - `target_size`（tuple[int, int]）：`target_size` 对应的数量或大小；默认值为 `(640, 360)`
#   - `fill_color`（tuple[int, int, int]）：`fill_color` 对应的业务输入值；默认值为 `_DEFAULT_FILL_COLOR`
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `_render_camera_tile`
#         调用本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_letterbox_preserves_landscape_content_ratio_and_input`
#         调用本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_letterbox_preserves_portrait_content_ratio`
#         调用本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_letterbox_rejects_missing_or_invalid_frames` 调用本符号
#   - 内部调用：`_validated_size`、`isinstance`、`len`、`ValueError`、`_as_bgr`、`min`、`max`、`round`、`cv2.resize`、`np.full` 等共 11 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：实现 `_display_text` 对应的`compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（object）：待转换、校验或写入的值
#   - `fallback`（str）：`fallback` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `_draw_text`
#         调用本符号；`AiVision/platform/logistics_channel/compositor.py` 的 `render_placeholder` 调用本符号
#   - 内部调用：`str`、`''.join`、`unicodedata.category(character).startswith`、`unicodedata.category`、`visible.strip`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def _display_text(value: object, fallback: str) -> str:
    text = str(value or fallback)
    visible = "".join(" " if character in "\n\r" else character for character in text if not unicodedata.category(character).startswith("C"))
    return visible.strip()[:_MAX_TEXT_LENGTH] or fallback


# 功能：Resolve CJK font candidates once instead of scanning per rendered frame；输入与输出详见下方说明
# 参数：无。
# 返回：tuple[str, ...]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `_load_font` 调用本符号
#   - 内部调用：`tuple`、`Path(path).is_file`、`Path`、`lru_cache`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@lru_cache(maxsize=1)
def _available_font_paths() -> tuple[str, ...]:
    """Resolve CJK font candidates once instead of scanning per rendered frame."""
    return tuple(path for path in _CJK_FONT_PATHS if Path(path).is_file())


# 功能：读取或查询 `_load_font` 对应的`compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `font_path`（str | None）：`font_path` 对应的业务输入值
#   - `size`（int）：`size` 对应的数量或大小
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `_draw_text` 调用本符号
#   - 内部调用：`_available_font_paths`、`ImageFont.truetype`、`_LOGGER.warning`、`ImageFont.load_default`、`lru_cache`。
# 副作用/注意事项：会向日志系统输出运行或异常信息。
@lru_cache(maxsize=32)
def _load_font(font_path: str | None, size: int):
    if ImageFont is None:
        return None
    candidates = (font_path,) if font_path else _available_font_paths()
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, ValueError) as error:
            _LOGGER.warning("Unable to load logistics overlay font %s: %s", candidate, error)
    try:
        return ImageFont.load_default()
    except OSError as error:
        _LOGGER.warning("Unable to load Pillow fallback font: %s", error)
        return None


# 功能：实现 `_truncate_for_width` 对应的`compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `text`（str）：`text` 对应的业务输入值
#   - `draw`（未显式标注）：`draw` 对应的业务输入值
#   - `font`（未显式标注）：`font` 对应的业务输入值
#   - `max_width`（int | None）：`max_width` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `_draw_text` 调用本符号
#   - 内部调用：`draw.textlength`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _truncate_for_width(text: str, draw, font, max_width: int | None) -> str:
    if max_width is None or max_width <= 0 or draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "…"
    available = max_width - draw.textlength(suffix, font=font)
    truncated = ""
    for character in text:
        if draw.textlength(truncated + character, font=font) > available:
            break
        truncated += character
    return (truncated + suffix) if truncated else suffix


# 功能：Draw Unicode text in-place when possible, with a safe OpenCV fallback；输入与输出详见下方说明
# 参数：
#   - `image`（np.ndarray）：待处理的图像数据
#   - `text`（object）：`text` 对应的业务输入值
#   - `origin`（tuple[int, int]）：`origin` 对应的业务输入值
#   - `color`（tuple[int, int, int]）：`color` 对应的业务输入值
#   - `font_path`（str | None）：`font_path` 对应的业务输入值；默认值为 `None`
#   - `font_size`（int）：`font_size` 对应的数量或大小；默认值为 `16`
#   - `max_width`（int | None）：`max_width` 对应的业务输入值；默认值为 `None`
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `render_placeholder` 调用本符号
#   - 内部调用：`_display_text`、`_load_font`、`max`、`cv2.cvtColor`、`Image.fromarray`、`ImageDraw.Draw`、`_truncate_for_width`、`draw.text`、`tuple`、`reversed`
#          等共 16 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息。
def _draw_text(
    image: np.ndarray,
    text: object,
    origin: tuple[int, int],
    color: tuple[int, int, int],
    *,
    font_path: str | None = None,
    font_size: int = 16,
    max_width: int | None = None,
) -> np.ndarray:
    """Draw Unicode text in-place when possible, with a safe OpenCV fallback."""
    visible_text = _display_text(text, "-")
    if Image is not None and ImageDraw is not None:
        font = _load_font(font_path, max(8, font_size))
        if font is not None:
            try:
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(rgb)
                draw = ImageDraw.Draw(pil_image)
                fitted_text = _truncate_for_width(visible_text, draw, font, max_width)
                draw.text(origin, fitted_text, font=font, fill=tuple(reversed(color)))
                image[:] = cv2.cvtColor(np.asarray(pil_image), cv2.COLOR_RGB2BGR)
                return image
            except (OSError, ValueError, TypeError, UnicodeError, cv2.error) as error:
                _LOGGER.warning("Unable to render Unicode logistics overlay text: %s", error)

    fallback = visible_text.encode("ascii", "replace").decode("ascii")
    if not fallback.strip(" ?"):
        fallback = "text"
    if max_width:
        fallback = fallback[: max(1, max_width // max(5, font_size // 2))]
    cv2.putText(image, fallback, origin, cv2.FONT_HERSHEY_SIMPLEX, max(0.3, font_size / 30), color, 1, cv2.LINE_AA)
    return image


# 功能：Create a stable BGR image for offline, waiting, or unusable frames；输入与输出详见下方说明
# 参数：
#   - `camera_name`（str）：`camera_name` 对应的业务输入值
#   - `detail`（str）：`detail` 对应的业务输入值
#   - `target_size`（tuple[int, int]）：`target_size` 对应的数量或大小；默认值为 `(640, 360)`
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `_render_camera_tile`
#         调用本符号；`AiVision/platform/logistics_channel/compositor.py` 的 `compose_channel_frame`
#         调用本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_render_placeholder_is_nonempty_bgr_for_unicode_text`
#         调用本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的
#         `test_placeholder_preserves_unicode_camera_name_and_actual_reason_in_text_renderer` 调用本符号
#   - 内部调用：`_validated_size`、`np.full`、`cv2.rectangle`、`_display_text`、`max`、`min`、`_draw_text`、`np.ascontiguousarray`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def render_placeholder(camera_name: str, detail: str, target_size: tuple[int, int] = (640, 360)) -> np.ndarray:
    """Create a stable BGR image for offline, waiting, or unusable frames."""
    width, height = _validated_size(target_size)
    canvas = np.full((height, width, 3), (45, 45, 45), dtype=np.uint8)
    cv2.rectangle(canvas, (0, 0), (width - 1, height - 1), (100, 100, 100), 1)
    name = _display_text(camera_name, "camera")
    explanation = _display_text(detail, "waiting for frame")
    font_size = max(10, min(24, width // 28))
    _draw_text(canvas, name, (8, max(font_size + 4, height // 2 - font_size)), (235, 235, 235), font_size=font_size, max_width=width - 16)
    _draw_text(canvas, explanation, (8, min(height - 6, height // 2 + font_size + 4)), (180, 180, 180), font_size=max(9, font_size - 3), max_width=width - 16)
    return np.ascontiguousarray(canvas)


# 功能：绘制或渲染 `_render_camera_tile` 对应的`compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tile`（CameraTile）：`tile` 对应的业务输入值
#   - `tile_size`（tuple[int, int]）：`tile_size` 对应的数量或大小
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/compositor.py` 的 `compose_channel_frame` 调用本符号
#   - 内部调用：`render_placeholder`、`letterbox`、`str`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _render_camera_tile(tile: CameraTile, tile_size: tuple[int, int]) -> np.ndarray:
    if not tile.online:
        explanation = tile.detail or "offline"
        image = render_placeholder(tile.camera_name, explanation, tile_size)
    else:
        try:
            image = letterbox(tile.frame, tile_size)
        except (ValueError, cv2.error):
            explanation = tile.detail or str(tile.reason) or "unavailable frame"
            image = render_placeholder(tile.camera_name, explanation, tile_size)
    return image


# 功能：Compose the latest camera frames in input order into a fixed grid；输入与输出详见下方说明
# 参数：
#   - `tiles`（Iterable[CameraTile]）：`tiles` 对应的业务输入值
#   - `tile_size`（tuple[int, int]）：`tile_size` 对应的数量或大小；默认值为 `(640, 360)`
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_compose_channel_frame_uses_expected_grid_shapes`
#         调用本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_compose_channel_frame_rejects_empty_or_too_many_tiles`
#         调用本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的 `test_compose_channel_frame_places_tiles_in_input_order`
#         调用本符号；`AiVision/tests/test_logistics_channel_compositor.py` 的
#         `test_live_camera_frame_top_pixels_are_not_covered_by_status_banner` 调用本符号；另有 4 处静态调用
#   - 内部调用：`_validated_size`、`list`、`layout_for_count`、`len`、`np.empty`、`render_placeholder`、`range`、`divmod`、`isinstance`、`ValueError`
#          等共 12 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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
