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


@pytest.mark.parametrize(
    ("counts", "reason"),
    [
        ([0, 0], "empty"),
        ([1, 0], "normal"),
        ([1, 1], "normal"),
        ([2, 0], "multiple"),
        ([3, 1], "multiple"),
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


def test_classify_channel_reports_empty_membership_as_unconfigured():
    assert classify_channel([], now=100.0, stale_seconds=5.0).reason == "unconfigured"


def test_classify_channel_reports_disabled_channel_as_inactive():
    snapshots = [CameraSnapshot(camera_id=1, count=2, updated_at=100.0)]

    assert classify_channel(snapshots, now=100.0, stale_seconds=5.0, active=False).reason == "inactive"


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


def test_classify_channel_staleness_boundary_is_inclusive():
    fresh_at_boundary = CameraSnapshot(camera_id=1, count=1, updated_at=95.0)
    stale_after_boundary = CameraSnapshot(camera_id=1, count=1, updated_at=94.999)

    assert classify_channel([fresh_at_boundary], now=100.0, stale_seconds=5.0).reason == "normal"
    assert classify_channel([stale_after_boundary], now=100.0, stale_seconds=5.0).reason == "unknown"


def test_multiple_decision_identifies_offending_camera_ids():
    decision = classify_channel(
        [CameraSnapshot(camera_id=7, count=2, updated_at=100.0), CameraSnapshot(camera_id=8, count=0, updated_at=100.0)],
        now=100.0,
        stale_seconds=5.0,
    )

    assert decision.offending_camera_ids == (7,)


def test_presence_state_accumulates_empty_only_until_its_grace_period():
    state = ChannelPresenceState()

    first = state.evaluate("empty", now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)
    at_threshold = state.evaluate("empty", now=12.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    assert first.duration_seconds == 0.0
    assert first.alarm is False
    assert at_threshold.duration_seconds == 2.0
    assert at_threshold.alarm is True


def test_presence_state_switches_reason_and_resets_the_other_timer():
    state = ChannelPresenceState()

    state.evaluate("empty", now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)
    multiple = state.evaluate("multiple", now=11.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)
    empty = state.evaluate("empty", now=12.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    assert multiple.duration_seconds == 0.0
    assert multiple.alarm is False
    assert empty.duration_seconds == 0.0
    assert empty.alarm is False


@pytest.mark.parametrize("reason", ["normal", "unknown", "unconfigured", "inactive"])
def test_presence_state_non_alarm_reasons_clear_timers(reason):
    state = ChannelPresenceState()
    state.evaluate("empty", now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    result = state.evaluate(reason, now=11.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)
    restarted = state.evaluate("empty", now=12.0, empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    assert result.alarm is False
    assert result.duration_seconds == 0.0
    assert restarted.duration_seconds == 0.0


def test_presence_state_zero_grace_alarms_immediately_and_preserves_offenders():
    state = ChannelPresenceState()
    decision = classify_channel([CameraSnapshot(camera_id=2, count=3, updated_at=10.0)], now=10.0, stale_seconds=5.0)

    result = state.evaluate(decision, now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=0.0)

    assert result.alarm is True
    assert result.offending_camera_ids == (2,)


def test_presence_state_clock_rollback_restarts_duration_and_reset_clears_state():
    state = ChannelPresenceState()
    state.evaluate("multiple", now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=5.0)
    rollback = state.evaluate("multiple", now=9.0, empty_grace_seconds=2.0, multi_grace_seconds=5.0)
    state.reset()
    after_reset = state.evaluate("multiple", now=10.0, empty_grace_seconds=2.0, multi_grace_seconds=5.0)

    assert rollback.duration_seconds == 0.0
    assert after_reset.duration_seconds == 0.0


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


def test_presence_state_reset_clears_clock_rollback_tracking():
    state = ChannelPresenceState()
    state.evaluate("empty", now=20.0, empty_grace_seconds=5.0, multi_grace_seconds=5.0)
    state.reset()

    result = state.evaluate("empty", now=10.0, empty_grace_seconds=5.0, multi_grace_seconds=5.0)

    assert result.duration_seconds == 0.0
    assert result.alarm is False


def test_translate_person_detection_offsets_box_without_mutating_input():
    detection = PersonDetection(bbox=(1.0, 2.0, 11.0, 12.0), confidence=0.8, source_roi=4)

    translated = translate_person_detection(detection, 100.0, 200.0)

    assert translated == PersonDetection(bbox=(101.0, 202.0, 111.0, 212.0), confidence=0.8, source_roi=4)
    assert detection.bbox == (1.0, 2.0, 11.0, 12.0)


def test_intersection_over_union_handles_overlap_and_invalid_boxes():
    assert intersection_over_union((0, 0, 10, 10), (5, 5, 15, 15)) == pytest.approx(25 / 175)
    assert intersection_over_union((0, 0, 0, 10), (0, 0, 10, 10)) == 0.0


def test_deduplicate_person_detections_removes_overlap_keeps_distinct_and_is_deterministic():
    first = PersonDetection(bbox=(0, 0, 10, 10), confidence=0.9, source_roi=2)
    duplicate = PersonDetection(bbox=(1, 1, 11, 11), confidence=0.8, source_roi=1)
    distinct = PersonDetection(bbox=(20, 20, 30, 30), confidence=0.9, source_roi=3)

    result = deduplicate_person_detections([duplicate, distinct, first])

    assert result == (first, distinct)
    assert first.bbox == (0, 0, 10, 10)


def test_deduplicate_person_detections_filters_invalid_boxes_and_validates_threshold():
    valid = PersonDetection(bbox=(0, 0, 10, 10), confidence=0.5)
    invalid = PersonDetection(bbox=(4, 4, 4, 5), confidence=1.0)

    assert deduplicate_person_detections([invalid, valid]) == (valid,)
    with pytest.raises(ValueError, match="iou_threshold"):
        deduplicate_person_detections([valid], iou_threshold=1.1)


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


def test_snapshot_store_clear_feature_only_removes_its_own_entries():
    store = CameraSnapshotStore()
    first = CameraSnapshot(camera_id=1, count=1, updated_at=1.0)
    second = CameraSnapshot(camera_id=1, count=2, updated_at=1.0)
    store.upsert("one", first)
    store.upsert("two", second)

    assert store.clear_feature("one") == (first,)
    assert store.get("one", 1) is None
    assert store.get("two", 1) == second
