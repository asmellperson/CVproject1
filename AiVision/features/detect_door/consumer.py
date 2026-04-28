"""
features/detect_door/consumer.py
门禁状态检测 — 帧差法 + 双阶段告警(持续 N 秒触发首次,后续按间隔重复)。
"""
from __future__ import annotations
import time

import cv2
import numpy as np

from features._base.consumer import BaseFunctionConsumer


class DoorConsumer(BaseFunctionConsumer):
    """门禁检测 — 与 blocks 几乎一样的帧差,但用双阶段告警"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pre_gray: dict[int, list] = {}
        # 双阶段告警状态: camera_id → (continuous_start_ts, alarmed_once)
        self._alarm_state: dict[int, dict] = {}

    def _process(self, roi_list, camera_id):
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        diff_thr = cfg.get("diff_threshold", 5)
        ratio_thr = cfg.get("threshold", 0.5)

        if camera_id not in self._pre_gray or len(self._pre_gray[camera_id]) != len(roi_list):
            self._pre_gray[camera_id] = [
                cv2.cvtColor(self.blur_roi[camera_id][i], cv2.COLOR_BGR2GRAY)
                for i in range(len(roi_list))
            ]
            return [(False, {"ratio": 0.0}) for _ in roi_list]

        results = []
        for i in range(len(roi_list)):
            blur = self.blur_roi[camera_id][i]
            gray = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(gray, self._pre_gray[camera_id][i])
            _, bin_diff = cv2.threshold(diff, diff_thr, 255, cv2.THRESH_BINARY)
            ratio = float(bin_diff.mean()) / 255.0
            results.append((ratio > ratio_thr, {"ratio": ratio}))
            self._pre_gray[camera_id][i] = gray
        return results

    def post_process(self, camera_id, result):
        frame = self.frame_cache.get(camera_id)
        if frame is None:
            return None
        roi_polygons = self._get_roi_polygons(camera_id)
        alpha = 0.3
        color = np.array([0, 255, 255], dtype=np.uint8)

        for i, (alarm, _msg) in enumerate(result):
            if not alarm or i >= len(roi_polygons):
                continue
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            poly = np.array(roi_polygons[i], dtype=np.int32)
            cv2.fillPoly(mask, [poly], 255)
            mask_3ch = cv2.merge([mask, mask, mask])
            overlay = (frame * (1 - alpha) + color * alpha).astype(np.uint8)
            np.copyto(frame, overlay, where=mask_3ch > 0)
        return frame

    def _should_alarm(self, camera_id, result, cfg):
        """双阶段:持续 first_alarm 秒才首次告警,后续 alarm_dispatcher 控冷却"""
        now = time.time()
        first_alarm_threshold = self._value_config(cfg).get("first_alarm", 3.0)

        # 当前是否检测到变化
        has_change = any(item[0] for item in (result or []) if isinstance(item, (list, tuple)))

        state = self._alarm_state.setdefault(camera_id, {"start": None, "alarmed": False})

        if not has_change:
            # 状态恢复 — 重置
            state["start"] = None
            state["alarmed"] = False
            return False

        # 记录持续起点
        if state["start"] is None:
            state["start"] = now

        if not state["alarmed"]:
            # 第一阶段 — 等待持续时间到达
            if now - state["start"] >= first_alarm_threshold:
                state["alarmed"] = True
                return True
            return False

        # 第二阶段 — 已告警过,后续频率由 alarm_dispatcher 的冷却控制
        return True
