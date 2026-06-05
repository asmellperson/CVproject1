"""
features/blocks/consumer.py
区域入侵检测消费者 — 人体脚底点位于警戒线入侵侧即告警。
"""
from __future__ import annotations
import cv2
import numpy as np
from features._base.consumer import BaseFunctionConsumer


class BlocksConsumer(BaseFunctionConsumer):
    """区域入侵检测 — YOLO 人体检测 + 警戒线入侵侧存在告警"""

    def _get_roi(self, camera_id: int, frame: np.ndarray) -> list[np.ndarray]:
        """blocks 使用全帧检测，警戒线负责过滤入侵侧，避免依赖复杂 ROI。"""
        h, w = frame.shape[:2]
        self._roi_polygon_cache[camera_id] = [[[0, 0], [w, 0], [w, h], [0, h]]]
        return [frame]

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
        raw_points = config.get("line_points") or []
        points = cls._normalize_line_points(raw_points, frame)
        try:
            alarm_side = -1 if int(config.get("alarm_side", 1) or 1) < 0 else 1
        except (TypeError, ValueError):
            alarm_side = 1
        return points, alarm_side

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
