"""非法闯闸必须同时满足不同人员、同向过线与有效共同出现。"""
import pytest
from pydantic import ValidationError

from AiVision.features.tailgating.runtime import TailgatingRuntime
from AiVision.features.tailgating.schema import TailgatingValue

SHAPE = (200, 200, 3)


def runtime(**changes):
    return TailgatingRuntime(TailgatingValue(
        roi_pos=[[0.05, 0.05], [0.95, 0.05], [0.95, 0.95], [0.05, 0.95]],
        line_points=[[0.1, 0.5], [0.9, 0.5]], foot_ratio=1.0, **changes,
    ))


def observe(state, now, heights, xs=(0.3, 0.7), shape=SHAPE):
    detections = [{"bbox": [x * 200 - 12, y * 200 - 70, x * 200 + 12, y * 200], "confidence": 0.9}
                  for x, y in zip(xs, heights)]
    return state.update(detections, shape, now=now)


def test_parallel_crossing_with_confirmed_overlap_alarms_once_per_pair():
    state = runtime()
    assert not observe(state, 0.0, [0.35, 0.35])["alarm"]
    assert not observe(state, 0.2, [0.45, 0.45])["alarm"]
    result = observe(state, 0.4, [0.55, 0.55])
    assert result["alarm"] and result["count"] == 2
    assert result["events"][0]["overlap_seconds"] == 0.4
    event_id = result["events"][0]["id"]
    assert observe(state, 0.6, [0.65, 0.65])["events"][0]["id"] == event_id


def test_follower_crossing_requires_both_people_to_cross():
    state = runtime()
    observe(state, 0.0, [0.35, 0.3])
    observe(state, 0.2, [0.45, 0.35])
    assert not observe(state, 0.4, [0.55, 0.45])["alarm"]
    assert observe(state, 0.6, [0.65, 0.55])["alarm"]


@pytest.mark.parametrize("heights", [[0.3, 0.4], [0.6, 0.7], [0.4]])
def test_people_standing_or_a_single_person_do_not_alarm(heights):
    state = runtime()
    for now in (0.0, 0.2, 0.4, 0.6):
        assert not observe(state, now, heights)["alarm"]


def test_short_overlap_does_not_alarm_even_when_both_cross():
    state = runtime(overlap_seconds=0.5)
    observe(state, 0.0, [0.4, 0.4])
    assert not observe(state, 0.2, [0.6, 0.6])["alarm"]
    assert not observe(state, 0.4, [0.98, 0.98])["alarm"]


def test_opposite_directions_and_unmonitored_direction_do_not_alarm():
    state = runtime()
    observe(state, 0.0, [0.4, 0.6])
    observe(state, 0.2, [0.45, 0.55])
    assert not observe(state, 0.4, [0.55, 0.45])["alarm"]
    reverse = runtime(direction=-1)
    observe(reverse, 0.0, [0.4, 0.4])
    observe(reverse, 0.2, [0.45, 0.45])
    assert not observe(reverse, 0.4, [0.55, 0.55])["alarm"]


def test_bidirectional_mode_still_requires_matching_directions():
    state = runtime(direction=0)
    observe(state, 0.0, [0.6, 0.6])
    observe(state, 0.2, [0.55, 0.55])
    result = observe(state, 0.4, [0.45, 0.45])
    assert result["alarm"] and result["events"][0]["direction"] == -1


def test_sequential_crossings_without_roi_overlap_do_not_alarm():
    state = runtime()
    state.config.roi_pos = [[0.05, 0.4], [0.95, 0.4], [0.95, 0.6], [0.05, 0.6]]
    for now, heights in [(0.0, [0.45, 0.2]), (0.2, [0.55, 0.25]), (0.4, [0.65, 0.35]),
                         (0.6, [0.75, 0.45]), (0.8, [0.85, 0.55])]:
        assert not observe(state, now, heights)["alarm"]


def test_people_outside_roi_and_crossing_line_extension_do_not_alarm():
    outside = runtime()
    extension = runtime()
    extension.config.line_points = [[0.4, 0.5], [0.6, 0.5]]
    for now, y in [(0.0, 0.4), (0.2, 0.45), (0.4, 0.55)]:
        assert not observe(outside, now, [y, y], xs=(0.01, 0.99))["alarm"]
        assert not observe(extension, now, [y, y])["alarm"]


def test_line_jitter_does_not_count_as_crossing():
    state = runtime()
    for now, y in [(0.0, 0.499), (0.2, 0.501), (0.4, 0.499), (0.6, 0.501)]:
        assert not observe(state, now, [y, y])["alarm"]


def test_missing_observations_do_not_accumulate_overlap_time():
    state = runtime()
    observe(state, 0.0, [0.4, 0.4])
    observe(state, 0.2, [])
    assert not observe(state, 0.4, [0.45, 0.45])["alarm"]
    assert not observe(state, 0.6, [0.55, 0.55])["alarm"]


def test_long_sampling_gap_and_resolution_change_clear_previous_evidence():
    for changed in (False, True):
        state = runtime()
        observe(state, 0.0, [0.4, 0.4])
        observe(state, 0.2, [0.45, 0.45])
        result = observe(state, 0.4 if changed else 2.0, [0.55, 0.55], shape=(201, 200, 3) if changed else SHAPE)
        assert not result["alarm"]
        assert result["reason"] == ("clear" if changed else "sampling_gap")


def test_expired_association_does_not_match_a_later_crossing():
    state = runtime(crossing_window_seconds=0.5)
    state.config.roi_pos = [[0.05, 0.1], [0.95, 0.1], [0.95, 0.7], [0.05, 0.7]]
    observe(state, 0.0, [0.4, 0.4])
    observe(state, 0.2, [0.45, 0.45])
    observe(state, 0.4, [0.55, 0.45])
    observe(state, 0.6, [0.65, 0.45])
    observe(state, 0.8, [0.75, 0.45])
    observe(state, 1.0, [0.85, 0.45])
    observe(state, 1.2, [0.85, 0.45])
    assert not observe(state, 1.4, [0.85, 0.55])["alarm"]


def test_separate_cameras_have_independent_tracks_and_overlap():
    first, second = runtime(), runtime()
    observe(first, 0.0, [0.4, 0.4])
    observe(first, 0.2, [0.45, 0.45])
    assert observe(first, 0.4, [0.55, 0.55])["alarm"]
    assert not observe(second, 0.4, [0.55, 0.55])["alarm"]


def test_crossing_can_finish_after_confirmed_shared_presence_has_ended():
    state = runtime()
    state.config.roi_pos = [[0.05, 0.1], [0.95, 0.1], [0.95, 0.7], [0.05, 0.7]]
    observe(state, 0.0, [0.4, 0.3])
    observe(state, 0.2, [0.45, 0.35])
    observe(state, 0.4, [0.55, 0.4])
    observe(state, 0.6, [0.65, 0.45])
    assert observe(state, 0.8, [0.75, 0.55])["alarm"]


def test_reversing_does_not_reuse_the_previous_passage_overlap():
    state = runtime()
    observe(state, 0.0, [0.4, 0.4])
    observe(state, 0.2, [0.45, 0.45])
    observe(state, 0.4, [0.55, 0.45])
    assert not observe(state, 0.6, [0.45, 0.55])["alarm"]


def test_next_passage_of_same_tracks_has_a_new_event_identity():
    state = runtime(direction=0)
    observe(state, 0.0, [0.4, 0.4])
    observe(state, 0.2, [0.45, 0.45])
    first = observe(state, 0.4, [0.55, 0.55])["events"][0]["id"]
    observe(state, 0.6, [0.6, 0.6])
    assert not observe(state, 0.8, [0.45, 0.45])["alarm"]
    observe(state, 1.0, [0.4, 0.4])
    second = observe(state, 1.2, [0.35, 0.35])["events"][0]["id"]
    assert first != second


def test_three_people_in_one_passage_form_one_event():
    state = runtime()
    for now, y in [(0.0, 0.4), (0.2, 0.45), (0.4, 0.55)]:
        result = observe(state, now, [y, y, y], xs=(0.2, 0.5, 0.8))
    assert len(result["events"]) == 1
    assert len(result["events"][0]["track_ids"]) == 3


def test_independent_opposite_direction_groups_have_distinct_events():
    state = runtime(direction=0)
    for now, forward, reverse in [(0.0, 0.4, 0.6), (0.2, 0.45, 0.55), (0.4, 0.55, 0.45)]:
        result = observe(state, now, [forward, forward, reverse, reverse], xs=(0.15, 0.35, 0.65, 0.85))
    assert len(result["events"]) == 2
    assert {event["direction"] for event in result["events"]} == {-1, 1}


@pytest.mark.parametrize("change", [
    {"overlap_seconds": 0.0}, {"overlap_seconds": float("nan")}, {"direction": 2}, {"direction": True}, {"threshold": 0.005},
    {"line_points": [[0.5, 0.5], [0.5, 0.5]]}, {"roi_pos": [[0.0, 0.0], [1.0, 1.0]]},
    {"max_frame_gap_seconds": 0.2, "cap_interval": 0.3},
    {"crossing_window_seconds": 0.5, "overlap_seconds": 1.0}, {"unused_option": True},
])
def test_invalid_config_is_rejected(change):
    with pytest.raises(ValidationError):
        TailgatingValue.model_validate(change)
