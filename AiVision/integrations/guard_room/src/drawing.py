# 文件说明：实现`drawing` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# drawing.py
"""
画面标注工具模块。

提供一组无状态的绘图函数，用于在 numpy 帧上叠加检测框、多边形区域、
调试文字和报警横幅，所有函数均直接修改传入的 frame（in-place）。
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

import cv2
import numpy as np

from .geometry import polygon_to_np
from .types import AlarmEvent, Detection


# 功能：在画面上绘制封闭多边形区域及其标签；输入与输出详见下方说明
# 参数：
#   - `frame`（np.ndarray）：待处理的视频图像帧
#   - `polygon`（Sequence[tuple[int, int]]）：`polygon` 对应的业务输入值
#   - `label`（str）：`label` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_draw_camera` 调用本符号
#   - 内部调用：`len`、`polygon_to_np(polygon).reshape`、`polygon_to_np`、`cv2.polylines`、`cv2.putText`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def draw_polygon(
    frame: np.ndarray,
    polygon: Sequence[tuple[int, int]],
    label: str,
) -> None:
    """在画面上绘制封闭多边形区域及其标签。

    用于标注监控区域、禁区边界等兴趣区域。
    顶点数不足 3 个或 polygon 为 None 时静默跳过，不抛出异常。

    Args:
        frame:   BGR 格式的原始视频帧，in-place 修改。
        polygon: 多边形顶点列表 [(x1,y1), (x2,y2), ...]，至少 3 个点。
        label:   显示在第一个顶点左上角的区域名称。
    """
    if polygon is None or len(polygon) < 3:
        return
    pts = polygon_to_np(polygon).reshape((-1, 1, 2))    # reshape 为 polylines 要求的形状
    cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 255), thickness=2)
    x, y = polygon[0]
    cv2.putText(frame, label, (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)


# 功能：在画面上绘制单个检测框及其标签；输入与输出详见下方说明
# 参数：
#   - `frame`（np.ndarray）：待处理的视频图像帧
#   - `det`（Detection）：`det` 对应的业务输入值
#   - `label`（str）：`label` 对应的业务输入值
#   - `color`（未显式标注）：`color` 对应的业务输入值；默认值为 `(0, 255, 0)`
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_draw_camera` 调用本符号
#   - 内部调用：`cv2.rectangle`、`cv2.putText`、`max`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def draw_detection(
    frame: np.ndarray,
    det: Detection,
    label: str,
    color=(0, 255, 0),
) -> None:
    """在画面上绘制单个检测框及其标签。

    Args:
        frame: BGR 格式的原始视频帧，in-place 修改。
        det:   Detection 对象，提供 bbox (x1, y1, x2, y2)。
        label: 显示在检测框左上角的文字（如类别名、置信度、track_id）。
        color: BGR 颜色元组，默认绿色。
    """
    x1, y1, x2, y2 = det.bbox
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    # max(20, y1-8)：防止文字因目标贴近画面顶部而被裁剪
    cv2.putText(frame, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


# 功能：在画面左上角逐行绘制调试信息；输入与输出详见下方说明
# 参数：
#   - `frame`（np.ndarray）：待处理的视频图像帧
#   - `lines`（Iterable[str]）：`lines` 对应的业务输入值
#   - `origin`（未显式标注）：`origin` 对应的业务输入值；默认值为 `(20, 30)`
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`enumerate`、`cv2.putText`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def draw_debug_text(
    frame: np.ndarray,
    lines: Iterable[str],
    origin=(20, 30),
) -> None:
    """在画面左上角逐行绘制调试信息。

    每行行高固定为 26 像素，适合叠加规则状态、帧率、计数等实时数值。
    仅在 RuntimeConfig.draw_debug=True 时由上层调用，不影响生产性能。

    Args:
        frame:  BGR 格式的原始视频帧，in-place 修改。
        lines:  要逐行显示的字符串列表，按传入顺序从上到下排列。
        origin: 第一行文字左下角的起始坐标，默认 (20, 30)。
    """
    x, y = origin
    for idx, line in enumerate(lines):
        cv2.putText(frame, line, (x, y + idx * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 180, 255), 2)


# 功能：在画面顶部绘制红色报警横幅，显示报警类型与原因；输入与输出详见下方说明
# 参数：
#   - `frame`（np.ndarray）：待处理的视频图像帧
#   - `event`（Optional[AlarmEvent]）：待处理的事件对象
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
#   - 内部调用：`cv2.rectangle`、`cv2.putText`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def draw_alarm_banner(
    frame: np.ndarray,
    event: Optional[AlarmEvent],
) -> None:
    """在画面顶部绘制红色报警横幅，显示报警类型与原因。

    event 为 None 时静默跳过，调用方无需在外部判断。
    横幅覆盖画面顶部 48 像素区域，文字叠加于红底之上，视觉优先级最高。

    Args:
        frame: BGR 格式的原始视频帧，in-place 修改。
        event: 当前最新的报警事件；无报警时传 None。
    """
    if event is None:
        return
    text = f"ALARM: {event.event_type} | track={event.track_id} | {event.reason}"
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 48), (0, 0, 255), -1)    # 红色实心背景
    cv2.putText(frame, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)