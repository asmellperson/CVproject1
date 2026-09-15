"""
features/_base/dwell_consumer.py

detect_face 和 detect_human 的告警逻辑实质上一样:
    - 通过功能声明的模型检测目标，接收统一检测结果
    - 跟踪每个目标的逗留时间
    - 达到 MAX_TIME 后轨迹保持告警状态，直至轨迹删除
    - 仅本次匹配到目标（lost == 0）的轨迹参与当前告警；重复通知由 alarm_interval 冷却控制
    - 推理故障保留轨迹并暂停计时；恢复后重新匹配，不补计故障跨越的间隔
    - 故障持续期间不按时长删除轨迹；恢复后的有效观测未匹配才累计 MAX_LOST

它们的唯一区别是:
    - 用的模型不同(face 用人脸模型, human 用人体模型)
    - 检测结果过滤可能不同(face 可能要求 type=='face')

所以本模板把这个共性抽出来,detect_face/detect_human 极简继承即可。
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from time import monotonic
import time
import cv2

from AiVision.core.logger import logger
from AiVision.features._base.consumer import BaseFunctionConsumer
from AiVision.features._base.tracking import IouTracker
from AiVision.inference.contracts import INFERENCE_STATUS_OK


@dataclass
class DwellObservationClock:
    """只累计相邻两次有效推理之间的单调时间，故障及恢复首帧均不推进。"""
    elapsed: float = 0.0
    last_success_at: float = 0.0
    valid: bool = False

    def observe(self, now: float) -> None:
        if self.valid:
            self.elapsed += max(0.0, now - self.last_success_at)
        self.last_success_at = now
        self.valid = True


def validated_dwell_detections(result: dict) -> list[dict]:
    """整帧校验后再交给跟踪器；损坏的框不能被静默当成未检测到目标。"""
    detections = result.get("detections")
    if not isinstance(detections, list):
        raise ValueError("detections 必须是列表")
    for detection in detections:
        if not isinstance(detection, dict):
            raise ValueError("检测项必须是对象")
        bbox = detection.get("bbox")
        confidence = detection.get("confidence")
        class_id = detection.get("class_id")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("bbox 必须是四坐标列表")
        if (
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in (*bbox, confidence))
            or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]
            or not 0 <= confidence <= 1
            or not isinstance(class_id, int) or isinstance(class_id, bool) or class_id < 0
            or not isinstance(detection.get("type"), str) or not detection["type"]
        ):
            raise ValueError("检测项的 bbox、confidence、class_id 或 type 无效")
    return detections

def build_dwell_monitor_snapshot(
    trackers: dict,                    # camera_id：每台 Camera 有一个独立 Tracker。
    *,
    camera_id: int,
    threshold_seconds: float,
    updated_at: float | None = None,
) -> dict:
    """展示最后一次有效观测中的可见轨迹，时长与告警使用同一时间轴。"""
    tracker = trackers.get(camera_id)
    visible_tracks = [
        track for track in tracker.tracks.values() if track.lost == 0
    ] if tracker is not None else []

    durations = [track.dwell_time for track in visible_tracks]
    alarm = any(track.alarmed for track in visible_tracks)
    return {
        "count": len(visible_tracks),
        "alarm": alarm,
        "reason": "loitering" if alarm else "normal",
        "duration_seconds": round(max(durations, default=0.0), 2),      # 当前状态页展示当前最大逗留时间
        "threshold_seconds": float(threshold_seconds),
        "updated_at_s": time.time() if updated_at is None else float(updated_at),
    }

class DwellDetectionConsumer(BaseFunctionConsumer):
    """逗留检测通用模板 — 适合 face 和 human"""
    # 子类通过 class 变量配置:
    REQUIRED_DETECTION_TYPE: str | None = None  # None = 不过滤,如 "face" / "person"
    BBOX_COLOR_NORMAL = (0, 255, 0)              # 正常跟踪 — 绿框
    BBOX_COLOR_ALARM = (0, 0, 255)               # 告警 — 红框

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # camera_id → IouTracker
        self._trackers: dict[int, IouTracker] = {}
        self._observation_clocks: dict[int, DwellObservationClock] = {}
        self.monitor_status: dict[str, dict] = {}

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        super()._clear_camera_state(camera_id, shm_name)
        self._trackers.pop(camera_id, None)
        self._observation_clocks.pop(camera_id, None)
        if shm_name:
            self.monitor_status.pop(shm_name, None)

    def _on_roi_changed(self, camera_id: int) -> None:
        super()._on_roi_changed(camera_id)
        self._trackers.pop(camera_id, None)
        self._observation_clocks.pop(camera_id, None)
        camera_key = self.config_cache[camera_id].get("shm_name")
        self.monitor_status.pop(camera_key, None)

    def _detection_options(self, cfg: dict) -> tuple:
        raise NotImplementedError

    def _process(self, roi, camera_id):
        """
        拿当前摄像头唯一 ROI 完成人员/人脸检测、跟踪和逗留时间判断，返回本帧是否违规
        """
        # 读取算法参数
        cfg = self.config_cache[camera_id]
        clock = self._observation_clocks.setdefault(camera_id, DwellObservationClock())
        max_time = cfg["MAX_TIME"]
        detection_iou = cfg["DETECTION_IOU_THR"]
        track_iou = cfg["TRACK_IOU_THR"]
        max_lost = cfg["MAX_LOST"]
        conf_thr, min_box_area, aspect_range, tracking_options = self._detection_options(cfg)
        min_aspect, max_aspect = aspect_range

        # 统一推理接口；具体模型由功能声明，检测 NMS 与跟踪匹配分别配置。
        model_name = self.spec.required_models[0]
        try:
            det_result = self.dispatch_inference_sync(
                camera_id, model_name, roi,
                task_meta={"conf": conf_thr, "iou": detection_iou},
            )
        except Exception:
            clock.valid = False
            logger.exception(f"[{self.feature_name}] 推理调用失败，逗留计时暂停 camera_id={camera_id}")
            return False, None
        if not isinstance(det_result, dict) or det_result.get("status") != INFERENCE_STATUS_OK:
            clock.valid = False
            return False, None
        try:
            raw_detections = validated_dwell_detections(det_result)
        except ValueError as exc:
            clock.valid = False
            logger.warning(f"[{self.feature_name}] 推理结果无效，逗留计时暂停 camera_id={camera_id}: {exc}")
            return False, None

        clock.observe(monotonic())

        # 每台摄像头对应一个 Tracker
        tracker_key = camera_id
        if tracker_key not in self._trackers:
            self._trackers[tracker_key] = IouTracker(
                iou_thr=track_iou,
                max_lost=max_lost,
                **tracking_options,
            )
        # 热更新保持检测与跟踪参数独立。
        tracker = self._trackers[tracker_key]
        tracker.iou_thr = track_iou
        tracker.max_lost = max_lost
        for key, value in tracking_options.items():
            setattr(tracker, key, value)

        # 提取检测框
        detections = []
        for det in raw_detections:
            # 1、检测类别过滤
            if self.REQUIRED_DETECTION_TYPE and det.get("type") != self.REQUIRED_DETECTION_TYPE:
                continue
            bbox = det["bbox"]
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            # 最小框面积与宽高比是业务过滤，正常过滤为空仍然属于有效观测。
            if width * height < min_box_area:
                continue
            if min_aspect is not None and max_aspect is not None and not min_aspect <= width / height <= max_aspect:
                continue
            detections.append({"bbox": bbox})
        # 进入跟踪
        tracks = tracker.update(detections, now=clock.elapsed)

        # 判定告警
        has_alarm = False
        alarm_msgs = []
        for tid, trk in tracks.items():
            if trk.lost > 0:              # 本帧没有真正检测到的人，不参与当前逗留告警判断
                continue
            dwell_time = trk.dwell_time
            if not trk.alarmed and dwell_time >= max_time:
                trk.alarmed = True
            # Track一旦报警就一直保持报警，直到这个Track被删除
            if trk.alarmed:
                has_alarm = True
                alarm_msgs.append({
                    "track_id": tid,
                    "dwell_time": round(dwell_time, 2),
                    "bbox": list(trk.bbox),
                })
        return has_alarm, alarm_msgs if alarm_msgs else None

    def post_process(self, camera_id, result):
        """
        负责：
            生成运行状态
            画ROI
            画Track框
        """
        cfg = self.config_cache[camera_id]
        clock = self._observation_clocks.get(camera_id)
        valid = clock is not None and clock.valid
        camera_key = str(self.config_cache.get(camera_id, {}).get("shm_name") or "").strip()
        if camera_key:
            # build_dwell_monitor_snapshot只统计当前真正可见Track，track.lost == 0才算
            self.monitor_status[camera_key] = build_dwell_monitor_snapshot(
                self._trackers,
                camera_id=camera_id,
                threshold_seconds=cfg["MAX_TIME"],
            ) if valid else {
                "count": None, "alarm": False, "reason": "unknown",
                "duration_seconds": None, "threshold_seconds": cfg["MAX_TIME"],
                "updated_at_s": time.time(),
            }
        frame_copy = self._annotated_frame(camera_id)
        if frame_copy is None:
            return None
        if not valid:
            cv2.putText(frame_copy, "UNKNOWN - inference failed; dwell paused", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 255), 2)
            return frame_copy
        tracker = self._trackers.get(camera_id)
        if tracker is None:
            return frame_copy
        ox, oy = self._get_roi_offset(camera_id)
        for tid, trk in tracker.tracks.items():
            dwell_time = trk.dwell_time
            x1, y1, x2, y2 = (
                int(trk.bbox[0]) + ox, int(trk.bbox[1]) + oy,
                int(trk.bbox[2]) + ox, int(trk.bbox[3]) + oy,
            )
            if trk.alarmed:
                cv2.rectangle(frame_copy, (x1, y1), (x2, y2), self.BBOX_COLOR_ALARM, 2)
                # 文字：这个人当前Track ID + 已经逗留了多久
                cv2.putText(
                    frame_copy,
                    f"ALARM ID:{tid} {dwell_time:.1f}s",
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, self.BBOX_COLOR_ALARM, 2,
                )
            else:
                cv2.rectangle(frame_copy, (x1, y1), (x2, y2), self.BBOX_COLOR_NORMAL, 2)
                cv2.putText(
                    frame_copy,
                    f"ID:{tid} {dwell_time:.1f}s",
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.BBOX_COLOR_NORMAL, 1,
                )
        return frame_copy

    def get_monitor_status(self, camera_key: str) -> dict | None:
        with self._camera_state_lock:
            value = self.monitor_status.get(camera_key)
            return dict(value) if value else None

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True
