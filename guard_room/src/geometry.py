# geometry.py
from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import cv2
import numpy as np

from .types import BBox


Point = Tuple[int, int]


def bbox_iou(a: BBox, b: BBox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    x_left = max(ax1, bx1)
    y_top = max(ay1, by1)
    x_right = min(ax2, bx2)
    y_bottom = min(ay2, by2)
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    inter = (x_right - x_left) * (y_bottom - y_top)
    area_a = max(0, ax2 - ax1) * (ay2 - ay1)
    area_b = max(0, bx2 - bx1) * (by2 - by1)
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0

def bbox_center(bbox: BBox) -> Tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def bbox_height(bbox: BBox) -> float:
    return float(max(1, bbox[3] - bbox[1]))


def center_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return float(np.linalg.norm(np.array(a, dtype=np.float32) - np.array(b, dtype=np.float32)))


def polygon_to_np(polygon: Iterable[Point]) -> np.ndarray:
    return np.array(list(polygon), dtype=np.int32)
