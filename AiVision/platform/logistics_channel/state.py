# 文件说明：实现状态管理相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""物流通道的纯状态判定、检测框去重与快照存储。"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from threading import RLock
from typing import Iterable, Literal


ChannelReason = Literal["normal", "empty", "multiple", "unknown", "unconfigured", "inactive"]


# 功能：定义 `CameraSnapshot` 类，封装状态管理相关的状态、约束与操作
# 参数：
#   - `camera_id`（int）：摄像头唯一标识
#   - `count`（int | None）：`count` 对应的数量或大小
#   - `updated_at`（float）：`updated_at` 对应的业务输入值
#   - `online`（bool）：`online` 对应的业务输入值
#   - `camera_name`（str）：`camera_name` 对应的业务输入值
# 返回：CameraSnapshot；返回新建的 `CameraSnapshot` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_state.py` 的 `test_classify_channel_uses_joint_camera_rule_with_priority`
#         实例化本符号；`AiVision/tests/test_logistics_channel_state.py` 的 `test_classify_channel_reports_disabled_channel_as_inactive`
#         实例化本符号；`AiVision/tests/test_logistics_channel_state.py` 的 `test_classify_channel_staleness_boundary_is_inclusive`
#         实例化本符号；`AiVision/tests/test_logistics_channel_state.py` 的
#         `test_classify_channel_rejects_non_finite_or_negative_time_inputs` 实例化本符号；另有 9 处静态调用
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class CameraSnapshot:
    camera_id: int
    count: int | None
    updated_at: float
    online: bool = True
    camera_name: str = ""


# 功能：定义 `ChannelDecision` 类，封装状态管理相关的状态、约束与操作
# 参数：
#   - `reason`（ChannelReason）：`reason` 对应的业务输入值
#   - `alarm`（bool）：`alarm` 对应的业务输入值
#   - `duration_seconds`（float）：`duration_seconds` 对应的时间间隔或时长
#   - `threshold_seconds`（float | None）：`threshold_seconds` 对应的时间间隔或时长
#   - `offending_camera_ids`（tuple[int, ...]）：`offending_camera_ids` 对应的业务输入值
# 返回：ChannelDecision；返回新建的 `ChannelDecision` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/state.py` 的 `ChannelPresenceState::evaluate`
#         实例化本符号；`AiVision/platform/logistics_channel/state.py` 的 `_decision`
#         实例化本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::evaluate` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class ChannelDecision:
    reason: ChannelReason
    alarm: bool
    duration_seconds: float
    threshold_seconds: float | None
    offending_camera_ids: tuple[int, ...] = ()


# 功能：定义 `PersonDetection` 类，封装状态管理相关的状态、约束与操作
# 参数：
#   - `bbox`（tuple[float, float, float, float]）：`bbox` 对应的业务输入值
#   - `confidence`（float）：模型预测或规则判断的置信度
#   - `source_roi`（int | None）：`source_roi` 对应的业务输入值
# 返回：PersonDetection；返回新建的 `PersonDetection` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/state.py` 的 `translate_person_detection`
#         实例化本符号；`AiVision/tests/test_logistics_channel_state.py` 的
#         `test_translate_person_detection_offsets_box_without_mutating_input`
#         实例化本符号；`AiVision/tests/test_logistics_channel_state.py` 的
#         `test_deduplicate_person_detections_removes_overlap_keeps_distinct_and_is_deterministic`
#         实例化本符号；`AiVision/tests/test_logistics_channel_state.py` 的
#         `test_deduplicate_person_detections_filters_invalid_boxes_and_validates_threshold` 实例化本符号；另有 4 处静态调用
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class PersonDetection:
    bbox: tuple[float, float, float, float]
    confidence: float
    source_roi: int | None = None


# 功能：按全体摄像头人数作无副作用的通道基础判定；输入与输出详见下方说明
# 参数：
#   - `snapshots`（Iterable[CameraSnapshot]）：`snapshots` 对应的业务输入值
#   - `now`（float）：`now` 对应的业务输入值
#   - `stale_seconds`（float）：`stale_seconds` 对应的时间间隔或时长
#   - `active`（bool）：`active` 对应的业务输入值；默认值为 `True`
# 返回：ChannelDecision；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_state.py` 的 `test_classify_channel_uses_joint_camera_rule_with_priority`
#         调用本符号；`AiVision/tests/test_logistics_channel_state.py` 的 `test_classify_channel_reports_empty_membership_as_unconfigured`
#         调用本符号；`AiVision/tests/test_logistics_channel_state.py` 的 `test_classify_channel_reports_disabled_channel_as_inactive`
#         调用本符号；`AiVision/tests/test_logistics_channel_state.py` 的
#         `test_classify_channel_treats_invalid_or_unavailable_snapshot_as_unknown` 调用本符号；另有 7 处静态调用
#   - 内部调用：`_is_finite_number`、`ValueError`、`tuple`、`_decision`、`isinstance`、`offending_camera_ids.append`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def classify_channel(
    snapshots: Iterable[CameraSnapshot], *, now: float, stale_seconds: float, active: bool = True
) -> ChannelDecision:
    """按全体摄像头人数作无副作用的通道基础判定。"""
    if not _is_finite_number(now) or not _is_finite_number(stale_seconds) or stale_seconds < 0:
        raise ValueError("stale_seconds 必须大于等于 0")
    snapshot_list = tuple(snapshots)
    if not active:
        return _decision("inactive")
    if not snapshot_list:
        return _decision("unconfigured")

    has_normal = False
    has_empty = False
    has_unknown = False
    offending_camera_ids: list[int] = []
    for snapshot in snapshot_list:
        count = snapshot.count
        if (
            not snapshot.online
            or not _is_finite_number(snapshot.updated_at)
            or snapshot.updated_at > now
            or now - snapshot.updated_at > stale_seconds
            or count is None
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            has_unknown = True
        elif count >= 2:
            offending_camera_ids.append(snapshot.camera_id)
        elif count == 1:
            has_normal = True
        else:
            has_empty = True

    if offending_camera_ids:
        return _decision("multiple", offending_camera_ids=tuple(offending_camera_ids))
    if has_normal:
        return _decision("normal")
    if has_unknown:
        return _decision("unknown")
    if has_empty:
        return _decision("empty")
    return _decision("unknown")


# 功能：对连续空人/多人状态计时；实例由单个通道运行时持有；输入与输出详见下方说明
# 参数：无。
# 返回：ChannelPresenceState；返回新建的 `ChannelPresenceState` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_state.py` 的 `test_presence_state_accumulates_empty_only_until_its_grace_period`
#         实例化本符号；`AiVision/tests/test_logistics_channel_state.py` 的 `test_presence_state_switches_reason_and_resets_the_other_timer`
#         实例化本符号；`AiVision/tests/test_logistics_channel_state.py` 的 `test_presence_state_non_alarm_reasons_clear_timers`
#         实例化本符号；`AiVision/tests/test_logistics_channel_state.py` 的
#         `test_presence_state_zero_grace_alarms_immediately_and_preserves_offenders` 实例化本符号；另有 5 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ChannelPresenceState:
    """对连续空人/多人状态计时；实例由单个通道运行时持有。"""

    # 功能：初始化或配置 `__init__` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self) -> None:
        self._reason: ChannelReason | None = None
        self._started_at: float | None = None
        self._last_evaluated_at: float | None = None

    # 功能：实现 `evaluate` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `decision_or_reason`（ChannelDecision | ChannelReason）：`decision_or_reason` 对应的业务输入值
    #   - `now`（float）：`now` 对应的业务输入值
    #   - `empty_grace_seconds`（float）：`empty_grace_seconds` 对应的时间间隔或时长
    #   - `multi_grace_seconds`（float）：`multi_grace_seconds` 对应的时间间隔或时长
    # 返回：ChannelDecision；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`_is_finite_number`、`ValueError`、`isinstance`、`self.reset`、`_decision`、`max`、`ChannelDecision`。
    # 副作用/注意事项：会更新当前实例的运行状态；校验或执行失败时会主动抛出异常。
    def evaluate(
        self,
        decision_or_reason: ChannelDecision | ChannelReason,
        *,
        now: float,
        empty_grace_seconds: float,
        multi_grace_seconds: float,
    ) -> ChannelDecision:
        if (
            not _is_finite_number(now)
            or not _is_finite_number(empty_grace_seconds)
            or not _is_finite_number(multi_grace_seconds)
            or empty_grace_seconds < 0
            or multi_grace_seconds < 0
        ):
            raise ValueError("持续时间阈值必须大于等于 0")
        if isinstance(decision_or_reason, ChannelDecision):
            reason = decision_or_reason.reason
            offending_camera_ids = decision_or_reason.offending_camera_ids
        else:
            reason = decision_or_reason
            offending_camera_ids = ()
        if reason not in {"normal", "empty", "multiple", "unknown", "unconfigured", "inactive"}:
            raise ValueError(f"不支持的通道状态: {reason!r}")

        if reason not in {"empty", "multiple"}:
            self.reset()
            return _decision(reason, offending_camera_ids=offending_camera_ids)

        if (
            self._reason != reason
            or self._started_at is None
            or self._last_evaluated_at is None
            or now < self._last_evaluated_at
        ):
            self._reason = reason
            self._started_at = now
        duration = max(0.0, now - self._started_at)
        self._last_evaluated_at = now
        threshold = empty_grace_seconds if reason == "empty" else multi_grace_seconds
        return ChannelDecision(
            reason=reason,
            alarm=duration >= threshold,
            duration_seconds=duration,
            threshold_seconds=threshold,
            offending_camera_ids=offending_camera_ids,
        )

    # 功能：清空当前连续异常状态；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/state.py` 的 `ChannelPresenceState::evaluate` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def reset(self) -> None:
        """清空当前连续异常状态。"""
        self._reason = None
        self._started_at = None
        self._last_evaluated_at = None


# 功能：将 ROI 内的检测框平移回原始画面坐标；输入与输出详见下方说明
# 参数：
#   - `detection`（PersonDetection）：`detection` 对应的业务输入值
#   - `x_offset`（float）：`x_offset` 对应的业务输入值
#   - `y_offset`（float）：`y_offset` 对应的业务输入值
# 返回：PersonDetection；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_state.py` 的 `test_translate_person_detection_offsets_box_without_mutating_input`
#         调用本符号；`AiVision/features/_base/logistics_single_person_consumer.py` 的 `LogisticsSinglePersonConsumerBase::post_process`
#         调用本符号
#   - 内部调用：`PersonDetection`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def translate_person_detection(
    detection: PersonDetection, x_offset: float, y_offset: float
) -> PersonDetection:
    """将 ROI 内的检测框平移回原始画面坐标。"""
    x1, y1, x2, y2 = detection.bbox
    return PersonDetection(
        bbox=(x1 + x_offset, y1 + y_offset, x2 + x_offset, y2 + y_offset),
        confidence=detection.confidence,
        source_roi=detection.source_roi,
    )


# 功能：计算两个正面积 bbox 的 IoU；无效或无重叠的框返回零；输入与输出详见下方说明
# 参数：
#   - `a`（tuple[float, float, float, float]）：`a` 对应的业务输入值
#   - `b`（tuple[float, float, float, float]）：`b` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/state.py` 的 `deduplicate_person_detections`
#         调用本符号；`AiVision/tests/test_logistics_channel_state.py` 的 `test_intersection_over_union_handles_overlap_and_invalid_boxes`
#         调用本符号
#   - 内部调用：`_is_valid_bbox`、`max`、`min`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def intersection_over_union(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    """计算两个正面积 bbox 的 IoU；无效或无重叠的框返回零。"""
    if not _is_valid_bbox(a) or not _is_valid_bbox(b):
        return 0.0
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    overlap_width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    overlap_height = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = overlap_width * overlap_height
    if intersection == 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union


# 功能：以确定性置信度排序执行轻量 NMS，丢弃无效框；输入与输出详见下方说明
# 参数：
#   - `detections`（Iterable[PersonDetection]）：`detections` 对应的业务输入值
#   - `iou_threshold`（float）：`iou_threshold` 对应的业务输入值；默认值为 `0.5`
# 返回：tuple[PersonDetection, ...]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_state.py` 的
#         `test_deduplicate_person_detections_removes_overlap_keeps_distinct_and_is_deterministic`
#         调用本符号；`AiVision/tests/test_logistics_channel_state.py` 的
#         `test_deduplicate_person_detections_filters_invalid_boxes_and_validates_threshold`
#         调用本符号；`AiVision/tests/test_logistics_channel_state.py` 的
#         `test_deduplicate_person_detections_validates_iou_bounds_and_uses_strict_duplicate_cutoff`
#         调用本符号；`AiVision/tests/test_logistics_channel_state.py` 的
#         `test_deduplicate_person_detections_filters_non_finite_or_out_of_range_candidates` 调用本符号；另有 2 处静态调用
#   - 内部调用：`_is_finite_number`、`ValueError`、`_is_valid_bbox`、`_is_valid_confidence`、`candidates.sort`、`all`、`intersection_over_union`、`selected.append`、`tuple`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def deduplicate_person_detections(
    detections: Iterable[PersonDetection], *, iou_threshold: float = 0.5
) -> tuple[PersonDetection, ...]:
    """以确定性置信度排序执行轻量 NMS，丢弃无效框。"""
    if not _is_finite_number(iou_threshold) or not 0 <= iou_threshold <= 1:
        raise ValueError("iou_threshold 必须在 0 到 1 之间")
    candidates = [
        detection
        for detection in detections
        if _is_valid_bbox(detection.bbox) and _is_valid_confidence(detection.confidence)
    ]
    candidates.sort(key=_detection_sort_key)
    selected: list[PersonDetection] = []
    for detection in candidates:
        if all(intersection_over_union(detection.bbox, kept.bbox) <= iou_threshold for kept in selected):
            selected.append(detection)
    return tuple(selected)


# 功能：按功能和摄像头编号隔离的线程安全不可变快照仓库；输入与输出详见下方说明
# 参数：无。
# 返回：CameraSnapshotStore；返回新建的 `CameraSnapshotStore` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_state.py` 的 `test_snapshot_store_isolates_features_and_returns_immutable_snapshots`
#         实例化本符号；`AiVision/tests/test_logistics_channel_state.py` 的 `test_snapshot_store_clear_feature_only_removes_its_own_entries`
#         实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraSnapshotStore:
    """按功能和摄像头编号隔离的线程安全不可变快照仓库。"""

    # 功能：初始化或配置 `__init__` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`RLock`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshots: dict[tuple[str, int], CameraSnapshot] = {}

    # 功能：实现 `upsert` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `snapshot`（CameraSnapshot）：`snapshot` 对应的业务输入值
    # 返回：CameraSnapshot；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_state.py` 的
    #         `test_snapshot_store_isolates_features_and_returns_immutable_snapshots`
    #         调用本符号；`AiVision/tests/test_logistics_channel_state.py` 的
    #         `test_snapshot_store_clear_feature_only_removes_its_own_entries` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def upsert(self, feature_name: str, snapshot: CameraSnapshot) -> CameraSnapshot:
        with self._lock:
            self._snapshots[(feature_name, snapshot.camera_id)] = snapshot
            return snapshot

    # 功能：读取或查询 `get` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：CameraSnapshot | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._snapshots.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get(self, feature_name: str, camera_id: int) -> CameraSnapshot | None:
        with self._lock:
            return self._snapshots.get((feature_name, camera_id))

    # 功能：删除或清理 `remove` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：CameraSnapshot | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._snapshots.pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def remove(self, feature_name: str, camera_id: int) -> CameraSnapshot | None:
        with self._lock:
            return self._snapshots.pop((feature_name, camera_id), None)

    # 功能：删除或清理 `clear_feature` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：tuple[CameraSnapshot, ...]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_state.py` 的 `test_snapshot_store_clear_feature_only_removes_its_own_entries`
    #         调用本符号
    #   - 内部调用：`tuple`、`self._snapshots.pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def clear_feature(self, feature_name: str) -> tuple[CameraSnapshot, ...]:
        with self._lock:
            keys = [key for key in self._snapshots if key[0] == feature_name]
            removed = tuple(self._snapshots.pop(key) for key in keys)
            return removed


# 功能：实现 `_decision` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `reason`（ChannelReason）：`reason` 对应的业务输入值
#   - `offending_camera_ids`（tuple[int, ...]）：`offending_camera_ids` 对应的业务输入值；默认值为 `()`
# 返回：ChannelDecision；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/state.py` 的 `classify_channel` 调用本符号；`AiVision/platform/logistics_channel/state.py` 的
#         `ChannelPresenceState::evaluate` 调用本符号
#   - 内部调用：`ChannelDecision`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _decision(reason: ChannelReason, *, offending_camera_ids: tuple[int, ...] = ()) -> ChannelDecision:
    return ChannelDecision(
        reason=reason,
        alarm=False,
        duration_seconds=0.0,
        threshold_seconds=None,
        offending_camera_ids=offending_camera_ids,
    )


# 功能：检查或判断 `_is_valid_bbox` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `bbox`（tuple[float, float, float, float]）：`bbox` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/state.py` 的 `intersection_over_union`
#         调用本符号；`AiVision/platform/logistics_channel/state.py` 的 `deduplicate_person_detections` 调用本符号
#   - 内部调用：`len`、`all`、`_is_finite_number`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _is_valid_bbox(bbox: tuple[float, float, float, float]) -> bool:
    if len(bbox) != 4 or not all(_is_finite_number(coordinate) for coordinate in bbox):
        return False
    x1, y1, x2, y2 = bbox
    return x2 > x1 and y2 > y1


# 功能：检查或判断 `_is_valid_confidence` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `confidence`（float）：模型预测或规则判断的置信度
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/state.py` 的 `deduplicate_person_detections` 调用本符号
#   - 内部调用：`_is_finite_number`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _is_valid_confidence(confidence: float) -> bool:
    return _is_finite_number(confidence) and 0 <= confidence <= 1


# 功能：检查或判断 `_is_finite_number` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（object）：待转换、校验或写入的值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/state.py` 的 `classify_channel` 调用本符号；`AiVision/platform/logistics_channel/state.py` 的
#         `ChannelPresenceState::evaluate` 调用本符号；`AiVision/platform/logistics_channel/state.py` 的 `deduplicate_person_detections`
#         调用本符号；`AiVision/platform/logistics_channel/state.py` 的 `_is_valid_bbox` 调用本符号；另有 1 处静态调用
#   - 内部调用：`isinstance`、`isfinite`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


# 功能：实现 `_detection_sort_key` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `detection`（PersonDetection）：`detection` 对应的业务输入值
# 返回：tuple[float, tuple[float, float, float, float], int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _detection_sort_key(detection: PersonDetection) -> tuple[float, tuple[float, float, float, float], int]:
    return (-detection.confidence, detection.bbox, -1 if detection.source_roi is None else detection.source_roi)
