"""
features/blocks/consumer.py
区域入侵检测消费者 — 在 ROI 区域内检测到人体即告警。
"""
from __future__ import annotations
import cv2
from features._base.consumer import BaseFunctionConsumer


class BlocksConsumer(BaseFunctionConsumer):
    """区域入侵检测 — YOLO 人体检测 + ROI 告警"""

    def _process(self, roi_list, camera_id):
        """对每个 ROI 做人体检测,检测到人即告警。"""
        config = self._value_config(self.config_cache.get(camera_id, {}))
        conf = float(config.get("threshold", 0.3) or 0.3)
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
            roi_detections = detections_by_roi.get(roi_id, [])
            results.append((len(roi_detections) > 0, {"detections": roi_detections}))
        return results

    def post_process(self, camera_id, result):
        """绘制人体框,不再对 ROI 区域做底色高亮。"""
        frame = self.frame_cache.get(camera_id)
        if frame is None:
            return None
        frame_copy = frame.copy()
        roi_polygons = self._get_roi_polygons(camera_id)

        for i, (alarm, _msg) in enumerate(result):
            if not alarm or i >= len(roi_polygons):
                continue
            poly = roi_polygons[i]
            x_offset = int(min(point[0] for point in poly))
            y_offset = int(min(point[1] for point in poly))
            for det in (_msg or {}).get("detections", []):
                x1, y1, x2, y2 = [int(v) for v in det.get("bbox", [0, 0, 0, 0])]
                x1 += x_offset
                x2 += x_offset
                y1 += y_offset
                y2 += y_offset
                cv2.rectangle(frame_copy, (x1, y1), (x2, y2), (0, 0, 255), 2)
                conf = float(det.get("confidence", 0.0))
                cv2.putText(
                    frame_copy,
                    f"person {conf:.2f}",
                    (x1, max(0, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 255),
                    2,
                )
        return frame_copy

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        """人体检测需要周期处理静止画面,避免有人站着不动时漏检。"""
        return True
