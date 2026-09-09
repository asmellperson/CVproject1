"""
只负责把已经画好检测结果的Camera frame拼成物流通道画面（物流通道多路监控拼接器）
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

from .constants import MAX_CAMERAS_PER_CHANNEL

try:  
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  
    Image = ImageDraw = ImageFont = None


_MAX_TILE_SIDE = 4096
_DEFAULT_FILL_COLOR = (28, 28, 28)
_MAX_TEXT_LENGTH = 80
_LOGGER = logging.getLogger(__name__)
_CJK_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
)

# 一台摄像头最新帧的检测结果
@dataclass(frozen=True)
class CameraTile:

    camera_id: int
    camera_name: str
    frame: np.ndarray | None
    reason: str
    person_count: int | None
    online: bool
    detail: str = ""

def layout_for_count(count: int) -> tuple[int, int]:
    """最多九台，由于受九宫格compositor设计驱动"""
    if not isinstance(count, Integral) or isinstance(count, bool) or not 1 <= count <= MAX_CAMERAS_PER_CHANNEL:
        raise ValueError("摄像头数量必须是1到9的整数")
    if count == 1:
        return 1, 1
    if count == 2:
        return 1, 2
    if count <= 4:
        return 2, 2
    return 3, 3

def _validated_size(target_size: tuple[int, int]) -> tuple[int, int]:
    if not isinstance(target_size, tuple) or len(target_size) != 2:
        raise ValueError("target_size 必须是一个 (宽度，高度) 元组")
    width, height = target_size
    if (
        not isinstance(width, Integral)
        or isinstance(width, bool)
        or not isinstance(height, Integral)
        or isinstance(height, bool)
        or not 0 < width <= _MAX_TILE_SIDE
        or not 0 < height <= _MAX_TILE_SIDE
    ):
        raise ValueError(f"target_size 的值必须是 1 到 {_MAX_TILE_SIDE} 之间的整数")
    return int(width), int(height)

def _as_bgr(frame: np.ndarray | None) -> np.ndarray:
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.size == 0:
        raise ValueError("frame 必须是一张非空的 uint8 类型图像")
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if frame.ndim != 3:
        raise ValueError("frame 必须为二维，或是带有通道维度的图像")
    if frame.shape[2] == 3:
        return frame.copy()
    if frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    raise ValueError("frame（图像帧）的通道数必须为 1、3 或 4")

def letterbox(
    frame: np.ndarray | None,
    target_size: tuple[int, int] = (640, 360),
    fill_color: tuple[int, int, int] = _DEFAULT_FILL_COLOR,
) -> np.ndarray:
    """把不同分辨率画面缩进放进640*360的统一格子（保存比例，不拉伸）"""
    target_width, target_height = _validated_size(target_size)
    if not isinstance(fill_color, tuple) or len(fill_color) != 3:
        raise ValueError("fill_color 必须是一个 BGR 三元组")
    try:
        bgr = _as_bgr(frame)
    except cv2.error as error:
        raise ValueError("frame（图像帧）无法转换为 BGR 格式") from error

    source_height, source_width = bgr.shape[:2]
    scale = min(target_width / source_width, target_height / source_height)
    resized_width = max(1, min(target_width, round(source_width * scale)))
    resized_height = max(1, min(target_height, round(source_height * scale)))
    try:
        resized = cv2.resize(bgr, (resized_width, resized_height), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    except cv2.error as error:
        raise ValueError("frame（图像帧）无法完成缩放") from error

    canvas = np.full((target_height, target_width, 3), fill_color, dtype=np.uint8)
    x_offset = (target_width - resized_width) // 2
    y_offset = (target_height - resized_height) // 2
    canvas[y_offset : y_offset + resized_height, x_offset : x_offset + resized_width] = resized
    return np.ascontiguousarray(canvas)

def _display_text(value: object, fallback: str) -> str:
    text = str(value or fallback)
    visible = "".join(" " if character in "\n\r" else character for character in text if not unicodedata.category(character).startswith("C"))
    return visible.strip()[:_MAX_TEXT_LENGTH] or fallback

@lru_cache(maxsize=1)
def _available_font_paths() -> tuple[str, ...]:
    """一次性解析中日韩（CJK）候选字体，而非在每一帧渲染时都扫描。"""
    return tuple(path for path in _CJK_FONT_PATHS if Path(path).is_file())

@lru_cache(maxsize=32)
def _load_font(font_path: str | None, size: int):
    if ImageFont is None:
        return None
    candidates = (font_path,) if font_path else _available_font_paths()
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, ValueError) as error:
            _LOGGER.warning("无法加载物流信息叠加层字体 %s: %s", candidate, error)
    try:
        return ImageFont.load_default()
    except OSError as error:
        _LOGGER.warning("无法加载 Pillow 备用字体: %s", error)
        return None

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
    """尽可能就地绘制 Unicode 文本，并配置安全的 OpenCV 兜底方案。"""
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
                _LOGGER.warning("无法渲染 Unicode 编码的物流叠加文字: %s", error)

    fallback = visible_text.encode("ascii", "replace").decode("ascii")
    if not fallback.strip(" ?"):
        fallback = "text"
    if max_width:
        fallback = fallback[: max(1, max_width // max(5, font_size // 2))]
    cv2.putText(image, fallback, origin, cv2.FONT_HERSHEY_SIMPLEX, max(0.3, font_size / 30), color, 1, cv2.LINE_AA)
    return image

def render_placeholder(camera_name: str, detail: str, target_size: tuple[int, int] = (640, 360)) -> np.ndarray:
    """为离线帧、等待帧或无效帧生成稳定的 BGR 图像。"""
    width, height = _validated_size(target_size)
    canvas = np.full((height, width, 3), (45, 45, 45), dtype=np.uint8)
    cv2.rectangle(canvas, (0, 0), (width - 1, height - 1), (100, 100, 100), 1)
    name = _display_text(camera_name, "camera")
    explanation = _display_text(detail, "waiting for frame")
    font_size = max(10, min(24, width // 28))
    _draw_text(canvas, name, (8, max(font_size + 4, height // 2 - font_size)), (235, 235, 235), font_size=font_size, max_width=width - 16)
    _draw_text(canvas, explanation, (8, min(height - 6, height // 2 + font_size + 4)), (180, 180, 180), font_size=max(9, font_size - 3), max_width=width - 16)
    return np.ascontiguousarray(canvas)

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

def compose_channel_frame(tiles: Iterable[CameraTile], tile_size: tuple[int, int] = (640, 360)) -> np.ndarray:
    """将最新的帧按照输入顺序拼接成固定网格画面。"""
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
