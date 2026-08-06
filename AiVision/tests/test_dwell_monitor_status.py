from types import SimpleNamespace

from features._base.dwell_consumer import build_dwell_monitor_snapshot


class FakeTracker:
    def __init__(self, tracks):
        self.tracks = tracks


def test_dwell_snapshot_counts_visible_tracks_and_longest_duration():
    trackers = {
        (7, 0): FakeTracker({
            1: SimpleNamespace(first_seen=100.0, lost=0, alarmed=False),
            2: SimpleNamespace(first_seen=90.0, lost=0, alarmed=True),
            3: SimpleNamespace(first_seen=80.0, lost=1, alarmed=True),
        }),
        (8, 0): FakeTracker({
            4: SimpleNamespace(first_seen=70.0, lost=0, alarmed=True),
        }),
    }

    snapshot = build_dwell_monitor_snapshot(
        trackers,
        camera_id=7,
        threshold_seconds=15.0,
        now=110.0,
        updated_at=109.5,
    )

    assert snapshot == {
        "count": 2,
        "alarm": True,
        "reason": "loitering",
        "duration_seconds": 20.0,
        "threshold_seconds": 15.0,
        "updated_at_s": 109.5,
    }


def test_dwell_snapshot_is_normal_when_roi_has_no_visible_tracks():
    snapshot = build_dwell_monitor_snapshot(
        {(7, 0): FakeTracker({1: SimpleNamespace(first_seen=90.0, lost=2, alarmed=True)})},
        camera_id=7,
        threshold_seconds=30.0,
        now=110.0,
        updated_at=110.0,
    )

    assert snapshot["count"] == 0
    assert snapshot["duration_seconds"] == 0.0
    assert snapshot["threshold_seconds"] == 30.0
    assert snapshot["alarm"] is False
    assert snapshot["reason"] == "normal"


def test_dwell_snapshot_ignores_trackers_for_removed_rois():
    snapshot = build_dwell_monitor_snapshot(
        {
            (7, 0): FakeTracker({1: SimpleNamespace(first_seen=105.0, lost=0, alarmed=False)}),
            (7, 1): FakeTracker({2: SimpleNamespace(first_seen=80.0, lost=0, alarmed=True)}),
        },
        camera_id=7,
        active_roi_indices={0},
        threshold_seconds=10.0,
        now=110.0,
        updated_at=110.0,
    )

    assert snapshot["count"] == 1
    assert snapshot["duration_seconds"] == 5.0
    assert snapshot["alarm"] is False
