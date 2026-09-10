"""
features/detect_door/consumer.py
门禁状态检测 — 帧差法 + 双阶段告警(持续 N 秒触发首次,后续按间隔重复)。
"""
from __future__ import annotations
import time

import cv2
import numpy as np

from AiVision.features._base.consumer import BaseFunctionConsumer

class DoorConsumer(BaseFunctionConsumer):
    """门禁检测 — 与 blocks 几乎一样的帧差,但用双阶段告警"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pre_gray: dict[int, np.ndarray] = {}
        self._bg_gray: dict[int, np.ndarray] = {}
        self._candidate_state: dict[int, dict] = {}
        # 双阶段告警状态: camera_id → (continuous_start_ts, alarmed_once)
        self._alarm_state: dict[int, dict] = {}

    def _process(self, roi, camera_id):
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        diff_thr = int(cfg.get("diff_threshold", 5))
        ratio_thr = float(cfg.get("threshold", 0.5))
        env_thr = self._optional_ratio_threshold(cfg.get("env_threshold", 1.0))
        env_diff_thr = int(cfg.get("diff_threshold_env", max(diff_thr * 2, 10)))
        stable_confirm_seconds = float(cfg.get("stable_confirm_seconds", 1.0))
        stable_confirm_hits = int(cfg.get("stable_confirm_hits", 3))
        bg_alpha = float(cfg.get("background_update_alpha", 0.05))
        global_motion_thr = float(cfg.get("global_motion_threshold", 0.22))
        min_local_ratio = float(cfg.get("min_local_change_ratio", 0.01))

        gray = cv2.cvtColor(self.blur_roi[camera_id], cv2.COLOR_BGR2GRAY)
        if camera_id not in self._bg_gray or camera_id not in self._pre_gray:
            self._pre_gray[camera_id] = gray.copy()
            self._bg_gray[camera_id] = gray.copy()
            self._candidate_state.pop(camera_id, None)
            return False, {"ratio": 0.0}

        now = time.time()
        prev_diff = cv2.absdiff(gray, self._pre_gray[camera_id])
        bg_diff = cv2.absdiff(gray, self._bg_gray[camera_id])
        _, bin_prev = cv2.threshold(prev_diff, env_diff_thr, 255, cv2.THRESH_BINARY)
        _, bin_bg = cv2.threshold(bg_diff, diff_thr, 255, cv2.THRESH_BINARY)
        frame_motion_ratio = float(bin_prev.mean()) / 255.0
        ratio = float(bin_bg.mean()) / 255.0
        unstable_background = frame_motion_ratio > global_motion_thr or ratio > env_thr

        if unstable_background:
            self._reset_candidate(camera_id)
            result = (False, {
                "ratio": ratio,
                "frame_motion_ratio": frame_motion_ratio,
                "stable": False,
                "reason": "background_unstable",
            })
            self._pre_gray[camera_id] = gray
            return result

        raw_change = ratio >= ratio_thr and ratio >= min_local_ratio
        confirmed = self._update_candidate(camera_id, raw_change, now, stable_confirm_seconds, stable_confirm_hits)
        result = (confirmed, {
            "ratio": ratio,
            "frame_motion_ratio": frame_motion_ratio,
            "hits": self._candidate_state.get(camera_id, {}).get("hits", 0),
            "stable": True,
        })
        if not raw_change:
            self._bg_gray[camera_id] = cv2.addWeighted(
                gray,
                bg_alpha,
                self._bg_gray[camera_id],
                1.0 - bg_alpha,
                0,
            )
        self._pre_gray[camera_id] = gray
        return result

    def post_process(self, camera_id, result):
        frame = self._annotated_frame(camera_id)
        if frame is None:
            return None
        alarm, _detail = result
        if alarm:
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            cv2.fillPoly(mask, [self._roi_polygon_cache[camera_id]], 255)
            color = np.array([0, 255, 255], dtype=np.uint8)
            overlay = (frame * 0.7 + color * 0.3).astype(np.uint8)
            np.copyto(frame, overlay, where=mask[:, :, None] > 0)
        return frame

    def _on_roi_changed(self, camera_id: int) -> None:
        super()._on_roi_changed(camera_id)
        for cache in (self._pre_gray, self._bg_gray, self._candidate_state, self._alarm_state):
            cache.pop(camera_id, None)

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        super()._clear_camera_state(camera_id, shm_name)
        for cache in (self._pre_gray, self._bg_gray, self._candidate_state, self._alarm_state):
            cache.pop(camera_id, None)

    def _update_candidate(self, camera_id: int, raw_change: bool, now: float, seconds: float, hits: int) -> bool:
        state = self._candidate_state.setdefault(
            camera_id,
            {"start": None, "hits": 0},
        )
        if not raw_change:
            state["start"] = None
            state["hits"] = 0
            return False
        if state["start"] is None:
            state["start"] = now
            state["hits"] = 0
        state["hits"] = int(state.get("hits", 0)) + 1
        return state["hits"] >= hits and now - float(state["start"]) >= seconds

    def _reset_candidate(self, camera_id: int):
        state = self._candidate_state.setdefault(
            camera_id,
            {"start": None, "hits": 0},
        )
        state["start"] = None
        state["hits"] = 0

    @staticmethod
    def _optional_ratio_threshold(value) -> float:
        value = float(value)
        return 1.0 if value > 1 else value

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True

    def _should_alarm(self, camera_id, result, cfg):
        """双阶段:持续 first_alarm 秒才首次告警,后续 alarm_dispatcher 控冷却"""
        now = time.time()
        first_alarm_threshold = self._value_config(cfg).get("first_alarm", 3.0)

        # 当前是否检测到变化
        has_change = bool(result[0])

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
