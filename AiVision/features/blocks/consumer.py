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
from AiVision.features._base.roi import LINE_ADAPTER


class BlocksConsumer(BaseFunctionConsumer):
    """区域入侵检测 — YOLO 人体检测 + 警戒线入侵侧存在告警"""
    def _process(self, roi, camera_id):
        """在唯一 ROI 内检测，恢复原始帧坐标后判断脚底点是否位于入侵侧。"""
        config = self._value_config(self.config_cache.get(camera_id, {}))
        conf = float(config.get("threshold", 0.3) or 0.3)
        frame = self.frame_cache.get(camera_id)
        line_points, alarm_side = self._line_config(config, frame)
        foot_ratio = self._foot_ratio(config)

        outcome = self.dispatch_inference_sync(
            camera_id,
            "yolo_human",
            roi,
            task_meta={"conf": conf},
            timeout=1.0,
        )
        roi_detections = []
        intrusions = []
        ox, oy = self._get_roi_offset(camera_id)
        for det in outcome.get("detections", []):
            enriched = dict(det)
            bbox = enriched.get("bbox") or []
            if len(bbox) == 4:
                bbox = [bbox[0] + ox, bbox[1] + oy, bbox[2] + ox, bbox[3] + oy]
                enriched["bbox"] = bbox
            foot_point = self._foot_point(bbox, foot_ratio)
            side = self._point_side(line_points, foot_point) if line_points and foot_point is not None else 0.0
            intrusion = self._is_alarm_side(side, alarm_side) if line_points and foot_point is not None else False
            enriched.update(foot_point=foot_point, line_side=side, intrusion=intrusion)
            roi_detections.append(enriched)
            if intrusion:
                intrusions.append(enriched)
        return bool(intrusions), {
            "detections": roi_detections, "intrusions": intrusions,
            "line_points": line_points, "alarm_side": alarm_side, "foot_ratio": foot_ratio,
        }

    def post_process(self, camera_id, result):
        """绘制警戒线、入侵侧方向、人体框和脚底点。"""
        frame_copy = self._annotated_frame(camera_id)
        if frame_copy is None:
            return None
        _alarm, _msg = result
        self._draw_line(frame_copy, _msg["line_points"], _msg["alarm_side"])
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

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        """人体检测需要周期处理静止画面,避免有人站着不动时漏检。"""
        return True

    @staticmethod
    def _foot_ratio(config: dict) -> float:
        try:
            return max(0.0, min(1.0, float(config.get("foot_ratio", 0.93))))
        except (TypeError, ValueError):
            return 0.93

    @classmethod
    def _line_config(cls, config: dict, frame: np.ndarray | None) -> tuple[list[list[float]], int]:
        raw_points = config.get("line_points", [])
        points = LINE_ADAPTER.validate_python(raw_points)
        if frame is not None:
            h, w = frame.shape[:2]
            points = [[x * w, y * h] for x, y in points]
        try:
            alarm_side = -1 if int(config.get("alarm_side", 1) or 1) < 0 else 1
        except (TypeError, ValueError):
            alarm_side = 1
        return points, alarm_side

    @staticmethod
    def _foot_point(bbox, foot_ratio: float) -> list[float] | None:
        if not isinstance(bbox, list) or len(bbox) < 4:
            return None
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
        except (TypeError, ValueError):
            return None
        return [(x1 + x2) / 2.0, y1 + (y2 - y1) * foot_ratio]

    @staticmethod
    def _point_side(line_points: list[list[float]], point: list[float]) -> float:
        (x1, y1), (x2, y2) = line_points
        px, py = point
        return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)

    @staticmethod
    def _is_alarm_side(side: float, alarm_side: int) -> bool:
        return side >= 0 if alarm_side >= 0 else side <= 0

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
