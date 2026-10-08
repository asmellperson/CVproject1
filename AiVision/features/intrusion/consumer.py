"""区域入侵检测：以人体框靠近脚底的代表点判断人员是否处于警戒线指定侧。

检测结果表示入侵侧存在人员，不要求观测到完整跨线过程。ROI 内的检测坐标
需还原到原帧坐标后，才能与归一化警戒线转换出的像素坐标比较。
"""
from __future__ import annotations
import cv2
import numpy as np
from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.features._shared.roi import LINE_ADAPTER


class BlocksConsumer(BaseFunctionConsumer):
    """区域入侵检测 — YOLO 人体检测 + 警戒线入侵侧存在告警"""
    def _process(self, roi, camera_id):
        """在唯一 ROI 内检测，恢复原始帧坐标后判断脚底点是否位于入侵侧。"""
        config = self.config_cache[camera_id]
        conf = config["threshold"]
        frame = self.frame_cache.get(camera_id)
        # 读取警戒线和报警方向
        line_points, alarm_side = self._line_config(config, frame)
        # 默认0.93，作用是确定人体bbox里脚底参考点（x是框的中间，y是框的两个y值相加*0.93）
        foot_ratio = config["foot_ratio"]
        # YOLO
        outcome = self.dispatch_inference_sync(
            camera_id,
            "yolo_human",
            roi,
            task_meta={"conf": conf},
            timeout=1.0,             # Base是0.8秒，这里是1秒
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
            # 算脚底点
            foot_point = self._foot_point(bbox, foot_ratio)
            # 使用二维向量的叉积，判断一个点位于有方向的直线都哪一侧（side>0,一侧，side<0另一侧，side=0在线上）
            side = self._point_side(line_points, foot_point) if line_points and foot_point is not None else 0.0
            intrusion = self._is_alarm_side(side, alarm_side) if line_points and foot_point is not None else False
            enriched.update(foot_point=foot_point, line_side=side, intrusion=intrusion)
            roi_detections.append(enriched)
            if intrusion:
                intrusions.append(enriched)
        # roi_detections：所有检测到的人，intrusions：真正处在危险区的人
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
        # 画警戒线和箭头
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

    @classmethod
    def _line_config(cls, config: dict, frame: np.ndarray | None) -> tuple[list[list[float]], int]:
        """校验归一化警戒线，按当前帧尺寸转换坐标并保留配置的入侵方向。"""
        raw_points = config["line_points"]
        points = LINE_ADAPTER.validate_python(raw_points)
        if frame is not None:
            h, w = frame.shape[:2]
            points = [[x * w, y * h] for x, y in points]
        alarm_side = config["alarm_side"]
        return points, alarm_side

    @staticmethod
    def _foot_point(bbox, foot_ratio: float) -> list[float] | None:
        """按高度比例选取人体代表点；检测框缺失或坐标不可转换时返回 None。"""
        if not isinstance(bbox, list) or len(bbox) < 4:
            return None
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
        except (TypeError, ValueError):
            return None
        return [(x1 + x2) / 2.0, y1 + (y2 - y1) * foot_ratio]

    @staticmethod
    def _point_side(line_points: list[list[float]], point: list[float]) -> float:
        """叉积，判断脚底点在线的哪一侧"""
        (x1, y1), (x2, y2) = line_points
        px, py = point
        return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)

    @staticmethod
    def _is_alarm_side(side: float, alarm_side: int) -> bool:
        """alarm_side是真正的危险区，所以这里的逻辑是:
            alarm_side 表示哪一侧是危险区；side 表示当前人体脚底点位于警戒线的哪一侧。两者方向一致时，就判定为入侵。
        """
        return side >= 0 if alarm_side >= 0 else side <= 0

    @staticmethod
    def _draw_line(frame: np.ndarray, line_points: list[list[float]], alarm_side: int):
        """画警戒线和箭头"""
        if len(line_points) != 2:
            cv2.putText(frame, "line not configured", (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
            return

        a = np.array(line_points[0], dtype=np.float32)
        b = np.array(line_points[1], dtype=np.float32)
        p1 = tuple(np.round(a).astype(int).tolist())
        p2 = tuple(np.round(b).astype(int).tolist())
        cv2.line(frame, p1, p2, (0, 0, 255), 3)

        direction = b - a
        # normal是垂直于警戒线的方向
        normal = np.array([-direction[1], direction[0]], dtype=np.float32)
        # alarm_side < 0
        if alarm_side < 0:
            # 就把方向翻转
            normal = -normal
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-6:
            return
        normal = normal / norm
        mid = (a + b) / 2.0
        arrow_start = tuple(np.round(mid).astype(int).tolist())
        arrow_end = tuple(np.round(mid + normal * 72.0).astype(int).tolist())
        # 箭头指向当前配置的报警侧
        cv2.arrowedLine(frame, arrow_start, arrow_end, (0, 0, 255), 3, tipLength=0.35)
        cv2.putText(frame, "alarm side", arrow_end, cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
