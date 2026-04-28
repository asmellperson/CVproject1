"""
features/detect_phone/consumer.py
手机检测消费者 — 检测到手机即告警(无逗留概念)。
"""
from __future__ import annotations
import cv2
import numpy as np

from features._base.consumer import BaseFunctionConsumer


class PhoneConsumer(BaseFunctionConsumer):
    """手机检测 — 检到任意手机就触发告警(冷却由 dispatcher 控制)"""

    def _process(self, roi_list, camera_id):
        if not self.spec.required_models:
            return [(False, None) for _ in roi_list]
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        conf_thr = float(cfg.get("CONF_THRESHOLD", 0.7))
        iou_thr = float(cfg.get("IOU_THR", 0.5))
        model_name = self.spec.required_models[0]
        det_results = self.dispatch_inference_sync(
            camera_id,
            model_name,
            roi_list,
            task_meta={"conf": conf_thr, "iou": iou_thr},
        )

        results = []
        for det_result in det_results:
            detections = det_result.get("detections", []) or []
            results.append((bool(detections), detections))
        # 推理可能漏返回部分 ROI,补足
        while len(results) < len(roi_list):
            results.append((False, None))
        return results

    def post_process(self, camera_id, result):
        frame = self.frame_cache.get(camera_id)
        if frame is None:
            return None
        frame_copy = frame.copy()
        roi_polygons = self._get_roi_polygons(camera_id)
        roi_offsets = self._get_roi_offsets(camera_id)

        for roi_index, (alarm, detections) in enumerate(result):
            if not alarm or not detections:
                continue
            ox, oy = roi_offsets[roi_index] if roi_index < len(roi_offsets) else (0, 0)
            for det in detections:
                bbox = det.get("bbox", [])
                if len(bbox) < 4:
                    continue
                x1, y1, x2, y2 = (
                    int(bbox[0]) + ox, int(bbox[1]) + oy,
                    int(bbox[2]) + ox, int(bbox[3]) + oy,
                )
                conf = det.get("confidence", 0)
                cv2.rectangle(frame_copy, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    frame_copy, f"phone {conf:.2f}", (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
                )
        return frame_copy

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True

    def _get_roi_offsets(self, camera_id: int) -> list[tuple[int, int]]:
        offsets = []
        if camera_id in self._masks:
            for _mask, y_min, _y_max, x_min, _x_max in self._masks[camera_id]:
                offsets.append((x_min, y_min))
        return offsets
