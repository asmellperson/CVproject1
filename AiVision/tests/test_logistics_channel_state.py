# 文件说明：包含状态管理的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from dataclasses import FrozenInstanceError

import pytest

from platform.logistics_channel.state import (
    CameraSnapshot,
    CameraSnapshotStore,
    ChannelPresenceState,
    PersonDetection,
    classify_channel,
    deduplicate_person_detections,
    intersection_over_union,
    translate_person_detection,
)


# 功能：验证 `test_classify_channel_uses_joint_camera_rule_with_priority` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `counts`（未显式标注）：`counts` 对应的业务输入值
#   - `reason`（未显式标注）：`reason` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`CameraSnapshot`、`enumerate`、`classify_channel`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    ("counts", "reason"),
    [
        ([0, 0], "empty"),
        ([1, 0], "normal"),
        ([1, 1], "normal"),
        ([2, 0], "multiple"),
        ([3, 1], "multiple"),
        # 全无人要求所有成员均有效；未知成员不能触发全无人告警。
        ([None, 0], "unknown"),
        ([None, 1], "normal"),
        ([None, 2], "multiple"),
    ],
)
def test_classify_channel_uses_joint_camera_rule_with_priority(counts, reason):
    snapshots = [CameraSnapshot(camera_id=index + 1, count=count, updated_at=100.0) for index, count in enumerate(counts)]

    decision = classify_channel(snapshots, now=100.0, stale_seconds=5.0)

    assert decision.reason == reason
    assert decision.alarm is False
    assert decision.duration_seconds == 0.0


# 功能：验证 `test_classify_channel_reports_empty_membership_as_unconfigured` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`classify_channel`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_classify_channel_reports_empty_membership_as_unconfigured():
    assert classify_channel([], now=100.0, stale_seconds=5.0).reason == "unconfigured"


# 功能：验证 `test_classify_channel_reports_disabled_channel_as_inactive` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`CameraSnapshot`、`classify_channel`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_classify_channel_reports_disabled_channel_as_inactive():
    snapshots = [CameraSnapshot(camera_id=1, count=2, updated_at=100.0)]

    assert classify_channel(snapshots, now=100.0, stale_seconds=5.0, active=False).reason == "inactive"


# 功能：验证 `test_classify_channel_treats_invalid_or_unavailable_snapshot_as_unknown` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `snapshot`（未显式标注）：`snapshot` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`classify_channel`、`pytest.mark.parametrize`、`CameraSnapshot`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    "snapshot",
    [
        CameraSnapshot(camera_id=1, count=1, updated_at=100.0, online=False),
        CameraSnapshot(camera_id=1, count=1, updated_at=94.9),
        CameraSnapshot(camera_id=1, count=None, updated_at=100.0),
        CameraSnapshot(camera_id=1, count=True, updated_at=100.0),
        CameraSnapshot(camera_id=1, count=-1, updated_at=100.0),
    ],
)
def test_classify_channel_treats_invalid_or_unavailable_snapshot_as_unknown(snapshot):
    assert classify_channel([snapshot], now=100.0, stale_seconds=5.0).reason == "unknown"


# 功能：验证 `test_classify_channel_staleness_boundary_is_inclusive` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`CameraSnapshot`、`classify_channel`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_classify_channel_staleness_boundary_is_inclusive():
    fresh_at_boundary = CameraSnapshot(camera_id=1, count=1, updated_at=95.0)
    stale_after_boundary = CameraSnapshot(camera_id=1, count=1, updated_at=94.999)

    assert classify_channel([fresh_at_boundary], now=100.0, stale_seconds=5.0).reason == "normal"
    assert classify_channel([stale_after_boundary], now=100.0, stale_seconds=5.0).reason == "unknown"


# 功能：验证 `test_classify_channel_rejects_non_finite_or_negative_time_inputs` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `now`（未显式标注）：`now` 对应的业务输入值
#   - `stale_seconds`（未显式标注）：`stale_seconds` 对应的时间间隔或时长
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`classify_channel`、`CameraSnapshot`、`pytest.mark.parametrize`、`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("now, stale_seconds", [(float("nan"), 5.0), (float("inf"), 5.0), (100.0, float("nan")), (100.0, float("inf")), (100.0, -0.1)])
def test_classify_channel_rejects_non_finite_or_negative_time_inputs(now, stale_seconds):
    with pytest.raises(ValueError):
        classify_channel([CameraSnapshot(camera_id=1, count=1, updated_at=100.0)], now=now, stale_seconds=stale_seconds)


# 功能：验证 `test_classify_channel_treats_non_finite_snapshot_timestamp_as_unknown` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `updated_at`（未显式标注）：`updated_at` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`classify_channel`、`CameraSnapshot`、`pytest.mark.parametrize`、`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("updated_at", [float("nan"), float("inf"), float("-inf")])
def test_classify_channel_treats_non_finite_snapshot_timestamp_as_unknown(updated_at):
    decision = classify_channel([CameraSnapshot(camera_id=1, count=1, updated_at=updated_at)], now=100.0, stale_seconds=5.0)

    assert decision.reason == "unknown"


# 功能：验证 `test_classify_channel_treats_future_snapshot_timestamp_as_unknown` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`CameraSnapshot`、`classify_channel`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_classify_channel_treats_future_snapshot_timestamp_as_unknown():
    snapshot = CameraSnapshot(camera_id=1, count=1, updated_at=100.001)

    assert classify_channel([snapshot], now=100.0, stale_seconds=5.0).reason == "unknown"


# 功能：验证 `test_multiple_decision_identifies_offending_camera_ids` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`classify_channel`、`CameraSnapshot`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_multiple_decision_identifies_offending_camera_ids():
    decision = classify_channel(
        [CameraSnapshot(camera_id=7, count=2, updated_at=100.0), CameraSnapshot(camera_id=8, count=0, updated_at=100.0)],
        now=100.0,
        stale_seconds=5.0,
    )

    assert decision.offending_camera_ids == (7,)


# 功能：验证 `test_presence_state_accumulates_empty_only_until_its_grace_period` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ChannelPresenceState`、`state.evaluate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_presence_state_accumulates_empty_only_until_its_grace_period():
    state = ChannelPresenceState()

    first = state.evaluate("empty", now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)
    at_threshold = state.evaluate("empty", now=12.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    assert first.duration_seconds == 0.0
    assert first.alarm is False
    assert at_threshold.duration_seconds == 2.0
    assert at_threshold.alarm is True


# 功能：验证 `test_presence_state_switches_reason_and_resets_the_other_timer` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ChannelPresenceState`、`state.evaluate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_presence_state_switches_reason_and_resets_the_other_timer():
    state = ChannelPresenceState()

    state.evaluate("empty", now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)
    multiple = state.evaluate("multiple", now=11.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)
    empty = state.evaluate("empty", now=12.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    assert multiple.duration_seconds == 0.0
    assert multiple.alarm is False
    assert empty.duration_seconds == 0.0
    assert empty.alarm is False


# 功能：验证 `test_presence_state_non_alarm_reasons_clear_timers` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `reason`（未显式标注）：`reason` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ChannelPresenceState`、`state.evaluate`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("reason", ["normal", "unknown", "unconfigured", "inactive"])
def test_presence_state_non_alarm_reasons_clear_timers(reason):
    state = ChannelPresenceState()
    state.evaluate("empty", now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    result = state.evaluate(reason, now=11.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)
    restarted = state.evaluate("empty", now=12.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    assert result.alarm is False
    assert result.duration_seconds == 0.0
    assert restarted.duration_seconds == 0.0


# 功能：验证 `test_presence_state_zero_grace_alarms_immediately_and_preserves_offenders` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ChannelPresenceState`、`classify_channel`、`CameraSnapshot`、`state.evaluate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_presence_state_zero_grace_alarms_immediately_and_preserves_offenders():
    state = ChannelPresenceState()
    decision = classify_channel([CameraSnapshot(camera_id=2, count=3, updated_at=10.0)], now=10.0, stale_seconds=5.0)

    result = state.evaluate(decision, now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=0.0)

    assert result.alarm is True
    assert result.offending_camera_ids == (2,)


# 功能：验证 `test_presence_state_clock_rollback_restarts_duration_and_reset_clears_state` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ChannelPresenceState`、`state.evaluate`、`state.reset`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_presence_state_clock_rollback_restarts_duration_and_reset_clears_state():
    state = ChannelPresenceState()
    state.evaluate("multiple", now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=5.0)
    rollback = state.evaluate("multiple", now=9.0, empty_grace_seconds=2.0, multi_grace_seconds=5.0)
    state.reset()
    after_reset = state.evaluate("multiple", now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=5.0)

    assert rollback.duration_seconds == 0.0
    assert after_reset.duration_seconds == 0.0


# 功能：验证 `test_presence_state_rolls_back_after_accumulation_from_last_evaluation` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `reason`（未显式标注）：`reason` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ChannelPresenceState`、`state.evaluate`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("reason", ["empty", "multiple"])
def test_presence_state_rolls_back_after_accumulation_from_last_evaluation(reason):
    state = ChannelPresenceState()
    grace_seconds = 5.0

    state.evaluate(reason, now=10.0, empty_grace_seconds=grace_seconds, multi_grace_seconds=grace_seconds)
    reached_threshold = state.evaluate(
        reason, now=20.0, empty_grace_seconds=grace_seconds, multi_grace_seconds=grace_seconds
    )
    rollback = state.evaluate(reason, now=15.0, empty_grace_seconds=grace_seconds, multi_grace_seconds=grace_seconds)
    resumed = state.evaluate(reason, now=16.0, empty_grace_seconds=grace_seconds, multi_grace_seconds=grace_seconds)

    assert reached_threshold.alarm is True
    assert rollback.duration_seconds == 0.0
    assert rollback.alarm is False
    assert resumed.duration_seconds == 1.0
    assert resumed.alarm is False


# 功能：验证 `test_presence_state_reset_clears_clock_rollback_tracking` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ChannelPresenceState`、`state.evaluate`、`state.reset`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_presence_state_reset_clears_clock_rollback_tracking():
    state = ChannelPresenceState()
    state.evaluate("empty", now=20.0, empty_grace_seconds=5.0, multi_grace_seconds=5.0)
    state.reset()

    result = state.evaluate("empty", now=10.0, empty_grace_seconds=5.0, multi_grace_seconds=5.0)

    assert result.duration_seconds == 0.0
    assert result.alarm is False


# 功能：验证 `test_presence_state_rejects_non_finite_or_negative_time_inputs` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `now`（未显式标注）：`now` 对应的业务输入值
#   - `empty_grace_seconds`（未显式标注）：`empty_grace_seconds` 对应的时间间隔或时长
#   - `multi_grace_seconds`（未显式标注）：`multi_grace_seconds` 对应的时间间隔或时长
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`ChannelPresenceState().evaluate`、`ChannelPresenceState`、`pytest.mark.parametrize`、`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    "now, empty_grace_seconds, multi_grace_seconds",
    [
        (float("nan"), 1.0, 1.0),
        (float("inf"), 1.0, 1.0),
        (1.0, float("nan"), 1.0),
        (1.0, 1.0, float("inf")),
        (1.0, -0.1, 1.0),
        (1.0, 1.0, -0.1),
    ],
)
def test_presence_state_rejects_non_finite_or_negative_time_inputs(now, empty_grace_seconds, multi_grace_seconds):
    with pytest.raises(ValueError):
        ChannelPresenceState().evaluate(
            "empty",
            now=now,
            empty_grace_seconds=empty_grace_seconds,
            multi_grace_seconds=multi_grace_seconds,
        )


# 功能：验证 `test_translate_person_detection_offsets_box_without_mutating_input` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`PersonDetection`、`translate_person_detection`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_translate_person_detection_offsets_box_without_mutating_input():
    detection = PersonDetection(bbox=(1.0, 2.0, 11.0, 12.0), confidence=0.8, source_roi=4)

    translated = translate_person_detection(detection, 100.0, 200.0)

    assert translated == PersonDetection(bbox=(101.0, 202.0, 111.0, 212.0), confidence=0.8, source_roi=4)
    assert detection.bbox == (1.0, 2.0, 11.0, 12.0)


# 功能：验证 `test_intersection_over_union_handles_overlap_and_invalid_boxes` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`intersection_over_union`、`pytest.approx`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_intersection_over_union_handles_overlap_and_invalid_boxes():
    assert intersection_over_union((0, 0, 10, 10), (5, 5, 15, 15)) == pytest.approx(25 / 175)
    assert intersection_over_union((0, 0, 0, 10), (0, 0, 10, 10)) == 0.0


# 功能：验证 `test_deduplicate_person_detections_removes_overlap_keeps_distinct_and_is_deterministic` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`PersonDetection`、`deduplicate_person_detections`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_deduplicate_person_detections_removes_overlap_keeps_distinct_and_is_deterministic():
    first = PersonDetection(bbox=(0, 0, 10, 10), confidence=0.9, source_roi=2)
    duplicate = PersonDetection(bbox=(1, 1, 11, 11), confidence=0.8, source_roi=1)
    distinct = PersonDetection(bbox=(20, 20, 30, 30), confidence=0.9, source_roi=3)

    result = deduplicate_person_detections([duplicate, distinct, first])

    assert result == (first, distinct)
    assert first.bbox == (0, 0, 10, 10)


# 功能：验证 `test_deduplicate_person_detections_filters_invalid_boxes_and_validates_threshold` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`PersonDetection`、`deduplicate_person_detections`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_deduplicate_person_detections_filters_invalid_boxes_and_validates_threshold():
    valid = PersonDetection(bbox=(0, 0, 10, 10), confidence=0.5)
    invalid = PersonDetection(bbox=(4, 4, 4, 5), confidence=1.0)

    assert deduplicate_person_detections([invalid, valid]) == (valid,)
    with pytest.raises(ValueError, match="iou_threshold"):
        deduplicate_person_detections([valid], iou_threshold=1.1)


# 功能：验证 `test_deduplicate_person_detections_validates_iou_bounds_and_uses_strict_duplicate_cutoff` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`PersonDetection`、`pytest.raises`、`deduplicate_person_detections`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_deduplicate_person_detections_validates_iou_bounds_and_uses_strict_duplicate_cutoff():
    first = PersonDetection(bbox=(0, 0, 10, 10), confidence=0.9)
    identical = PersonDetection(bbox=(0, 0, 10, 10), confidence=0.8)
    distinct = PersonDetection(bbox=(20, 20, 30, 30), confidence=0.7)

    with pytest.raises(ValueError, match="iou_threshold"):
        deduplicate_person_detections([first], iou_threshold=-0.01)
    with pytest.raises(ValueError, match="iou_threshold"):
        deduplicate_person_detections([first], iou_threshold=1.01)
    assert deduplicate_person_detections([first, identical, distinct], iou_threshold=0.0) == (first, distinct)
    assert deduplicate_person_detections([first, identical, distinct], iou_threshold=1.0) == (
        first,
        identical,
        distinct,
    )


# 功能：验证 `test_deduplicate_person_detections_filters_non_finite_or_out_of_range_candidates` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `invalid`（未显式标注）：`invalid` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`PersonDetection`、`deduplicate_person_detections`、`pytest.mark.parametrize`、`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    "invalid",
    [
        PersonDetection(bbox=(float("nan"), 0, 10, 10), confidence=0.9),
        PersonDetection(bbox=(0, 0, float("inf"), 10), confidence=0.9),
        PersonDetection(bbox=(0, 0, 10, 10), confidence=float("nan")),
        PersonDetection(bbox=(0, 0, 10, 10), confidence=float("inf")),
        PersonDetection(bbox=(0, 0, 10, 10), confidence=-0.01),
        PersonDetection(bbox=(0, 0, 10, 10), confidence=1.01),
    ],
)
def test_deduplicate_person_detections_filters_non_finite_or_out_of_range_candidates(invalid):
    valid = PersonDetection(bbox=(20, 20, 30, 30), confidence=0.5)

    assert deduplicate_person_detections([invalid, valid]) == (valid,)


# 功能：验证 `test_deduplicate_person_detections_output_order_is_independent_of_input_order` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`PersonDetection`、`deduplicate_person_detections`、`reversed`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_deduplicate_person_detections_output_order_is_independent_of_input_order():
    detections = (
        PersonDetection(bbox=(20, 20, 30, 30), confidence=0.8, source_roi=2),
        PersonDetection(bbox=(0, 0, 10, 10), confidence=0.8, source_roi=1),
        PersonDetection(bbox=(40, 40, 50, 50), confidence=0.9, source_roi=None),
    )

    first_order = deduplicate_person_detections(detections)
    reversed_order = deduplicate_person_detections(reversed(detections))

    assert first_order == reversed_order


# 功能：验证 `test_snapshot_store_isolates_features_and_returns_immutable_snapshots` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`CameraSnapshotStore`、`CameraSnapshot`、`store.upsert`、`store.get`、`pytest.raises`、`store.remove`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_snapshot_store_isolates_features_and_returns_immutable_snapshots():
    store = CameraSnapshotStore()
    original = CameraSnapshot(camera_id=7, count=1, updated_at=100.0)

    assert store.upsert("detect_logistics_single_person", original) == original
    assert store.get("detect_logistics_single_person", 7) == original
    assert store.get("other-feature", 7) is None
    with pytest.raises(FrozenInstanceError):
        store.get("detect_logistics_single_person", 7).count = 2
    assert store.remove("detect_logistics_single_person", 7) == original
    assert store.get("detect_logistics_single_person", 7) is None


# 功能：验证 `test_snapshot_store_clear_feature_only_removes_its_own_entries` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`CameraSnapshotStore`、`CameraSnapshot`、`store.upsert`、`store.clear_feature`、`store.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_snapshot_store_clear_feature_only_removes_its_own_entries():
    store = CameraSnapshotStore()
    first = CameraSnapshot(camera_id=1, count=1, updated_at=1.0)
    second = CameraSnapshot(camera_id=1, count=2, updated_at=1.0)
    store.upsert("one", first)
    store.upsert("two", second)

    assert store.clear_feature("one") == (first,)
    assert store.get("one", 1) is None
    assert store.get("two", 1) == second
