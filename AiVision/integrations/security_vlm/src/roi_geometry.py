# 文件说明：实现感兴趣区域、几何计算相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""Security VLM 共用的 ROI 标准化、校验与多边形几何判定。"""

import math
from collections.abc import Mapping, Sequence
from typing import Any


Point = list[float]
Polygon = list[Point]
ROI_COORD_DECIMALS = 2
DEFAULT_MAX_VERTICES = 64


# 功能：检查或判断 `_is_sequence` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（Any）：待转换、校验或写入的值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `normalize_roi_points`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `point_in_polygon`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `validate_rois` 调用本符号
#   - 内部调用：`isinstance`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


# 功能：实现 `_finite_float` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（Any）：待转换、校验或写入的值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `normalize_roi_points`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `scale_roi_mapping`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `roi_mapping_exceeds_bounds`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `point_in_polygon` 调用本符号；另有 1 处静态调用
#   - 内部调用：`isinstance`、`ValueError`、`float`、`math.isfinite`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _finite_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("坐标必须是 JSON 数字")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("坐标必须是数字") from exc
    if not math.isfinite(result):
        raise ValueError("坐标必须是有限值")
    return result


# 功能：返回排序后的 (x1, y1, x2, y2)；无效输入返回 None；输入与输出详见下方说明
# 参数：
#   - `values`（Sequence[float]）：`values` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `bbox_roi_overlap_ratio_normalized`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `bbox_belongs_to_normalized_roi` 调用本符号
#   - 内部调用：`len`、`float`、`range`、`all`、`math.isfinite`、`min`、`max`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：把旧矩形或多边形 ROI 规范化为 ``[[x, y], ...]``；输入与输出详见下方说明
# 参数：
#   - `values`（Any）：`values` 对应的业务输入值
# 返回：Polygon；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `scale_roi_mapping`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `roi_mapping_exceeds_bounds`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `polygon_area`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `roi_bounds` 调用本符号；另有 9 处静态调用
#   - 内部调用：`_is_sequence`、`ValueError`、`len`、`any`、`_finite_float`、`sorted`、`enumerate`、`points.append`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def normalize_roi_points(values: Any) -> Polygon:
    """把旧矩形或多边形 ROI 规范化为 ``[[x, y], ...]``。"""
    if not _is_sequence(values):
        raise ValueError("ROI 必须是坐标列表")

    if len(values) == 4 and not any(_is_sequence(value) for value in values):
        x1, y1, x2, y2 = (_finite_float(value) for value in values)
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        return [
            [left, top],
            [right, top],
            [right, bottom],
            [left, bottom],
        ]

    if len(values) < 3:
        raise ValueError("多边形至少 3 个点")

    points: Polygon = []
    for index, value in enumerate(values, start=1):
        if not _is_sequence(value) or len(value) != 2:
            raise ValueError(f"第 {index} 个点坐标必须为 [x, y]")
        points.append([_finite_float(value[0]), _finite_float(value[1])])
    return points


# 功能：按每台摄像头的源/目标帧尺寸缩放 ROI，保持多边形顶点结构；输入与输出详见下方说明
# 参数：
#   - `rois`（Any）：`rois` 对应的业务输入值
#   - `source_width`（float）：`source_width` 对应的业务输入值
#   - `source_height`（float）：`source_height` 对应的业务输入值
#   - `target_width`（float）：`target_width` 对应的业务输入值
#   - `target_height`（float）：`target_height` 对应的业务输入值
# 返回：dict[str, Polygon]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::load_rois`
#         调用本符号；`AiVision/integrations/security_vlm/src/session_worker.py` 的 `reload_rois` 调用本符号
#   - 内部调用：`_finite_float`、`any`、`ValueError`、`isinstance`、`rois.items`、`str`、`round`、`normalize_roi_points`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def scale_roi_mapping(
    rois: Any,
    source_width: float,
    source_height: float,
    target_width: float,
    target_height: float,
) -> dict[str, Polygon]:
    """按每台摄像头的源/目标帧尺寸缩放 ROI，保持多边形顶点结构。"""
    dimensions = (
        _finite_float(source_width),
        _finite_float(source_height),
        _finite_float(target_width),
        _finite_float(target_height),
    )
    if any(value <= 0 for value in dimensions):
        raise ValueError("ROI 源尺寸和目标尺寸必须为正数")
    if not isinstance(rois, Mapping):
        raise ValueError("staff_rois 必须是字典")

    source_w, source_h, target_w, target_h = dimensions
    scale_x = target_w / source_w
    scale_y = target_h / source_h
    scaled: dict[str, Polygon] = {}
    for name, values in rois.items():
        scaled[str(name)] = [
            [
                round(x * scale_x, ROI_COORD_DECIMALS),
                round(y * scale_y, ROI_COORD_DECIMALS),
            ]
            for x, y in normalize_roi_points(values)
        ]
    return scaled


# 功能：判断任一 ROI 坐标是否明显超出当前帧，用于旧文件安全迁移；输入与输出详见下方说明
# 参数：
#   - `rois`（Any）：`rois` 对应的业务输入值
#   - `width`（float）：`width` 对应的业务输入值
#   - `height`（float）：`height` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::load_rois`
#         调用本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::_migrate_legacy_roi_dimensions` 调用本符号
#   - 内部调用：`_finite_float`、`ValueError`、`isinstance`、`any`、`rois.values`、`normalize_roi_points`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def roi_mapping_exceeds_bounds(rois: Any, width: float, height: float) -> bool:
    """判断任一 ROI 坐标是否明显超出当前帧，用于旧文件安全迁移。"""
    frame_width = _finite_float(width)
    frame_height = _finite_float(height)
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("画面尺寸必须为正数")
    if not isinstance(rois, Mapping):
        raise ValueError("staff_rois 必须是字典")
    return any(
        x < 0 or y < 0 or x > frame_width or y > frame_height
        for values in rois.values()
        for x, y in normalize_roi_points(values)
    )


# 功能：使用鞋带公式计算多边形面积；输入与输出详见下方说明
# 参数：
#   - `points`（Any）：`points` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`normalize_roi_points`、`enumerate`、`len`、`abs`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def polygon_area(points: Any) -> float:
    """使用鞋带公式计算多边形面积。"""
    polygon = normalize_roi_points(points)
    signed_twice_area = 0.0
    for index, point in enumerate(polygon):
        next_point = polygon[(index + 1) % len(polygon)]
        signed_twice_area += (
            point[0] * next_point[1] - next_point[0] * point[1]
        )
    return abs(signed_twice_area) / 2.0


# 功能：返回 ROI 多边形的外接矩形 ``[x1, y1, x2, y2]``；输入与输出详见下方说明
# 参数：
#   - `points`（Any）：`points` 对应的业务输入值
# 返回：list[float]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/session_worker.py` 的 `PairSessionManager::step` 调用本符号
#   - 内部调用：`normalize_roi_points`、`min`、`max`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def roi_bounds(points: Any) -> list[float]:
    """返回 ROI 多边形的外接矩形 ``[x1, y1, x2, y2]``。"""
    polygon = normalize_roi_points(points)
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


# 功能：处理 `_point_on_segment` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `point`（Sequence[float]）：`point` 对应的业务输入值
#   - `start`（Sequence[float]）：`start` 对应的业务输入值
#   - `end`（Sequence[float]）：`end` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `point_in_normalized_polygon`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `_segments_intersect_or_touch`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `_validate_simple_polygon` 调用本符号
#   - 内部调用：`max`、`abs`、`min`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _point_on_segment(
    point: Sequence[float],
    start: Sequence[float],
    end: Sequence[float],
) -> bool:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
    tolerance = 1e-9 * max(
        1.0,
        abs(px),
        abs(py),
        abs(x1),
        abs(y1),
        abs(x2),
        abs(y2),
    )
    if abs(cross) > tolerance:
        return False
    return (
        min(x1, x2) - tolerance <= px <= max(x1, x2) + tolerance
        and min(y1, y2) - tolerance <= py <= max(y1, y2) + tolerance
    )


# 功能：判断点是否在已标准化多边形内部；边界点也视为内部；输入与输出详见下方说明
# 参数：
#   - `point`（Sequence[float]）：`point` 对应的业务输入值
#   - `polygon`（Polygon）：`polygon` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `point_in_polygon`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `bbox_belongs_to_normalized_roi` 调用本符号
#   - 内部调用：`enumerate`、`len`、`_point_on_segment`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def point_in_normalized_polygon(point: Sequence[float], polygon: Polygon) -> bool:
    """判断点是否在已标准化多边形内部；边界点也视为内部。"""
    px, py = point
    inside = False
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if _point_on_segment((px, py), start, end):
            return True
        y1, y2 = start[1], end[1]
        if (y1 > py) == (y2 > py):
            continue
        crossing_x = start[0] + (py - y1) * (end[0] - start[0]) / (y2 - y1)
        if crossing_x > px:
            inside = not inside
    return inside


# 功能：判断点是否在多边形内部；位于边界上的点也视为内部；输入与输出详见下方说明
# 参数：
#   - `point`（Any）：`point` 对应的业务输入值
#   - `roi`（Any）：感兴趣区域的坐标集合
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_is_sequence`、`len`、`_finite_float`、`normalize_roi_points`、`point_in_normalized_polygon`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def point_in_polygon(point: Any, roi: Any) -> bool:
    """判断点是否在多边形内部；位于边界上的点也视为内部。"""
    try:
        if not _is_sequence(point) or len(point) != 2:
            return False
        px, py = _finite_float(point[0]), _finite_float(point[1])
        polygon = normalize_roi_points(roi)
    except ValueError:
        return False
    return point_in_normalized_polygon((px, py), polygon)


# 功能：用 Sutherland–Hodgman 把简单多边形裁剪到轴对齐矩形；输入与输出详见下方说明
# 参数：
#   - `polygon`（Polygon）：`polygon` 对应的业务输入值
#   - `rect`（Sequence[float]）：`rect` 对应的业务输入值
# 返回：Polygon；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `bbox_roi_overlap_ratio_normalized` 调用本符号
#   - 内部调用：`clip`、`at_x`、`at_y`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _clip_polygon_to_rect(
    polygon: Polygon,
    rect: Sequence[float],
) -> Polygon:
    """用 Sutherland–Hodgman 把简单多边形裁剪到轴对齐矩形。"""
    x1, y1, x2, y2 = rect

    # 功能：实现 `clip` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `vertices`（Polygon）：`vertices` 对应的业务输入值
    #   - `inside`（未显式标注）：`inside` 对应的业务输入值
    #   - `intersection`（未显式标注）：`intersection` 对应的业务输入值
    # 返回：Polygon；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `_clip_polygon_to_rect` 调用本符号
    #   - 内部调用：`inside`、`result.append`、`intersection`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def clip(
        vertices: Polygon,
        inside,
        intersection,
    ) -> Polygon:
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

    # 功能：实现 `at_x` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `start`（Point）：`start` 对应的业务输入值
    #   - `end`（Point）：`end` 对应的业务输入值
    #   - `x`（float）：`x` 对应的业务输入值
    # 返回：Point；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `_clip_polygon_to_rect` 调用本符号
    #   - 内部调用：`abs`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def at_x(start: Point, end: Point, x: float) -> Point:
        dx = end[0] - start[0]
        if abs(dx) <= 1e-12:
            return [x, start[1]]
        ratio = (x - start[0]) / dx
        return [x, start[1] + ratio * (end[1] - start[1])]

    # 功能：实现 `at_y` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `start`（Point）：`start` 对应的业务输入值
    #   - `end`（Point）：`end` 对应的业务输入值
    #   - `y`（float）：`y` 对应的业务输入值
    # 返回：Point；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `_clip_polygon_to_rect` 调用本符号
    #   - 内部调用：`abs`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def at_y(start: Point, end: Point, y: float) -> Point:
        dy = end[1] - start[1]
        if abs(dy) <= 1e-12:
            return [start[0], y]
        ratio = (y - start[1]) / dy
        return [start[0] + ratio * (end[0] - start[0]), y]

    clipped = clip(
        polygon,
        lambda point: point[0] >= x1,
        lambda start, end: at_x(start, end, x1),
    )
    clipped = clip(
        clipped,
        lambda point: point[0] <= x2,
        lambda start, end: at_x(start, end, x2),
    )
    clipped = clip(
        clipped,
        lambda point: point[1] >= y1,
        lambda start, end: at_y(start, end, y1),
    )
    return clip(
        clipped,
        lambda point: point[1] <= y2,
        lambda start, end: at_y(start, end, y2),
    )


# 功能：实现 `_area_of_normalized_polygon` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `polygon`（Polygon）：`polygon` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `bbox_roi_overlap_ratio_normalized`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `bbox_belongs_to_normalized_roi`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `validate_rois` 调用本符号
#   - 内部调用：`len`、`enumerate`、`abs`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _area_of_normalized_polygon(polygon: Polygon) -> float:
    if len(polygon) < 3:
        return 0.0
    signed_twice_area = 0.0
    for index, point in enumerate(polygon):
        next_point = polygon[(index + 1) % len(polygon)]
        signed_twice_area += (
            point[0] * next_point[1] - next_point[0] * point[1]
        )
    return abs(signed_twice_area) / 2.0


# 功能：计算人体框与已标准化 ROI 的交叠率；输入与输出详见下方说明
# 参数：
#   - `person_box`（未显式标注）：`person_box` 对应的业务输入值
#   - `polygon`（Polygon）：`polygon` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `bbox_roi_overlap_ratio`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `bbox_belongs_to_normalized_roi` 调用本符号
#   - 内部调用：`_normalize_rect`、`_area_of_normalized_polygon`、`_clip_polygon_to_rect`、`min`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def bbox_roi_overlap_ratio_normalized(person_box, polygon: Polygon) -> float:
    """计算人体框与已标准化 ROI 的交叠率。"""
    box = _normalize_rect(person_box)
    if box is None:
        return 0.0

    bx1, by1, bx2, by2 = box
    box_area = (bx2 - bx1) * (by2 - by1)
    if box_area <= 0 or _area_of_normalized_polygon(polygon) <= 0:
        return 0.0

    clipped = _clip_polygon_to_rect(polygon, box)
    return min(1.0, _area_of_normalized_polygon(clipped) / box_area)


# 功能：计算 person_box 与 ROI 交集面积占 person_box 面积的比例；输入与输出详见下方说明
# 参数：
#   - `person_box`（未显式标注）：`person_box` 对应的业务输入值
#   - `roi`（未显式标注）：感兴趣区域的坐标集合
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`normalize_roi_points`、`bbox_roi_overlap_ratio_normalized`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def bbox_roi_overlap_ratio(person_box, roi) -> float:
    """计算 person_box 与 ROI 交集面积占 person_box 面积的比例。"""
    try:
        polygon = normalize_roi_points(roi)
    except ValueError:
        return 0.0
    return bbox_roi_overlap_ratio_normalized(person_box, polygon)


# 功能：使用已标准化 ROI 执行中心点或交叠率归属判定；输入与输出详见下方说明
# 参数：
#   - `person_box`（未显式标注）：`person_box` 对应的业务输入值
#   - `polygon`（Polygon）：`polygon` 对应的业务输入值
#   - `min_overlap_ratio`（float）：`min_overlap_ratio` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `bbox_belongs_to_roi`
#         调用本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `_overlay_on_frame`
#         调用本符号；`AiVision/integrations/security_vlm/src/session_worker.py` 的 `PairSessionManager::_tracks_for_roi` 调用本符号
#   - 内部调用：`_normalize_rect`、`_area_of_normalized_polygon`、`point_in_normalized_polygon`、`float`、`math.isfinite`、`min`、`max`、`bbox_roi_overlap_ratio_normalized`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def bbox_belongs_to_normalized_roi(
    person_box,
    polygon: Polygon,
    min_overlap_ratio: float,
) -> bool:
    """使用已标准化 ROI 执行中心点或交叠率归属判定。"""
    box = _normalize_rect(person_box)
    if box is None:
        return False

    bx1, by1, bx2, by2 = box
    if (
        bx2 <= bx1
        or by2 <= by1
        or _area_of_normalized_polygon(polygon) <= 0
    ):
        return False

    center_x = (bx1 + bx2) / 2.0
    center_y = (by1 + by2) / 2.0
    if point_in_normalized_polygon((center_x, center_y), polygon):
        return True

    try:
        threshold = float(min_overlap_ratio)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(threshold):
        return False
    threshold = min(1.0, max(0.0, threshold))
    overlap_ratio = bbox_roi_overlap_ratio_normalized(box, polygon)
    return overlap_ratio > 0.0 and overlap_ratio >= threshold


# 功能：中心点在 ROI 内或人体框重叠率达到阈值时，判定属于 ROI；输入与输出详见下方说明
# 参数：
#   - `person_box`（未显式标注）：`person_box` 对应的业务输入值
#   - `roi`（未显式标注）：感兴趣区域的坐标集合
#   - `min_overlap_ratio`（float）：`min_overlap_ratio` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`normalize_roi_points`、`bbox_belongs_to_normalized_roi`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def bbox_belongs_to_roi(person_box, roi, min_overlap_ratio: float) -> bool:
    """中心点在 ROI 内或人体框重叠率达到阈值时，判定属于 ROI。"""
    try:
        polygon = normalize_roi_points(roi)
    except ValueError:
        return False
    return bbox_belongs_to_normalized_roi(
        person_box,
        polygon,
        min_overlap_ratio,
    )


# 功能：实现 `_cross` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `start`（Point）：`start` 对应的业务输入值
#   - `end`（Point）：`end` 对应的业务输入值
#   - `point`（Point）：`point` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `_segments_intersect_or_touch`
#         调用本符号；`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `_validate_simple_polygon` 调用本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _cross(start: Point, end: Point, point: Point) -> float:
    return (
        (end[0] - start[0]) * (point[1] - start[1])
        - (end[1] - start[1]) * (point[0] - start[0])
    )


# 功能：实现 `_segments_intersect_or_touch` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `first_start`（Point）：`first_start` 对应的业务输入值
#   - `first_end`（Point）：`first_end` 对应的业务输入值
#   - `second_start`（Point）：`second_start` 对应的业务输入值
#   - `second_end`（Point）：`second_end` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `_validate_simple_polygon` 调用本符号
#   - 内部调用：`_cross`、`max`、`abs`、`_point_on_segment`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _segments_intersect_or_touch(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
) -> bool:
    crosses = (
        _cross(first_start, first_end, second_start),
        _cross(first_start, first_end, second_end),
        _cross(second_start, second_end, first_start),
        _cross(second_start, second_end, first_end),
    )
    tolerance = 1e-9 * max(
        1.0,
        *(abs(value) for point in (
            first_start,
            first_end,
            second_start,
            second_end,
        ) for value in point),
    )
    if abs(crosses[0]) <= tolerance and _point_on_segment(
        second_start,
        first_start,
        first_end,
    ):
        return True
    if abs(crosses[1]) <= tolerance and _point_on_segment(
        second_end,
        first_start,
        first_end,
    ):
        return True
    if abs(crosses[2]) <= tolerance and _point_on_segment(
        first_start,
        second_start,
        second_end,
    ):
        return True
    if abs(crosses[3]) <= tolerance and _point_on_segment(
        first_end,
        second_start,
        second_end,
    ):
        return True
    return (
        (crosses[0] > tolerance and crosses[1] < -tolerance)
        or (crosses[0] < -tolerance and crosses[1] > tolerance)
    ) and (
        (crosses[2] > tolerance and crosses[3] < -tolerance)
        or (crosses[2] < -tolerance and crosses[3] > tolerance)
    )


# 功能：检查或判断 `_validate_simple_polygon` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `points`（Polygon）：`points` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/roi_geometry.py` 的 `validate_rois` 调用本符号
#   - 内部调用：`tuple`、`len`、`ValueError`、`enumerate`、`max`、`abs`、`_cross`、`_point_on_segment`、`range`、`_segments_intersect_or_touch`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _validate_simple_polygon(name: str, points: Polygon) -> None:
    unique_points = {tuple(point) for point in points}
    if len(unique_points) < 3:
        raise ValueError(f"ROI '{name}': 舍入后少于 3 个唯一顶点")
    if len(unique_points) != len(points):
        raise ValueError(
            f"ROI '{name}': 存在重复顶点或零长度边，首尾重复也不允许"
        )

    edge_count = len(points)
    for index, current in enumerate(points):
        previous = points[index - 1]
        following = points[(index + 1) % edge_count]
        tolerance = 1e-9 * max(
            1.0,
            *(abs(value) for point in (
                previous,
                current,
                following,
            ) for value in point),
        )
        if abs(_cross(previous, current, following)) <= tolerance and (
            _point_on_segment(following, previous, current)
            or _point_on_segment(previous, current, following)
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
            if _segments_intersect_or_touch(
                first_start,
                first_end,
                second_start,
                second_end,
            ):
                raise ValueError(
                    f"ROI '{name}': 非相邻边自相交或接触"
                )


# 功能：校验并规范化一组命名 ROI；输入与输出详见下方说明
# 参数：
#   - `rois`（Any）：`rois` 对应的业务输入值
#   - `width`（Any）：`width` 对应的业务输入值
#   - `height`（Any）：`height` 对应的业务输入值
#   - `min_area`（Any）：`min_area` 对应的业务输入值
#   - `max_vertices`（Any）：`max_vertices` 对应的业务输入值；默认值为 `DEFAULT_MAX_VERTICES`
# 返回：dict[str, Polygon]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::save_rois` 调用本符号
#   - 内部调用：`isinstance`、`ValueError`、`_finite_float`、`rois.items`、`str(raw_name).strip`、`str`、`_is_sequence`、`len`、`normalize_roi_points`、`round`
#          等共 13 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def validate_rois(
    rois: Any,
    width: Any,
    height: Any,
    min_area: Any,
    max_vertices: Any = DEFAULT_MAX_VERTICES,
) -> dict[str, Polygon]:
    """校验并规范化一组命名 ROI。"""
    if not isinstance(rois, Mapping):
        raise ValueError("staff_rois 必须是字典")
    try:
        frame_width = _finite_float(width)
        frame_height = _finite_float(height)
        minimum_area = _finite_float(min_area)
    except ValueError as exc:
        raise ValueError(f"ROI 校验参数无效: {exc}") from exc
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("画面宽高必须大于 0")
    if minimum_area < 0:
        raise ValueError("ROI 最小面积不能小于 0")
    if (
        isinstance(max_vertices, bool)
        or not isinstance(max_vertices, int)
        or max_vertices < 3
    ):
        raise ValueError("ROI 最大顶点数必须是大于等于 3 的整数")

    normalized: dict[str, Polygon] = {}
    for raw_name, values in rois.items():
        name = str(raw_name).strip()
        display_name = name or "<空名称>"
        if not name:
            raise ValueError(f"ROI '{display_name}': 名称不能为空")
        if _is_sequence(values) and len(values) > max_vertices:
            raise ValueError(
                f"ROI '{display_name}': 顶点数 {len(values)} 超过限制 "
                f"{max_vertices}"
            )
        try:
            raw_points = normalize_roi_points(values)
        except ValueError as exc:
            raise ValueError(f"ROI '{display_name}': {exc}") from exc
        points = [
            [
                round(point[0], ROI_COORD_DECIMALS),
                round(point[1], ROI_COORD_DECIMALS),
            ]
            for point in raw_points
        ]

        if any(
            x < 0 or x > frame_width or y < 0 or y > frame_height
            for x, y in points
        ):
            raise ValueError(
                f"ROI '{display_name}': 顶点超出画面范围 "
                f"0..{frame_width:g} x 0..{frame_height:g}"
            )
        _validate_simple_polygon(display_name, points)
        area = _area_of_normalized_polygon(points)
        if area < minimum_area:
            raise ValueError(
                f"ROI '{display_name}': 面积 {area:g} 小于最小值 "
                f"{minimum_area:g}"
            )
        normalized[name] = points
    return normalized
