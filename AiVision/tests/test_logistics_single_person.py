from features.detect_logistics_single_person.consumer import SinglePersonPresenceState


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
