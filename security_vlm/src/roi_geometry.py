"""Security VLM 共用的矩形 ROI 几何判定。"""

import math
from collections.abc import Sequence


def _normalize_rect(values: Sequence[float]):
    """返回排序后的 (x1, y1, x2, y2)；无效输入返回 None。"""
    try:
        if len(values) < 4:
            return None
        x1, y1, x2, y2 = (float(values[index]) for index in range(4))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
        return None
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def bbox_roi_overlap_ratio(person_box, roi) -> float:
    """计算 person_box 与 ROI 交集面积占 person_box 面积的比例。"""
    box = _normalize_rect(person_box)
    region = _normalize_rect(roi)
    if box is None or region is None:
        return 0.0

    bx1, by1, bx2, by2 = box
    rx1, ry1, rx2, ry2 = region
    box_area = (bx2 - bx1) * (by2 - by1)
    if box_area <= 0 or rx2 <= rx1 or ry2 <= ry1:
        return 0.0

    intersection_width = max(0.0, min(bx2, rx2) - max(bx1, rx1))
    intersection_height = max(0.0, min(by2, ry2) - max(by1, ry1))
    return (intersection_width * intersection_height) / box_area


def bbox_belongs_to_roi(person_box, roi, min_overlap_ratio: float) -> bool:
    """中心点在 ROI 内或人体框重叠率达到阈值时，判定属于 ROI。"""
    box = _normalize_rect(person_box)
    region = _normalize_rect(roi)
    if box is None or region is None:
        return False

    bx1, by1, bx2, by2 = box
    rx1, ry1, rx2, ry2 = region
    if bx2 <= bx1 or by2 <= by1 or rx2 <= rx1 or ry2 <= ry1:
        return False

    center_x = (bx1 + bx2) / 2.0
    center_y = (by1 + by2) / 2.0
    if rx1 <= center_x <= rx2 and ry1 <= center_y <= ry2:
        return True

    threshold = min(1.0, max(0.0, float(min_overlap_ratio)))
    overlap_ratio = bbox_roi_overlap_ratio(box, region)
    return overlap_ratio > 0.0 and overlap_ratio >= threshold
