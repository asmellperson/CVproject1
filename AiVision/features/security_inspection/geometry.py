"""已校验多边形的相交计算，支持凹多边形。"""

from collections.abc import Sequence
import cv2
import numpy as np

Point = list[float]
Polygon = list[Point]


def _point_on_segment(point: Sequence[float], start: Sequence[float], end: Sequence[float]) -> bool:
    """以随坐标尺度变化的容差判断点在线段上，包含端点。"""
    px, py = point
    x1, y1 = start
    x2, y2 = end
    cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
    tolerance = 1e-09 * max(1.0, abs(px), abs(py), abs(x1), abs(y1), abs(x2), abs(y2))
    if abs(cross) > tolerance:
        return False
    return (
        min(x1, x2) - tolerance <= px <= max(x1, x2) + tolerance
        and min(y1, y2) - tolerance <= py <= max(y1, y2) + tolerance
    )


def _clip_polygon_to_rect(polygon: Polygon, rect: Sequence[float]) -> Polygon:
    """用 Sutherland–Hodgman 把简单多边形裁剪到轴对齐矩形。"""
    x1, y1, x2, y2 = rect

    def clip(vertices: Polygon, inside, intersection) -> Polygon:
        """按单个边界保留内侧顶点并补入交点，供矩形四边依次裁剪。"""
        if not vertices:
            return []
        result: Polygon = []
        previous = vertices[-1]
        previous_inside = inside(previous)
        for current in vertices:
            current_inside = inside(current)
            if current_inside:
                if not previous_inside:
                    result.append(intersection(previous, current))
                result.append(current)
            elif previous_inside:
                result.append(intersection(previous, current))
            previous = current
            previous_inside = current_inside
        return result

    def at_x(start: Point, end: Point, x: float) -> Point:
        """求线段与竖直边界的交点，避免近似竖直线段除零。"""
        dx = end[0] - start[0]
        if abs(dx) <= 1e-12:
            return [x, start[1]]
        ratio = (x - start[0]) / dx
        return [x, start[1] + ratio * (end[1] - start[1])]

    def at_y(start: Point, end: Point, y: float) -> Point:
        """求线段与水平边界的交点，避免近似水平线段除零。"""
        dy = end[1] - start[1]
        if abs(dy) <= 1e-12:
            return [start[0], y]
        ratio = (y - start[1]) / dy
        return [start[0] + ratio * (end[0] - start[0]), y]

    clipped = clip(polygon, lambda point: point[0] >= x1, lambda start, end: at_x(start, end, x1))
    clipped = clip(clipped, lambda point: point[0] <= x2, lambda start, end: at_x(start, end, x2))
    clipped = clip(clipped, lambda point: point[1] >= y1, lambda start, end: at_y(start, end, y1))
    return clip(clipped, lambda point: point[1] <= y2, lambda start, end: at_y(start, end, y2))


def _cross(start: Point, end: Point, point: Point) -> float:
    """用有向叉积表示点在线段的哪一侧。"""
    return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])


def _segments_intersect_or_touch(first_start: Point, first_end: Point, second_start: Point, second_end: Point) -> bool:
    """判定线段穿越、端点接触或共线重叠，供简单多边形校验。"""
    crosses = (
        _cross(first_start, first_end, second_start),
        _cross(first_start, first_end, second_end),
        _cross(second_start, second_end, first_start),
        _cross(second_start, second_end, first_end),
    )
    tolerance = 1e-09 * max(
        1.0, *(abs(value) for point in (first_start, first_end, second_start, second_end) for value in point)
    )
    if abs(crosses[0]) <= tolerance and _point_on_segment(second_start, first_start, first_end):
        return True
    if abs(crosses[1]) <= tolerance and _point_on_segment(second_end, first_start, first_end):
        return True
    if abs(crosses[2]) <= tolerance and _point_on_segment(first_start, second_start, second_end):
        return True
    if abs(crosses[3]) <= tolerance and _point_on_segment(first_end, second_start, second_end):
        return True
    return (
        crosses[0] > tolerance and crosses[1] < -tolerance or (crosses[0] < -tolerance and crosses[1] > tolerance)
    ) and (crosses[2] > tolerance and crosses[3] < -tolerance or (crosses[2] < -tolerance and crosses[3] > tolerance))


def validate_polygon(name: str, points: Polygon) -> None:
    """拒绝重复顶点、重叠相邻边和非相邻边接触或自交。"""
    unique_points = {tuple(point) for point in points}
    if len(unique_points) < 3:
        raise ValueError(f"ROI '{name}': 少于 3 个唯一顶点")
    if len(unique_points) != len(points):
        raise ValueError(f"ROI '{name}': 存在重复顶点或零长度边，首尾重复也不允许")
    edge_count = len(points)
    for index, current in enumerate(points):
        previous = points[index - 1]
        following = points[(index + 1) % edge_count]
        tolerance = 1e-09 * max(1.0, *(abs(value) for point in (previous, current, following) for value in point))
        if abs(_cross(previous, current, following)) <= tolerance and (
            _point_on_segment(following, previous, current) or _point_on_segment(previous, current, following)
        ):
            raise ValueError(f"ROI '{name}': 相邻边重叠")
    for first_index in range(edge_count):
        first_start = points[first_index]
        first_end = points[(first_index + 1) % edge_count]
        for second_index in range(first_index + 1, edge_count):
            if second_index == first_index + 1:
                continue
            if first_index == 0 and second_index == edge_count - 1:
                continue
            second_start = points[second_index]
            second_end = points[(second_index + 1) % edge_count]
            if _segments_intersect_or_touch(first_start, first_end, second_start, second_end):
                raise ValueError(f"ROI '{name}': 非相邻边自相交或接触")


def bbox_in_roi(box, polygon, threshold):
    """人体框中心在区域内或区域覆盖框面积达到阈值时，视为进入 ROI。"""
    x1, y1, x2, y2 = box
    area = (x2 - x1) * (y2 - y1)
    if x2 <= x1 or y2 <= y1:
        return False
    contour = np.asarray(polygon, dtype=np.float32)
    if cv2.pointPolygonTest(contour, ((x1 + x2) / 2, (y1 + y2) / 2), False) >= 0:
        return True
    clipped = _clip_polygon_to_rect(polygon, box)
    overlap = cv2.contourArea(np.asarray(clipped, dtype=np.float32)) if len(clipped) >= 3 else 0.0
    return overlap > 0 and overlap / area >= threshold
