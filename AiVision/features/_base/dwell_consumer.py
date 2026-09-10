"""
features/_base/dwell_consumer.py

detect_face 和 detect_human 的告警逻辑实质上一样:
    - 用一个 YOLO 模型检测目标
    - 跟踪每个目标的逗留时间
    - 超过 MAX_TIME 触发一次性告警

它们的唯一区别是:
    - 用的模型不同(face 用人脸模型, human 用人体模型)
    - 检测结果过滤可能不同(face 可能要求 type=='face')

所以本模板把这个共性抽出来,detect_face/detect_human 极简继承即可。
"""
from __future__ import annotations
import time
import cv2

from AiVision.features._base.consumer import BaseFunctionConsumer
from AiVision.features._base.tracking import IouTracker

def _number_or_default(value, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def build_dwell_monitor_snapshot(
    trackers: dict,                    # camera_id：每台 Camera 有一个独立 Tracker。
    *,
    camera_id: int,
    threshold_seconds: float,
    now: float | None = None,
    updated_at: float | None = None,
) -> dict:
    """Build a display-only snapshot from the existing dwell trackers."""
    current_time = time.time() if now is None else float(now)
    tracker = trackers.get(camera_id)
    visible_tracks = [
        track for track in tracker.tracks.values() if int(getattr(track, "lost", 0)) == 0
    ] if tracker is not None else []

    durations = [
        max(0.0, current_time - float(getattr(track, "first_seen", current_time)))
        for track in visible_tracks
    ]
    alarm = any(bool(getattr(track, "alarmed", False)) for track in visible_tracks)
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
        self.monitor_status: dict[str, dict] = {}

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        super()._clear_camera_state(camera_id, shm_name)
        self._trackers.pop(camera_id, None)
        if shm_name:
            self.monitor_status.pop(shm_name, None)

    def _on_roi_changed(self, camera_id: int) -> None:
        super()._on_roi_changed(camera_id)
        self._trackers.pop(camera_id, None)

    def _process(self, roi, camera_id):
        """
        拿当前摄像头唯一 ROI 完成人员/人脸检测、跟踪和逗留时间判断，返回本帧是否违规
        """
        # 读取算法参数
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        max_time = _number_or_default(cfg.get("MAX_TIME"), 10.0)
        iou_thr = _number_or_default(cfg.get("IOU_THR"), 0.3)
        max_lost = int(_number_or_default(cfg.get("MAX_LOST"), 5))
        center_dist_thr = _number_or_default(cfg.get("CENTER_DIST_THR"), 0.65)
        area_ratio_thr = _number_or_default(cfg.get("AREA_RATIO_THR"), 0.55)
        match_score_thr = _number_or_default(cfg.get("MATCH_SCORE_THR"), 0.35)
        smooth_alpha = _number_or_default(cfg.get("TRACK_SMOOTH_ALPHA"), 0.7)
        conf_thr = _number_or_default(cfg.get("CONF_THRESHOLD", cfg.get("FACE_SCORE_THR")), 0.3)
        min_box_area = _number_or_default(cfg.get("MIN_BOX_AREA"), 0)
        aspect_range = cfg.get("ASPECT_RATIO_RANGE") or []
        min_aspect, max_aspect = None, None
        if isinstance(aspect_range, (list, tuple)) and len(aspect_range) >= 2:
            min_aspect = _number_or_default(aspect_range[0], 0)
            max_aspect = _number_or_default(aspect_range[1], 10)

        # 调YOLO推理 — 用 spec.required_models[0] 作为目标模型
        if not self.spec.required_models:
            return False, None
        model_name = self.spec.required_models[0]
        det_result = self.dispatch_inference_sync(
            camera_id,
            model_name,
            roi,
            task_meta={"conf": conf_thr, "iou": iou_thr},
        )

        # 每台摄像头对应一个 Tracker
        tracker_key = camera_id
        if tracker_key not in self._trackers:
            self._trackers[tracker_key] = IouTracker(
                iou_thr=iou_thr,
                max_lost=max_lost,
                center_dist_thr=center_dist_thr,
                area_ratio_thr=area_ratio_thr,
                match_score_thr=match_score_thr,
                smooth_alpha=smooth_alpha,
            )
        # 创建后每帧重新获取参数
        tracker = self._trackers[tracker_key]
        tracker.iou_thr = iou_thr
        tracker.max_lost = max_lost
        tracker.center_dist_thr = center_dist_thr
        tracker.area_ratio_thr = area_ratio_thr
        tracker.match_score_thr = match_score_thr
        tracker.smooth_alpha = smooth_alpha

        # 提取检测框
        detections = []
        for det in det_result.get("detections", []):
            # 1、检测类别过滤
            if self.REQUIRED_DETECTION_TYPE and det.get("type") != self.REQUIRED_DETECTION_TYPE:
                continue
            bbox = det.get("bbox")
            if bbox and len(bbox) >= 4:
                width = max(0.0, float(bbox[2]) - float(bbox[0]))
                height = max(0.0, float(bbox[3]) - float(bbox[1]))
                area = width * height
                # 2、最小框面积过滤，去掉特别小的远距离目标或者噪声框
                if area < min_box_area:
                    continue
                if height > 0 and min_aspect is not None and max_aspect is not None:
                    # 3、高宽比过滤，异常扁平或者扁长框进行过滤
                    aspect = width / height
                    if aspect < min_aspect or aspect > max_aspect:
                        continue
                detections.append({"bbox": bbox})
        # 进入跟踪
        tracks = tracker.update(detections)

        # 判定告警
        has_alarm = False
        alarm_msgs = []
        now = time.time()
        for tid, trk in tracks.items():
            if trk.lost > 0:              # 本帧没有真正检测到的人，不参与当前逗留告警判断
                continue
            dwell_time = now - trk.first_seen
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
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        camera_key = str(self.config_cache.get(camera_id, {}).get("shm_name") or "").strip()
        if camera_key:
            # build_dwell_monitor_snapshot只统计当前真正可见Track，track.lost == 0才算
            self.monitor_status[camera_key] = build_dwell_monitor_snapshot(
                self._trackers,
                camera_id=camera_id,
                threshold_seconds=_number_or_default(cfg.get("MAX_TIME"), 10.0),
            )
        frame_copy = self._annotated_frame(camera_id)
        if frame_copy is None:
            return None
        tracker = self._trackers.get(camera_id)
        if tracker is None:
            return frame_copy
        ox, oy = self._get_roi_offset(camera_id)
        for tid, trk in tracker.tracks.items():
            dwell_time = time.time() - trk.first_seen if trk.lost == 0 else trk.dwell_time
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
        value = self.monitor_status.get(camera_key)
        return dict(value) if value else None

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True
