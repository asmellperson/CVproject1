# 文件说明：实现视频帧消费与检测的帧消费、判定与告警衔接逻辑。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
features/_base/dwell_consumer.py
通用"YOLO 检测 + IoU 跟踪 + 逗留告警"消费者模板。

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
import numpy as np

from AiVision.features._base.consumer import BaseFunctionConsumer
from AiVision.features._base.tracking import IouTracker


# 功能：实现 `_number_or_default` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（未显式标注）：待转换、校验或写入的值
#   - `default`（float）：`default` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _number_or_default(value, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# 功能：Build a display-only snapshot from the existing dwell trackers；输入与输出详见下方说明
# 参数：
#   - `trackers`（dict）：`trackers` 对应的业务输入值
#   - `camera_id`（int）：摄像头唯一标识
#   - `active_roi_indices`（set[int] | None）：`active_roi_indices` 对应的业务输入值；默认值为 `None`
#   - `threshold_seconds`（float）：`threshold_seconds` 对应的时间间隔或时长
#   - `now`（float | None）：`now` 对应的业务输入值；默认值为 `None`
#   - `updated_at`（float | None）：`updated_at` 对应的业务输入值；默认值为 `None`
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/features/_base/dwell_consumer.py` 的 `DwellDetectionConsumer::post_process` 调用本符号
#   - 内部调用：`time.time`、`float`、`trackers.items`、`visible_tracks.extend`、`tracker.tracks.values`、`int`、`getattr`、`max`、`any`、`bool`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def build_dwell_monitor_snapshot(
    trackers: dict,
    *,
    camera_id: int,
    active_roi_indices: set[int] | None = None,
    threshold_seconds: float,
    now: float | None = None,
    updated_at: float | None = None,
) -> dict:
    """Build a display-only snapshot from the existing dwell trackers."""
    current_time = time.time() if now is None else float(now)
    visible_tracks = []
    for (tracker_camera_id, roi_index), tracker in trackers.items():
        if tracker_camera_id != camera_id:
            continue
        if active_roi_indices is not None and roi_index not in active_roi_indices:
            continue
        visible_tracks.extend(
            track
            for track in tracker.tracks.values()
            if int(getattr(track, "lost", 0)) == 0
        )

    durations = [
        max(0.0, current_time - float(getattr(track, "first_seen", current_time)))
        for track in visible_tracks
    ]
    alarm = any(bool(getattr(track, "alarmed", False)) for track in visible_tracks)
    return {
        "count": len(visible_tracks),
        "alarm": alarm,
        "reason": "loitering" if alarm else "normal",
        "duration_seconds": round(max(durations, default=0.0), 2),
        "threshold_seconds": float(threshold_seconds),
        "updated_at_s": time.time() if updated_at is None else float(updated_at),
    }


# 功能：逗留检测通用模板 — 适合 face 和 human；输入与输出详见下方说明
# 参数：
#   - `*args`（未显式标注）：`args` 对应的业务输入值
#   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
# 返回：DwellDetectionConsumer；返回新建的 `DwellDetectionConsumer` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DwellDetectionConsumer(BaseFunctionConsumer):
    """逗留检测通用模板 — 适合 face 和 human"""

    # 子类通过 class 变量配置:
    REQUIRED_DETECTION_TYPE: str | None = None  # None = 不过滤,如 "face" / "person"
    BBOX_COLOR_NORMAL = (0, 255, 0)              # 正常跟踪 — 绿框
    BBOX_COLOR_ALARM = (0, 0, 255)               # 告警 — 红框

    # 功能：初始化或配置 `__init__` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().__init__`、`super`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # (camera_id, roi_index) → IouTracker
        self._trackers: dict[tuple[int, int], IouTracker] = {}
        self.monitor_status: dict[str, dict] = {}

    # 功能：处理 `_process` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `roi_list`（未显式标注）：`roi_list` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._value_config`、`self.config_cache.get`、`_number_or_default`、`cfg.get`、`int`、`isinstance`、`len`、`self.dispatch_inference_sync`、`enumerate`、`IouTracker`
    #          等共 22 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process(self, roi_list, camera_id):
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

        # 调推理 — 用 spec.required_models[0] 作为目标模型
        if not self.spec.required_models:
            return [(False, None) for _ in roi_list]
        model_name = self.spec.required_models[0]
        det_results = self.dispatch_inference_sync(
            camera_id,
            model_name,
            roi_list,
            task_meta={"conf": conf_thr, "iou": iou_thr},
        )

        results = []
        for roi_index, det_result in enumerate(det_results):
            tracker_key = (camera_id, roi_index)
            if tracker_key not in self._trackers:
                self._trackers[tracker_key] = IouTracker(
                    iou_thr=iou_thr,
                    max_lost=max_lost,
                    center_dist_thr=center_dist_thr,
                    area_ratio_thr=area_ratio_thr,
                    match_score_thr=match_score_thr,
                    smooth_alpha=smooth_alpha,
                )
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
                if self.REQUIRED_DETECTION_TYPE and det.get("type") != self.REQUIRED_DETECTION_TYPE:
                    continue
                bbox = det.get("bbox")
                if bbox and len(bbox) >= 4:
                    width = max(0.0, float(bbox[2]) - float(bbox[0]))
                    height = max(0.0, float(bbox[3]) - float(bbox[1]))
                    area = width * height
                    if area < min_box_area:
                        continue
                    if height > 0 and min_aspect is not None and max_aspect is not None:
                        aspect = width / height
                        if aspect < min_aspect or aspect > max_aspect:
                            continue
                    detections.append({"bbox": bbox})

            tracks = tracker.update(detections)

            # 判定告警
            has_alarm = False
            alarm_msgs = []
            now = time.time()
            for tid, trk in tracks.items():
                if trk.lost > 0:
                    continue
                dwell_time = now - trk.first_seen
                if not trk.alarmed and dwell_time >= max_time:
                    trk.alarmed = True
                if trk.alarmed:
                    has_alarm = True
                    alarm_msgs.append({
                        "track_id": tid,
                        "dwell_time": round(dwell_time, 2),
                        "bbox": list(trk.bbox),
                    })
            results.append((has_alarm, alarm_msgs if alarm_msgs else None))

        while len(results) < len(roi_list):
            results.append((False, None))
        return results

    # 功能：处理 `post_process` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `result`（未显式标注）：`result` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._value_config`、`self.config_cache.get`、`str(self.config_cache.get(camera_id, {}).get('shm_name') or
    #          '').strip`、`str`、`self.config_cache.get(camera_id,
    #          {}).get`、`build_dwell_monitor_snapshot`、`set`、`range`、`len`、`_number_or_default` 等共 25 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def post_process(self, camera_id, result):
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        camera_key = str(self.config_cache.get(camera_id, {}).get("shm_name") or "").strip()
        if camera_key:
            self.monitor_status[camera_key] = build_dwell_monitor_snapshot(
                self._trackers,
                camera_id=camera_id,
                active_roi_indices=set(range(len(result))),
                threshold_seconds=_number_or_default(cfg.get("MAX_TIME"), 10.0),
            )
        frame = self.frame_cache.get(camera_id)
        if frame is None:
            return None
        frame_copy = frame.copy()
        roi_polygons = self._get_roi_polygons(camera_id)
        roi_offsets = self._get_roi_offsets(camera_id)

        for roi_index, (alarm, _msgs) in enumerate(result):
            # 触发告警的 ROI 画蓝框
            if alarm and roi_index < len(roi_polygons):
                poly = np.array(roi_polygons[roi_index], dtype=np.int32)
                cv2.polylines(frame_copy, [poly.reshape(-1, 1, 2)], True, (255, 0, 0), 2)

            # 画跟踪框
            tracker = self._trackers.get((camera_id, roi_index))
            if tracker is None:
                continue
            ox, oy = roi_offsets[roi_index] if roi_index < len(roi_offsets) else (0, 0)
            for tid, trk in tracker.tracks.items():
                dwell_time = time.time() - trk.first_seen if trk.lost == 0 else trk.dwell_time
                x1, y1, x2, y2 = (
                    int(trk.bbox[0]) + ox, int(trk.bbox[1]) + oy,
                    int(trk.bbox[2]) + ox, int(trk.bbox[3]) + oy,
                )
                if trk.alarmed:
                    cv2.rectangle(frame_copy, (x1, y1), (x2, y2), self.BBOX_COLOR_ALARM, 2)
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

    # 功能：读取或查询 `get_monitor_status` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_key`（str）：`camera_key` 对应的业务输入值
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.monitor_status.get`、`dict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_monitor_status(self, camera_key: str) -> dict | None:
        value = self.monitor_status.get(camera_key)
        return dict(value) if value else None

    # 功能：处理 `_process_static_frames` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `cfg`（dict）：运行配置对象
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True

    # 功能：ROI 多边形左上角偏移,用于把 ROI 局部坐标转回全图坐标；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：list[tuple[int, int]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/dwell_consumer.py` 的 `DwellDetectionConsumer::post_process` 调用本符号
    #   - 内部调用：`offsets.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _get_roi_offsets(self, camera_id: int) -> list[tuple[int, int]]:
        """ROI 多边形左上角偏移,用于把 ROI 局部坐标转回全图坐标"""
        offsets = []
        if camera_id in self._masks:
            for _mask, y_min, _y_max, x_min, _x_max in self._masks[camera_id]:
                offsets.append((x_min, y_min))
        return offsets
