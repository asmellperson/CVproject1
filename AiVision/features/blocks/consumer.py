"""
features/blocks/consumer.py
区域入侵检测消费者 — 帧差法检测 ROI 区域内的画面变化。

业务逻辑与旧 blocks_function.py 保持一致,只是父类改为新的 BaseFunctionConsumer,
不再调用任何 ModelWorker(无需推理)。
"""
from __future__ import annotations
import time
import cv2
import numpy as np
from features._base.consumer import BaseFunctionConsumer


class BlocksConsumer(BaseFunctionConsumer):
    """区域入侵检测 — 帧差法 + 阈值告警"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pre_gray: dict[int, list[np.ndarray]] = {}

    def _process(self, roi_list, camera_id):
        """对每个 ROI 做灰度差分,变化比例超阈值则告警"""
        results = []
        config = self._value_config(self.config_cache.get(camera_id, {}))
        diff_thr = config.get("diff_threshold", 10)
        ratio_thr = config.get("threshold", 0.05)

        # 首帧:仅缓存灰度,不产出告警
        if camera_id not in self._pre_gray or len(self._pre_gray[camera_id]) != len(roi_list):
            self._pre_gray[camera_id] = [
                cv2.cvtColor(self.blur_roi[camera_id][i], cv2.COLOR_BGR2GRAY)
                for i in range(len(roi_list))
            ]
            return [(False, {"ratio": 0.0}) for _ in roi_list]

        for i in range(len(roi_list)):
            blur = self.blur_roi[camera_id][i]
            gray = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(gray, self._pre_gray[camera_id][i])
            _, diff_bin = cv2.threshold(diff, diff_thr, 255, cv2.THRESH_BINARY)
            ratio = float(diff_bin.mean()) / 255.0
            results.append((ratio > ratio_thr, {"ratio": ratio}))
            self._pre_gray[camera_id][i] = gray

        return results

    def post_process(self, camera_id, result):
        """触发告警的 ROI 用半透明黄色高亮"""
        frame = self.frame_cache.get(camera_id)
        if frame is None:
            return None
        roi_polygons = self._get_roi_polygons(camera_id)
        alpha = 0.3
        overlay_color = np.array([0, 255, 255], dtype=np.uint8)

        for i, (alarm, _msg) in enumerate(result):
            if not alarm or i >= len(roi_polygons):
                continue
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            poly = np.array(roi_polygons[i], dtype=np.int32)
            cv2.fillPoly(mask, [poly], 255)
            mask_3ch = cv2.merge([mask, mask, mask])
            overlay = (frame * (1 - alpha) + overlay_color * alpha).astype(np.uint8)
            np.copyto(frame, overlay, where=mask_3ch > 0)
        return frame
