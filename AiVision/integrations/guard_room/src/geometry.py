# 文件说明：实现几何计算相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# geometry.py
"""
几何计算工具模块。

提供检测框（BBox）与多边形相关的纯函数，不依赖任何状态，
可在检测、行为分析、绘图等模块中复用。
"""
from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np

from .types import BBox


Point = Tuple[int, int]


# 功能：计算两个检测框的交并比（IoU）；输入与输出详见下方说明
# 参数：
#   - `a`（BBox）：`a` 对应的业务输入值
#   - `b`（BBox）：`b` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`max`、`min`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def bbox_iou(a: BBox, b: BBox) -> float:
    """计算两个检测框的交并比（IoU）。

    IoU = 交集面积 / 并集面积，取值范围 [0, 1]。
    常用于判断两个框的重叠程度：NMS 去重、目标匹配等场景。
    无交集或面积为零时返回 0.0，不抛出异常。

    Args:
        a: 检测框 (x1, y1, x2, y2)。
        b: 检测框 (x1, y1, x2, y2)。

    Returns:
        IoU 值，范围 [0.0, 1.0]。
    """
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    # 交集区域的左上角取较大值，右下角取较小值
    x_left = max(ax1, bx1)
    y_top = max(ay1, by1)
    x_right = min(ax2, bx2)
    y_bottom = min(ay2, by2)

    if x_right <= x_left or y_bottom <= y_top:
        return 0.0  # 无交集

    inter = (x_right - x_left) * (y_bottom - y_top)
    area_a = max(0, ax2 - ax1) * (ay2 - ay1)
    area_b = max(0, bx2 - bx1) * (by2 - by1)
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


# 功能：返回检测框的中心点坐标 (cx, cy)；输入与输出详见下方说明
# 参数：
#   - `bbox`（BBox）：`bbox` 对应的业务输入值
# 返回：Tuple[float, float]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def bbox_center(bbox: BBox) -> Tuple[float, float]:
    """返回检测框的中心点坐标 (cx, cy)。"""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


# 功能：返回检测框的高度（像素），最小值为 1，避免后续做除数时出现零除；输入与输出详见下方说明
# 参数：
#   - `bbox`（BBox）：`bbox` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`float`、`max`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def bbox_height(bbox: BBox) -> float:
    """返回检测框的高度（像素），最小值为 1，避免后续做除数时出现零除。"""
    return float(max(1, bbox[3] - bbox[1]))


# 功能：计算两个中心点之间的欧氏距离（像素）；输入与输出详见下方说明
# 参数：
#   - `a`（Tuple[float, float]）：`a` 对应的业务输入值
#   - `b`（Tuple[float, float]）：`b` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`float`、`np.linalg.norm`、`np.array`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def center_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """计算两个中心点之间的欧氏距离（像素）。

    Args:
        a: 点坐标 (x, y)。
        b: 点坐标 (x, y)。

    Returns:
        两点间的欧氏距离（浮点数，像素单位）。
    """
    return float(np.linalg.norm(np.array(a, dtype=np.float32) - np.array(b, dtype=np.float32)))


# 功能：将多边形顶点列表转换为 OpenCV 所需的 int32 numpy 数组；输入与输出详见下方说明
# 参数：
#   - `polygon`（Iterable[Point]）：`polygon` 对应的业务输入值
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`np.array`、`list`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def polygon_to_np(polygon: Iterable[Point]) -> np.ndarray:
    """将多边形顶点列表转换为 OpenCV 所需的 int32 numpy 数组。

    转换后的数组可直接传入 cv2.polylines / cv2.fillPoly 等函数。

    Args:
        polygon: 顶点坐标的可迭代对象，每个元素为 (x, y) 整数元组。

    Returns:
        形状为 (N, 2) 的 int32 数组，N 为顶点数。
    """
    return np.array(list(polygon), dtype=np.int32)