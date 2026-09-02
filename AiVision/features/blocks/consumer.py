# 文件说明：实现视频帧消费与检测的帧消费、判定与告警衔接逻辑。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
features/blocks/consumer.py
区域入侵检测消费者 — 人体脚底点位于警戒线入侵侧即告警。
"""
from __future__ import annotations
import cv2
import numpy as np
from AiVision.features._base.consumer import BaseFunctionConsumer


# 功能：区域入侵检测 — YOLO 人体检测 + 警戒线入侵侧存在告警；输入与输出详见下方说明
# 参数：无。
# 返回：BlocksConsumer；返回新建的 `BlocksConsumer` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class BlocksConsumer(BaseFunctionConsumer):
    """区域入侵检测 — YOLO 人体检测 + 警戒线入侵侧存在告警"""

    # 功能：blocks 使用全帧检测，警戒线负责过滤入侵侧，避免依赖复杂 ROI；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    # 返回：list[np.ndarray]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _get_roi(self, camera_id: int, frame: np.ndarray) -> list[np.ndarray]:
        """blocks 使用全帧检测，警戒线负责过滤入侵侧，避免依赖复杂 ROI。"""
        h, w = frame.shape[:2]
        self._roi_polygon_cache[camera_id] = [[[0, 0], [w, 0], [w, h], [0, h]]]
        return [frame]

    # 功能：全帧人体检测后，仅脚底点落在警戒线入侵侧的人触发告警；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `roi_list`（未显式标注）：`roi_list` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._value_config`、`self.config_cache.get`、`float`、`config.get`、`self.frame_cache.get`、`self._line_config`、`self._foot_ratio`、`self.dispatch_inference_sync`、`int`、`item.get`
    #          等共 21 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process(self, roi_list, camera_id):
        """全帧人体检测后，仅脚底点落在警戒线入侵侧的人触发告警。"""
        config = self._value_config(self.config_cache.get(camera_id, {}))
        conf = float(config.get("threshold", 0.3) or 0.3)
        frame = self.frame_cache.get(camera_id)
        line_points, alarm_side = self._line_config(config, frame)
        foot_ratio = self._foot_ratio(config)

        detections = self.dispatch_inference_sync(
            camera_id,
            "yolo_human",
            roi_list,
            task_meta={"conf": conf},
            timeout=1.0,
        )
        detections_by_roi = {int(item.get("roi_id", 0)): item.get("detections", []) for item in detections}
        results = []
        for roi_id in range(len(roi_list)):
            roi_detections = []
            intrusions = []
            for det in detections_by_roi.get(roi_id, []):
                enriched = dict(det)
                bbox = enriched.get("bbox") or []
                foot_point = self._foot_point(bbox, foot_ratio)
                side = self._point_side(line_points, foot_point) if line_points and foot_point is not None else 0.0
                intrusion = self._is_alarm_side(side, alarm_side) if line_points and foot_point is not None else False
                enriched["foot_point"] = foot_point
                enriched["line_side"] = side
                enriched["intrusion"] = intrusion
                roi_detections.append(enriched)
                if intrusion:
                    intrusions.append(enriched)
            results.append((
                len(intrusions) > 0,
                {
                    "detections": roi_detections,
                    "intrusions": intrusions,
                    "line_points": line_points,
                    "alarm_side": alarm_side,
                    "foot_ratio": foot_ratio,
                },
            ))
        return results

    # 功能：绘制警戒线、入侵侧方向、人体框和脚底点；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `result`（未显式标注）：`result` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.frame_cache.get`、`frame.copy`、`(msg or {}).get`、`int`、`self._draw_line`、`enumerate`、`(_msg or
    #          {}).get`、`det.get`、`bool`、`cv2.rectangle` 等共 14 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def post_process(self, camera_id, result):
        """绘制警戒线、入侵侧方向、人体框和脚底点。"""
        frame = self.frame_cache.get(camera_id)
        if frame is None:
            return None
        frame_copy = frame.copy()

        line_points = []
        alarm_side = 1
        for _alarm, msg in result or []:
            line_points = (msg or {}).get("line_points") or line_points
            alarm_side = int((msg or {}).get("alarm_side") or alarm_side)
            if line_points:
                break
        self._draw_line(frame_copy, line_points, alarm_side)

        for i, (alarm, _msg) in enumerate(result):
            for det in (_msg or {}).get("detections", []):
                x1, y1, x2, y2 = [int(v) for v in det.get("bbox", [0, 0, 0, 0])]
                intrusion = bool(det.get("intrusion"))
                color = (0, 0, 255) if intrusion else (34, 197, 94)
                cv2.rectangle(frame_copy, (x1, y1), (x2, y2), color, 2)
                foot_point = det.get("foot_point")
                if foot_point:
                    fx, fy = [int(v) for v in foot_point]
                    cv2.circle(frame_copy, (fx, fy), 5, color, -1)
                conf = float(det.get("confidence", 0.0))
                label = "intrusion" if intrusion else "person"
                cv2.putText(
                    frame_copy,
                    f"{label} {conf:.2f}",
                    (x1, max(0, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2,
                )
        return frame_copy

    # 功能：人体检测需要周期处理静止画面,避免有人站着不动时漏检；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `cfg`（dict）：运行配置对象
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        """人体检测需要周期处理静止画面,避免有人站着不动时漏检。"""
        return True

    # 功能：实现 `_foot_ratio` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `config`（dict）：运行配置对象
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/blocks/consumer.py` 的 `BlocksConsumer::_process` 调用本符号
    #   - 内部调用：`max`、`min`、`float`、`config.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _foot_ratio(config: dict) -> float:
        try:
            return max(0.0, min(1.0, float(config.get("foot_ratio", 0.93))))
        except (TypeError, ValueError):
            return 0.93

    # 功能：实现 `_line_config` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `config`（dict）：运行配置对象
    #   - `frame`（np.ndarray | None）：待处理的视频图像帧
    # 返回：tuple[list[list[float]], int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/blocks/consumer.py` 的 `BlocksConsumer::_process` 调用本符号
    #   - 内部调用：`config.get`、`cls._normalize_line_points`、`int`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @classmethod
    def _line_config(cls, config: dict, frame: np.ndarray | None) -> tuple[list[list[float]], int]:
        raw_points = config.get("line_points") or []
        points = cls._normalize_line_points(raw_points, frame)
        try:
            alarm_side = -1 if int(config.get("alarm_side", 1) or 1) < 0 else 1
        except (TypeError, ValueError):
            alarm_side = 1
        return points, alarm_side

    # 功能：转换或规范化 `_normalize_line_points` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `raw_points`（未显式标注）：`raw_points` 对应的业务输入值
    #   - `frame`（np.ndarray | None）：待处理的视频图像帧
    # 返回：list[list[float]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/blocks/consumer.py` 的 `BlocksConsumer::_line_config` 调用本符号
    #   - 内部调用：`isinstance`、`len`、`points.append`、`float`、`all`、`abs`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _normalize_line_points(raw_points, frame: np.ndarray | None) -> list[list[float]]:
        if not isinstance(raw_points, list) or len(raw_points) < 2:
            return []
        points = []
        for item in raw_points[:2]:
            if not isinstance(item, list) or len(item) < 2:
                return []
            try:
                points.append([float(item[0]), float(item[1])])
            except (TypeError, ValueError):
                return []
        if frame is not None and all(0.0 <= coord <= 1.0 for point in points for coord in point):
            h, w = frame.shape[:2]
            points = [[points[0][0] * w, points[0][1] * h], [points[1][0] * w, points[1][1] * h]]
        if abs(points[0][0] - points[1][0]) < 1e-6 and abs(points[0][1] - points[1][1]) < 1e-6:
            return []
        return points

    # 功能：实现 `_foot_point` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `bbox`（未显式标注）：`bbox` 对应的业务输入值
    #   - `foot_ratio`（float）：`foot_ratio` 对应的业务输入值
    # 返回：list[float] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/blocks/consumer.py` 的 `BlocksConsumer::_process` 调用本符号
    #   - 内部调用：`isinstance`、`len`、`float`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _foot_point(bbox, foot_ratio: float) -> list[float] | None:
        if not isinstance(bbox, list) or len(bbox) < 4:
            return None
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
        except (TypeError, ValueError):
            return None
        return [(x1 + x2) / 2.0, y1 + (y2 - y1) * foot_ratio]

    # 功能：实现 `_point_side` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `line_points`（list[list[float]]）：`line_points` 对应的业务输入值
    #   - `point`（list[float]）：`point` 对应的业务输入值
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/blocks/consumer.py` 的 `BlocksConsumer::_process` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _point_side(line_points: list[list[float]], point: list[float]) -> float:
        (x1, y1), (x2, y2) = line_points
        px, py = point
        return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)

    # 功能：检查或判断 `_is_alarm_side` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `side`（float）：`side` 对应的业务输入值
    #   - `alarm_side`（int）：`alarm_side` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/blocks/consumer.py` 的 `BlocksConsumer::_process` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _is_alarm_side(side: float, alarm_side: int) -> bool:
        return side >= 0 if alarm_side >= 0 else side <= 0

    # 功能：绘制或渲染 `_draw_line` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    #   - `line_points`（list[list[float]]）：`line_points` 对应的业务输入值
    #   - `alarm_side`（int）：`alarm_side` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/blocks/consumer.py` 的 `BlocksConsumer::post_process` 调用本符号
    #   - 内部调用：`len`、`cv2.putText`、`np.array`、`tuple`、`np.round(a).astype(int).tolist`、`np.round(a).astype`、`np.round`、`np.round(b).astype(int).tolist`、`np.round(b).astype`、`cv2.line`
    #          等共 17 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _draw_line(frame: np.ndarray, line_points: list[list[float]], alarm_side: int):
        if len(line_points) != 2:
            cv2.putText(frame, "line not configured", (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
            return

        a = np.array(line_points[0], dtype=np.float32)
        b = np.array(line_points[1], dtype=np.float32)
        p1 = tuple(np.round(a).astype(int).tolist())
        p2 = tuple(np.round(b).astype(int).tolist())
        cv2.line(frame, p1, p2, (0, 0, 255), 3)

        direction = b - a
        normal = np.array([-direction[1], direction[0]], dtype=np.float32)
        if alarm_side < 0:
            normal = -normal
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-6:
            return
        normal = normal / norm
        mid = (a + b) / 2.0
        arrow_start = tuple(np.round(mid).astype(int).tolist())
        arrow_end = tuple(np.round(mid + normal * 72.0).astype(int).tolist())
        cv2.arrowedLine(frame, arrow_start, arrow_end, (0, 0, 255), 3, tipLength=0.35)
        cv2.putText(frame, "alarm side", arrow_end, cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
