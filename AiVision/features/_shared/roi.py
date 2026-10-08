"""普通 Feature 的单个归一化 ROI：校验与原始帧坐标转换。"""
from __future__ import annotations

from typing import Annotated

import numpy as np
from pydantic import AfterValidator, Field, TypeAdapter

NormalizedCoordinate = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
NormalizedPoint = Annotated[list[NormalizedCoordinate], Field(min_length=2, max_length=2)]


def _validate_polygon(points: list[list[float]]) -> list[list[float]]:
    """允许空 ROI 表示全画面；非空多边形必须至少三点且面积非零。"""
    if not points:
        return points
    if len(points) < 3:
        raise ValueError("ROI 至少需要三个顶点；空列表表示全帧")
    area = sum(
        point[0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * point[1]
        for index, point in enumerate(points)
    )
    if abs(area) <= 1e-12:
        raise ValueError("ROI 面积必须大于零")
    return points


NormalizedRoi = Annotated[list[NormalizedPoint], AfterValidator(_validate_polygon)]

def _validate_line(points: list[list[float]]) -> list[list[float]]:
    """允许未配置的空线段；有效线段必须恰好包含两个不同端点。"""
    if points and (len(points) != 2 or points[0] == points[1]):
        raise ValueError("警戒线需要两个不同的归一化端点")
    return points


NormalizedLine = Annotated[list[NormalizedPoint], AfterValidator(_validate_line)]
ROI_ADAPTER = TypeAdapter(NormalizedRoi)
LINE_ADAPTER = TypeAdapter(NormalizedLine)


def roi_to_pixels(points: list[list[float]], shape: tuple[int, ...]) -> np.ndarray:
    """只接受单个归一化多边形；每次使用实际帧宽高，空 ROI 取全帧。"""
    normalized = ROI_ADAPTER.validate_python(points)
    if not normalized:
        normalized = [[0, 0], [1, 0], [1, 1], [0, 1]]
    height, width = shape[:2]
    if width <= 0 or height <= 0:
        raise ValueError("摄像头帧尺寸无效")
    return np.rint(np.asarray(normalized) * [width, height]).astype(np.int32)
