"""警戒线与过闸线共用的边界、方向标记绘制。"""

import cv2
import numpy as np


BOUNDARY_COLOR = (238, 211, 34)
DIRECTION_COLOR = (255, 248, 224)
ALARM_SIDE_COLOR = (56, 189, 248)
_OUTLINE_COLOR = (42, 23, 15)
_REFERENCE_EDGE = 720


def _draw_path(frame: np.ndarray, points: np.ndarray, color: tuple[int, int, int], width: int) -> None:
    path = np.rint(points).astype(np.int32)
    # 细暗边保证亮色地面和复杂背景上的可读性，抗锯齿避免斜线出现明显台阶。
    cv2.polylines(frame, [path], False, _OUTLINE_COLOR, width + 2, lineType=cv2.LINE_AA)
    cv2.polylines(frame, [path], False, color, width, lineType=cv2.LINE_AA)


def draw_direction_line(
    frame: np.ndarray,
    points,
    directions: tuple[int, ...],
    *,
    direction_color: tuple[int, int, int] = DIRECTION_COLOR,
) -> None:
    """方向沿有序端点的法向显示；短双箭头与边界分离，保留原有正反向含义。"""
    if len(points) != 2:
        return
    endpoints = np.asarray(points, dtype=np.float64)
    delta = endpoints[1] - endpoints[0]
    length = float(np.linalg.norm(delta))
    if length <= 1e-6:
        return

    scale = max(0.75, min(frame.shape[:2]) / _REFERENCE_EDGE)
    width = max(1, round(2 * scale))
    tangent = delta / length
    normal = np.array([-tangent[1], tangent[0]])
    middle = endpoints.mean(axis=0)
    _draw_path(frame, endpoints, BOUNDARY_COLOR, width)

    for direction in directions:
        forward = normal * direction
        for distance in (22, 34):
            tip = middle + forward * distance * scale
            base = tip - forward * 7 * scale
            chevron = np.array([base - tangent * 8 * scale, tip, base + tangent * 8 * scale])
            _draw_path(frame, chevron, direction_color, width)
