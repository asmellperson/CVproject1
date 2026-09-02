# 文件说明：实现视频帧消费与检测的帧消费、判定与告警衔接逻辑。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""四个物流通道单人检测功能共用的逐摄像头消费者。"""
from __future__ import annotations

import time
from typing import Protocol

import cv2
import numpy as np

from AiVision.platform.logistics_channel.state import (
    CameraSnapshot,
    PersonDetection,
    deduplicate_person_detections,
    translate_person_detection,
)
from AiVision.features._base.consumer import BaseFunctionConsumer


DEFAULT_PERSON_DEDUP_IOU_THRESHOLD = 0.5


# 功能：Task 5 的最小运行时注入边界；通道聚合实现在后续任务中提供；输入与输出详见下方说明
# 参数：无。
# 返回：LogisticsConsumerRuntime；返回新建的 `LogisticsConsumerRuntime` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsConsumerRuntime(Protocol):
    """Task 5 的最小运行时注入边界；通道聚合实现在后续任务中提供。"""

    # 功能：启动或执行 `camera_should_run` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def camera_should_run(self, feature_name: str, camera_id: int) -> bool: ...

    # 功能：实现 `person_confidence_threshold` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：float | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def person_confidence_threshold(self, feature_name: str, camera_id: int) -> float | None: ...

    # 功能：更新或保存 `update_camera_snapshot` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `snapshot`（CameraSnapshot）：`snapshot` 对应的业务输入值
    #   - `annotated_frame`（np.ndarray | None）：`annotated_frame` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_camera_snapshot(
        self,
        feature_name: str,
        snapshot: CameraSnapshot,
        annotated_frame: np.ndarray | None,
    ) -> None: ...

    # 功能：更新或保存 `evaluate_after_camera_update` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def evaluate_after_camera_update(self, feature_name: str, camera_id: int) -> None: ...


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


# 功能：保留原监控读取契约；通道页面切换前仍可读取单路结果；输入与输出详见下方说明
# 参数：
#   - `result`（未显式标注）：`result` 对应的业务输入值
#   - `updated_at`（float | None）：`updated_at` 对应的业务输入值；默认值为 `None`
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_single_person.py` 的 `test_monitor_snapshot_sums_known_roi_counts_and_preserves_alarm` 调用本符号
#   - 内部调用：`isinstance`、`detail.get`、`counts.append`、`reasons.append`、`str`、`bool`、`next`、`sum`、`time.time`、`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def build_monitor_snapshot(result, updated_at: float | None = None) -> dict:
    """保留原监控读取契约；通道页面切换前仍可读取单路结果。"""
    counts: list[int] = []
    reasons: list[str] = []
    alarm = False

    for item in result or []:
        try:
            alarm_flag, detail = item
        except (TypeError, ValueError):
            continue
        detail = detail if isinstance(detail, dict) else {}
        count = detail.get("person_count")
        if isinstance(count, int) and not isinstance(count, bool):
            counts.append(count)
        reasons.append(str(detail.get("reason") or "unknown"))
        alarm = alarm or bool(alarm_flag)

    reason = next(
        (candidate for candidate in ("multiple", "empty", "normal") if candidate in reasons),
        "unknown",
    )
    return {
        "count": sum(counts) if counts else None,
        "alarm": alarm,
        "reason": reason,
        "updated_at_s": time.time() if updated_at is None else float(updated_at),
    }


# 功能：逐路推理、坐标还原和快照发布；人数告警统一交给通道运行时；输入与输出详见下方说明
# 参数：
#   - `*args`（未显式标注）：`args` 对应的业务输入值
#   - `logistics_runtime`（LogisticsConsumerRuntime | None）：`logistics_runtime` 对应的业务输入值；默认值为 `None`
#   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
# 返回：LogisticsSinglePersonConsumerBase；返回新建的 `LogisticsSinglePersonConsumerBase` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsSinglePersonConsumerBase(BaseFunctionConsumer):
    """逐路推理、坐标还原和快照发布；人数告警统一交给通道运行时。"""

    BBOX_COLOR_NORMAL = (0, 180, 0)
    BBOX_COLOR_ABNORMAL = (0, 0, 255)
    ROI_COLOR_NORMAL = (0, 180, 0)
    ROI_COLOR_ABNORMAL = (0, 0, 255)
    ROI_COLOR_UNKNOWN = (0, 165, 255)

    # 功能：初始化或配置 `__init__` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `logistics_runtime`（LogisticsConsumerRuntime | None）：`logistics_runtime` 对应的业务输入值；默认值为 `None`
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`RuntimeError`、`type`、`super().__init__`、`super`。
    # 副作用/注意事项：会更新当前实例的运行状态；校验或执行失败时会主动抛出异常。
    def __init__(self, *args, logistics_runtime: LogisticsConsumerRuntime | None = None, **kwargs):
        if logistics_runtime is None:
            raise RuntimeError(
                f"{type(self).__name__} 缺少 LogisticsChannelRuntime 注入；"
                "物流单人检测不能在无通道聚合运行时的情况下启动"
            )
        super().__init__(*args, **kwargs)
        self.logistics_runtime = logistics_runtime
        self.monitor_status: dict[str, dict] = {}

    # 功能：处理 `_process` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `roi_list`（未显式标注）：`roi_list` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._value_config`、`self.config_cache.get`、`_number_or_default`、`cfg.get`、`getattr`、`callable`、`threshold_provider`、`isinstance`、`len`、`self._unknown_roi_result`
    #          等共 17 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process(self, roi_list, camera_id):
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        conf_thr = _number_or_default(cfg.get("CONF_THRESHOLD"), 0.3)
        threshold_provider = getattr(self.logistics_runtime, "person_confidence_threshold", None)
        if callable(threshold_provider):
            conf_thr = _number_or_default(
                threshold_provider(self.feature_name, camera_id),
                conf_thr,
            )
        iou_thr = _number_or_default(cfg.get("IOU_THR"), 0.3)
        min_box_area = _number_or_default(cfg.get("MIN_BOX_AREA"), 0)
        aspect_range = cfg.get("ASPECT_RATIO_RANGE") or []
        min_aspect, max_aspect = None, None
        if isinstance(aspect_range, (list, tuple)) and len(aspect_range) >= 2:
            min_aspect = _number_or_default(aspect_range[0], 0)
            max_aspect = _number_or_default(aspect_range[1], 10)

        if not self.spec.required_models:
            return [self._unknown_roi_result() for _ in roi_list]

        det_results = self.dispatch_inference_sync(
            camera_id,
            self.spec.required_models[0],
            roi_list,
            task_meta={"conf": conf_thr, "iou": iou_thr},
        )
        results_by_roi = {item.get("roi_id", 0): item for item in det_results}

        results = []
        for roi_index in range(len(roi_list)):
            det_result = results_by_roi.get(roi_index)
            if det_result is None:
                results.append(self._unknown_roi_result())
                continue
            detections = self._filter_person_detections(
                det_result.get("detections", []) or [],
                min_box_area=min_box_area,
                min_aspect=min_aspect,
                max_aspect=max_aspect,
            )
            count = len(detections)
            reason = "empty" if count == 0 else "normal" if count == 1 else "multiple"
            results.append(
                (
                    False,
                    {
                        "reason": reason,
                        "person_count": count,
                        "elapsed": 0.0,
                        "detections": detections,
                    },
                )
            )
        return results

    # 功能：实现 `_unknown_roi_result` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：tuple[bool, dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/logistics_single_person_consumer.py` 的 `LogisticsSinglePersonConsumerBase::_process` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _unknown_roi_result() -> tuple[bool, dict]:
        return False, {
            "reason": "unknown",
            "person_count": None,
            "elapsed": 0.0,
            "detections": [],
        }

    # 功能：实现 `_filter_person_detections` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `detections`（未显式标注）：`detections` 对应的业务输入值
    #   - `min_box_area`（float）：`min_box_area` 对应的业务输入值
    #   - `min_aspect`（未显式标注）：`min_aspect` 对应的业务输入值
    #   - `max_aspect`（未显式标注）：`max_aspect` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/logistics_single_person_consumer.py` 的 `LogisticsSinglePersonConsumerBase::_process` 调用本符号
    #   - 内部调用：`detection.get`、`len`、`max`、`float`、`persons.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _filter_person_detections(detections, min_box_area: float, min_aspect, max_aspect):
        persons = []
        for detection in detections:
            detection_type = detection.get("type")
            if detection_type and detection_type not in {"person", "human"}:
                continue
            bbox = detection.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            width = max(0.0, float(bbox[2]) - float(bbox[0]))
            height = max(0.0, float(bbox[3]) - float(bbox[1]))
            if width * height < min_box_area:
                continue
            if height > 0 and min_aspect is not None and max_aspect is not None:
                aspect = width / height
                if aspect < min_aspect or aspect > max_aspect:
                    continue
            persons.append(detection)
        return persons

    # 功能：处理 `post_process` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `result`（未显式标注）：`result` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.frame_cache.get`、`frame.copy`、`self._get_roi_polygons`、`self._get_roi_offsets`、`enumerate`、`isinstance`、`str`、`detail.get`、`self._color_for_reason`、`len`
    #          等共 38 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def post_process(self, camera_id, result):
        frame = self.frame_cache.get(camera_id)
        annotated = frame.copy() if frame is not None else None
        roi_polygons = self._get_roi_polygons(camera_id)
        roi_offsets = self._get_roi_offsets(camera_id)
        translated_detections: list[PersonDetection] = []
        has_unknown_roi = False

        for roi_index, (_alarm, raw_detail) in enumerate(result or []):
            detail = raw_detail if isinstance(raw_detail, dict) else {}
            reason = str(detail.get("reason") or "unknown")
            has_unknown_roi = has_unknown_roi or reason == "unknown"
            roi_color = self._color_for_reason(reason)

            if annotated is not None and roi_index < len(roi_polygons):
                polygon = np.array(roi_polygons[roi_index], dtype=np.int32)
                cv2.polylines(annotated, [polygon.reshape(-1, 1, 2)], True, roi_color, 2)
                label_x = int(polygon[:, 0].min())
                label_y = max(20, int(polygon[:, 1].min()) - 8)
                cv2.putText(
                    annotated,
                    self._label_for(reason, detail.get("person_count")),
                    (label_x, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    roi_color,
                    2,
                )

            x_offset, y_offset = roi_offsets[roi_index] if roi_index < len(roi_offsets) else (0, 0)
            for detection in detail.get("detections") or []:
                bbox = detection.get("bbox")
                if not bbox or len(bbox) < 4:
                    continue
                try:
                    translated_detections.append(
                        translate_person_detection(
                            PersonDetection(
                                bbox=tuple(float(value) for value in bbox[:4]),
                                confidence=float(detection.get("confidence", 0)),
                                source_roi=roi_index,
                            ),
                            x_offset,
                            y_offset,
                        )
                    )
                except (TypeError, ValueError):
                    continue

        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        dedup_iou = _number_or_default(
            cfg.get("DEDUP_IOU_THRESHOLD"), DEFAULT_PERSON_DEDUP_IOU_THRESHOLD
        )
        if not 0 <= dedup_iou <= 1:
            dedup_iou = DEFAULT_PERSON_DEDUP_IOU_THRESHOLD
        unique_detections = deduplicate_person_detections(
            translated_detections,
            iou_threshold=dedup_iou,
        )
        count = len(unique_detections)
        snapshot_count = count if count >= 2 or not has_unknown_roi else None
        updated_at = time.time()
        camera_cfg = self.config_cache.get(camera_id, {})
        camera_key = str(camera_cfg.get("shm_name") or "").strip()
        camera_name = str(camera_cfg.get("name") or camera_key)
        snapshot = CameraSnapshot(
            camera_id=camera_id,
            camera_name=camera_name,
            count=snapshot_count,
            updated_at=updated_at,
            online=self._camera_online(camera_key),
        )

        if annotated is not None:
            self._draw_unique_detections(annotated, unique_detections, snapshot_count)
        if camera_key:
            self.monitor_status[camera_key] = {
                "count": snapshot_count,
                "alarm": False,
                "reason": self._snapshot_reason(snapshot_count),
                "updated_at_s": updated_at,
            }
        self.logistics_runtime.update_camera_snapshot(self.feature_name, snapshot, annotated)
        return annotated

    # 功能：实现 `_camera_online` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_key`（str）：`camera_key` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/logistics_single_person_consumer.py` 的 `LogisticsSinglePersonConsumerBase::post_process`
    #         调用本符号
    #   - 内部调用：`getattr`、`callable`、`bool`、`checker`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _camera_online(self, camera_key: str) -> bool:
        checker = getattr(self, "is_camera_active", None)
        if not camera_key or not callable(checker):
            return True
        return bool(checker(camera_key))

    # 功能：绘制或渲染 `_draw_unique_detections` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    #   - `detections`（tuple[PersonDetection, ...]）：`detections` 对应的业务输入值
    #   - `count`（int | None）：`count` 对应的数量或大小
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/logistics_single_person_consumer.py` 的 `LogisticsSinglePersonConsumerBase::post_process`
    #         调用本符号
    #   - 内部调用：`int`、`cv2.rectangle`、`cv2.putText`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _draw_unique_detections(
        self,
        frame: np.ndarray,
        detections: tuple[PersonDetection, ...],
        count: int | None,
    ) -> None:
        color = self.BBOX_COLOR_ABNORMAL if count is not None and count >= 2 else self.BBOX_COLOR_NORMAL
        for detection in detections:
            x1, y1, x2, y2 = (int(value) for value in detection.bbox)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"person {detection.confidence:.2f}",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

    # 功能：实现 `_color_for_reason` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `reason`（str）：`reason` 对应的业务输入值
    # 返回：tuple[int, int, int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/logistics_single_person_consumer.py` 的 `LogisticsSinglePersonConsumerBase::post_process`
    #         调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @classmethod
    def _color_for_reason(cls, reason: str) -> tuple[int, int, int]:
        if reason in {"empty", "multiple"}:
            return cls.ROI_COLOR_ABNORMAL
        if reason == "unknown":
            return cls.ROI_COLOR_UNKNOWN
        return cls.ROI_COLOR_NORMAL

    # 功能：实现 `_label_for` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `reason`（str）：`reason` 对应的业务输入值
    #   - `count`（未显式标注）：`count` 对应的数量或大小
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/logistics_single_person_consumer.py` 的 `LogisticsSinglePersonConsumerBase::post_process`
    #         调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _label_for(reason: str, count) -> str:
        if reason == "empty":
            return "EMPTY count=0"
        if reason == "multiple":
            return f"MULTI count={count}"
        if reason == "normal":
            return "OK count=1"
        return "UNKNOWN"

    # 功能：实现 `_snapshot_reason` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `count`（int | None）：`count` 对应的数量或大小
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/logistics_single_person_consumer.py` 的 `LogisticsSinglePersonConsumerBase::post_process`
    #         调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _snapshot_reason(count: int | None) -> str:
        if count is None:
            return "unknown"
        if count == 0:
            return "empty"
        if count == 1:
            return "normal"
        return "multiple"

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

    # 功能：检查或判断 `_should_process_now` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `cfg`（dict）：运行配置对象
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`bool`、`self.logistics_runtime.camera_should_run`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _should_process_now(self, camera_id: int, cfg: dict) -> bool:
        return bool(self.logistics_runtime.camera_should_run(self.feature_name, camera_id))

    # 功能：处理 `_handle_alarm` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `result`（list）：`result` 对应的业务输入值
    #   - `frame`（np.ndarray | None）：待处理的视频图像帧
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.logistics_runtime.evaluate_after_camera_update`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _handle_alarm(self, camera_id: int, result: list, frame: np.ndarray | None):
        self.logistics_runtime.evaluate_after_camera_update(self.feature_name, camera_id)

    # 功能：读取或查询 `_get_roi_offsets` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：list[tuple[int, int]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/logistics_single_person_consumer.py` 的 `LogisticsSinglePersonConsumerBase::post_process`
    #         调用本符号
    #   - 内部调用：`self._masks.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _get_roi_offsets(self, camera_id: int) -> list[tuple[int, int]]:
        return [
            (x_min, y_min)
            for _mask, y_min, _y_max, x_min, _x_max in self._masks.get(camera_id, [])
        ]
