from datetime import time as datetime_time

from features.detect_logistics_single_person.consumer import (
    LogisticsSinglePersonConsumer,
    SinglePersonPresenceState,
    build_monitor_snapshot,
)


def test_empty_detection_alarms_only_after_grace_period():
    state = SinglePersonPresenceState(empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    first = state.evaluate(0, now=10.0)
    second = state.evaluate(0, now=11.0)
    third = state.evaluate(0, now=12.1)

    assert first.alarm is False
    assert second.alarm is False
    assert third.alarm is True
    assert third.reason == "empty"


def test_normal_single_person_resets_empty_buffer():
    state = SinglePersonPresenceState(empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    assert state.evaluate(0, now=10.0).alarm is False
    assert state.evaluate(1, now=11.0).reason == "normal"
    assert state.evaluate(0, now=12.0).alarm is False
    assert state.evaluate(0, now=13.5).alarm is False


def test_multiple_people_alarm_uses_its_own_grace_period():
    state = SinglePersonPresenceState(empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    first = state.evaluate(2, now=20.0)
    second = state.evaluate(2, now=21.1)

    assert first.alarm is False
    assert second.alarm is True
    assert second.reason == "multiple"


def test_unknown_result_does_not_accumulate_empty_time():
    state = SinglePersonPresenceState(empty_grace_seconds=2.0, multi_grace_seconds=1.0)

    assert state.evaluate(0, now=30.0).alarm is False
    unknown = state.evaluate(None, now=33.0)
    empty_again = state.evaluate(0, now=33.1)

    assert unknown.alarm is False
    assert unknown.reason == "unknown"
    assert empty_again.alarm is False


def test_logistics_single_person_detects_only_from_8_to_before_20():
    assert LogisticsSinglePersonConsumer._is_detection_time(datetime_time(7, 59, 59)) is False
    assert LogisticsSinglePersonConsumer._is_detection_time(datetime_time(8, 0, 0)) is True
    assert LogisticsSinglePersonConsumer._is_detection_time(datetime_time(19, 59, 59)) is True
    assert LogisticsSinglePersonConsumer._is_detection_time(datetime_time(20, 0, 0)) is False


def test_monitor_snapshot_sums_known_roi_counts_and_preserves_alarm():
    result = [
        (False, {"reason": "normal", "person_count": 1}),
        (True, {"reason": "multiple", "person_count": 2}),
    ]

    snapshot = build_monitor_snapshot(result, updated_at=100.0)

    assert snapshot == {
        "count": 3,
        "alarm": True,
        "reason": "multiple",
        "updated_at_s": 100.0,
    }


def test_monitor_snapshot_keeps_unknown_count_neutral():
    snapshot = build_monitor_snapshot(
        [(False, {"reason": "unknown", "person_count": None})],
        updated_at=101.0,
    )

    assert snapshot["count"] is None
    assert snapshot["alarm"] is False
    assert snapshot["reason"] == "unknown"
