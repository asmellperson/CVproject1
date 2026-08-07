from __future__ import annotations

from datetime import datetime, time, timezone
import sys
from threading import Event, Thread
from types import SimpleNamespace

import numpy as np
import pytest

FEATURE = "detect_logistics_single_person"
OTHER_FEATURE = "detect_logistics_single_person_electronics_electrician"


class FakeChannelService:
    def __init__(self, channels):
        self.channels = {(item["feature_name"], item["id"]): item for item in channels}

    def list_channels(self, feature_name):
        return {
            "items": [
                {key: channel[key] for key in ("id", "name", "feature_name", "enabled", "sort_order")}
                for (feature, _channel_id), channel in self.channels.items()
                if feature == feature_name
            ]
        }

    def get_channel(self, feature_name, channel_id):
        return self.channels.get((feature_name, channel_id))

    def migrate_existing_feature_cameras(self):
        return SimpleNamespace(created=0, skipped=0, failed=0, errors=())


class FakeDispatcher:
    def __init__(self):
        self.requests = []
        self.reset_calls = []

    def maybe_dispatch(self, request, alarm_interval=5.0):
        self.requests.append((request, alarm_interval))
        return True

    def reset_subject_cooldown(self, subject_type, subject_id, feature_name):
        self.reset_calls.append((subject_type, subject_id, feature_name))


def channel(
    channel_id=3,
    *,
    feature=FEATURE,
    member_ids=(10, 11),
    empty_grace=0.0,
    multi_grace=0.0,
    enabled=True,
    start=time(0, 0),
    end=time(23, 59, 59),
):
    return {
        "id": channel_id,
        "name": f"物流通道-{channel_id}",
        "feature_name": feature,
        "enabled": enabled,
        "sort_order": 0,
        "config": {
            "enabled": enabled,
            "detection_start": start,
            "detection_end": end,
            "empty_grace_seconds": empty_grace,
            "multi_grace_seconds": multi_grace,
            "alarm_interval": 13.0,
            "alarm": {
                "sql_enable": True,
                "horn": {"enabled": False, "horn_id": None, "horn_event_id": None},
                "wechat": {"enabled": False, "user": ""},
            },
        },
        "members": [
            {"id": index, "channel_id": channel_id, "camera_id": camera_id, "enabled": True, "sort_order": index}
            for index, camera_id in enumerate(member_ids, start=1)
        ],
    }


def build_runtime(
    channels,
    *,
    active=None,
    wall_time=None,
    cameras=None,
    compositor=None,
    start_background=False,
    clock=None,
    stop_timeout=2.0,
    dispatcher=None,
    channel_service=None,
):
    loaded_platform = sys.modules.get("platform")
    if loaded_platform is not None and not hasattr(loaded_platform, "__path__"):
        sys.modules.pop("platform", None)
    from platform.logistics_channel.runtime import LogisticsChannelRuntime

    dispatcher = dispatcher or FakeDispatcher()
    cameras = cameras or {
        camera_id: {
            "id": camera_id,
            "name": f"摄像头-{camera_id}",
            "shm_name": f"camera_{camera_id}",
        }
        for item in channels
        for camera_id in [member["camera_id"] for member in item["members"]]
    }
    runtime = LogisticsChannelRuntime(
        channel_service=channel_service or FakeChannelService(channels),
        dispatcher=dispatcher,
        camera_provider=lambda camera_id: cameras.get(int(camera_id)),
        is_camera_active=active or (lambda _shm_name: True),
        stale_seconds=5.0,
        wall_time_provider=wall_time
        or (lambda: datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc).astimezone()),
        violation_type_provider=lambda feature_name: 6 if feature_name == FEATURE else 7,
        compositor=compositor,
        start_background=start_background,
        clock_provider=clock,
        stop_timeout_seconds=stop_timeout,
    )
    runtime.start()
    return runtime, dispatcher


def snapshot(camera_id, count, *, now=100.0, online=True):
    from platform.logistics_channel.state import CameraSnapshot

    return CameraSnapshot(
        camera_id=camera_id,
        camera_name=f"摄像头-{camera_id}",
        count=count,
        updated_at=now,
        online=online,
    )


def test_partial_unknown_does_not_trigger_empty_but_known_multiple_wins():
    runtime, dispatcher = build_runtime([channel()])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 0), np.zeros((8, 8, 3), np.uint8))

    unknown = runtime.evaluate(FEATURE, 3, now=100.0)

    assert unknown.reason == "unknown"
    assert dispatcher.requests == []

    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), np.zeros((8, 8, 3), np.uint8))
    multiple = runtime.evaluate(FEATURE, 3, now=100.1)

    assert multiple.reason == "multiple"
    assert multiple.alarm is True
    assert len(dispatcher.requests) == 1


def test_alarm_is_dispatched_once_per_incident_and_again_after_recovery():
    runtime, dispatcher = build_runtime([channel(member_ids=(10,))])
    frame = np.full((12, 16, 3), 20, np.uint8)

    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), frame)
    runtime.evaluate(FEATURE, 3, now=100.0)
    runtime.evaluate(FEATURE, 3, now=110.0)
    assert len(dispatcher.requests) == 1

    runtime.update_camera_snapshot(FEATURE, snapshot(10, 1, now=111.0), frame)
    assert runtime.evaluate(FEATURE, 3, now=111.0).reason == "normal"
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=112.0), frame)
    runtime.evaluate(FEATURE, 3, now=112.0)

    assert len(dispatcher.requests) == 2
    assert dispatcher.reset_calls == [("logistics_channel", "3", FEATURE)]


def test_cooldown_rejection_does_not_permanently_latch_new_incident():
    runtime, dispatcher = build_runtime([channel(member_ids=(10,))])
    accepted = iter((False, True))

    def maybe_dispatch(request, alarm_interval=5.0):
        dispatcher.requests.append((request, alarm_interval))
        return next(accepted)

    dispatcher.maybe_dispatch = maybe_dispatch
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)

    runtime.evaluate(FEATURE, 3, now=100.0)
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=101.0), None)
    runtime.evaluate(FEATURE, 3, now=101.0)
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=102.0), None)
    runtime.evaluate(FEATURE, 3, now=102.0)

    assert len(dispatcher.requests) == 2


def test_dispatch_request_uses_channel_subject_mosaic_and_complete_metadata():
    runtime, dispatcher = build_runtime([channel()])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), np.full((10, 20, 3), 10, np.uint8))
    runtime.update_camera_snapshot(FEATURE, snapshot(11, 1), np.full((10, 20, 3), 30, np.uint8))

    runtime.evaluate(FEATURE, 3, now=101.0)

    request, interval = dispatcher.requests[0]
    assert request.subject_type == "logistics_channel"
    assert request.subject_id == "3"
    assert request.subject_name == "物流通道-3"
    assert request.camera_name == "物流通道-3"
    assert request.reason == "multiple"
    assert request.frame.shape == (360, 1280, 3)
    assert interval == 13.0
    assert request.metadata["channel_id"] == 3
    assert request.metadata["channel_name"] == "物流通道-3"
    assert request.metadata["camera_ids"] == [10, 11]
    assert request.metadata["camera_counts"] == {"10": 2, "11": 1}
    assert request.metadata["camera_states"]["10"]["status"] == "multiple"
    assert request.metadata["offending_camera_ids"] == [10]
    assert request.metadata["alarm_started_at"] == 101.0
    assert request.metadata["triggered_at"] == 101.0


def test_all_members_must_be_fresh_online_and_zero_for_empty_alarm():
    active = {"camera_10": True, "camera_11": False}
    runtime, dispatcher = build_runtime([channel()], active=lambda key: active[key])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 0), None)
    runtime.update_camera_snapshot(FEATURE, snapshot(11, 0), None)

    assert runtime.evaluate(FEATURE, 3, now=100.0).reason == "unknown"
    assert dispatcher.requests == []

    active["camera_11"] = True
    decision = runtime.evaluate(FEATURE, 3, now=100.1)
    assert decision.reason == "empty"
    assert len(dispatcher.requests) == 1


def test_schedule_and_feature_namespaces_are_isolated():
    outside = channel(channel_id=3, start=time(11, 0), end=time(12, 0))
    other = channel(channel_id=3, feature=OTHER_FEATURE, member_ids=(10,))
    runtime, dispatcher = build_runtime(
        [outside, other],
        wall_time=lambda: datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc).astimezone(),
    )

    assert runtime.camera_should_run(FEATURE, 10) is False
    assert runtime.evaluate(FEATURE, 3, now=100.0).reason == "inactive"

    runtime.update_camera_snapshot(OTHER_FEATURE, snapshot(10, 2), None)
    assert runtime.evaluate(OTHER_FEATURE, 3, now=100.0).reason == "multiple"
    assert len(dispatcher.requests) == 1
    assert dispatcher.requests[0][0].feature_name == OTHER_FEATURE


def test_refresh_clears_timing_snapshot_and_incident_state():
    item = channel(member_ids=(10,), multi_grace=5.0)
    runtime, dispatcher = build_runtime([item])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)
    assert runtime.evaluate(FEATURE, 3, now=100.0).alarm is False
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=106.0), None)
    assert runtime.evaluate(FEATURE, 3, now=106.0).alarm is True

    runtime.refresh_channel(FEATURE, 3)

    assert runtime.get_channel_status(FEATURE, 3) is None
    assert runtime.evaluate(FEATURE, 3, now=107.0).reason == "unknown"
    assert len(dispatcher.requests) == 1


def test_concurrent_camera_updates_produce_consistent_channel_snapshot():
    runtime, _dispatcher = build_runtime([channel()])

    threads = [
        Thread(target=runtime.update_camera_snapshot, args=(FEATURE, snapshot(camera_id, count), None))
        for camera_id, count in ((10, 1), (11, 1))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    decision = runtime.evaluate(FEATURE, 3, now=100.0)
    status = runtime.get_channel_status(FEATURE, 3)
    assert decision.reason == "normal"
    assert status["camera_counts"] == {"10": 1, "11": 1}


@pytest.mark.parametrize("invalid_count", [True, -1, 1.5])
def test_invalid_count_is_unknown_in_decision_and_display(invalid_count):
    runtime, dispatcher = build_runtime([channel(member_ids=(10,))])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, invalid_count), None)

    decision = runtime.evaluate(FEATURE, 3, now=100.0)
    status = runtime.get_channel_status(FEATURE, 3)

    assert decision.reason == "unknown"
    assert status["camera_counts"] == {"10": None}
    assert status["camera_states"]["10"]["status"] == "unknown"
    assert status["camera_states"]["10"]["stale_reason"] == "invalid_count"
    assert dispatcher.requests == []


def test_compositor_runs_only_for_alarm_or_explicit_frame_request():
    calls = []

    def compositor(tiles):
        calls.append(tuple(tile.camera_id for tile in tiles))
        return np.zeros((20, 30, 3), np.uint8)

    runtime, dispatcher = build_runtime(
        [channel(member_ids=(10,))],
        compositor=compositor,
    )
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 1), None)

    assert runtime.evaluate(FEATURE, 3, now=100.0).reason == "normal"
    assert calls == []
    assert runtime.get_composite_frame(FEATURE, 3).shape == (20, 30, 3)
    assert calls == [(10,)]

    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=101.0), None)
    assert runtime.evaluate(FEATURE, 3, now=101.0).reason == "multiple"
    assert calls == [(10,), (10,)]
    assert len(dispatcher.requests) == 1


def test_service_camera_online_compositor_and_dispatcher_run_outside_global_lock():
    from platform.logistics_channel.runtime import LogisticsChannelRuntime

    holder = {}
    item = channel(member_ids=(10,))

    def assert_unlocked():
        runtime = holder.get("runtime")
        if runtime is not None:
            assert runtime._lock._is_owned() is False

    class GuardedService(FakeChannelService):
        def list_channels(self, feature_name):
            assert_unlocked()
            return super().list_channels(feature_name)

        def get_channel(self, feature_name, channel_id):
            assert_unlocked()
            return super().get_channel(feature_name, channel_id)

    class GuardedDispatcher(FakeDispatcher):
        def maybe_dispatch(self, request, alarm_interval=5.0):
            assert_unlocked()
            return super().maybe_dispatch(request, alarm_interval)

    dispatcher = GuardedDispatcher()
    runtime = LogisticsChannelRuntime(
        channel_service=GuardedService([item]),
        dispatcher=dispatcher,
        camera_provider=lambda camera_id: (
            assert_unlocked()
            or {"id": camera_id, "name": "摄像头-10", "shm_name": "camera_10"}
        ),
        is_camera_active=lambda _key: assert_unlocked() or True,
        compositor=lambda _tiles: assert_unlocked() or np.zeros((10, 10, 3), np.uint8),
        stale_seconds=5.0,
        wall_time_provider=lambda: datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc),
        violation_type_provider=lambda _feature: assert_unlocked() or 6,
        start_background=False,
    )
    holder["runtime"] = runtime
    runtime.start()
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)

    assert runtime.evaluate(FEATURE, 3, now=100.0).alarm is True
    assert len(dispatcher.requests) == 1


def test_refresh_during_slow_composition_discards_stale_incident_result():
    entered = Event()
    release = Event()

    def slow_compositor(_tiles):
        entered.set()
        assert release.wait(1.0)
        return np.zeros((10, 10, 3), np.uint8)

    item = channel(member_ids=(10,))
    service = FakeChannelService([item])
    runtime, dispatcher = build_runtime(
        [item],
        channel_service=service,
        compositor=slow_compositor,
    )
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)
    worker = Thread(target=runtime.evaluate, args=(FEATURE, 3), kwargs={"now": 100.0})
    worker.start()
    assert entered.wait(1.0)

    item["name"] = "重命名后的通道"
    runtime.refresh_channel(FEATURE, 3)
    release.set()
    worker.join(1.0)

    assert worker.is_alive() is False
    assert dispatcher.requests == []
    assert runtime.get_channel_status(FEATURE, 3) is None


def test_camera_rename_and_delete_refresh_real_runtime_membership_cache():
    item = channel(member_ids=(10, 11))
    service = FakeChannelService([item])
    cameras = {
        10: {"id": 10, "name": "旧名称", "shm_name": "camera_10"},
        11: {"id": 11, "name": "待删除", "shm_name": "camera_11"},
    }
    runtime, dispatcher = build_runtime(
        [item],
        channel_service=service,
        cameras=cameras,
    )
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)
    runtime.update_camera_snapshot(FEATURE, snapshot(11, 0), None)
    runtime.evaluate(FEATURE, 3, now=100.0)
    assert dispatcher.requests[0][0].metadata["camera_states"]["10"]["camera_name"] == "旧名称"

    cameras[10]["name"] = "新名称"
    runtime.refresh_camera_all(10)
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=101.0), None)
    runtime.update_camera_snapshot(FEATURE, snapshot(11, 0, now=101.0), None)
    runtime.evaluate(FEATURE, 3, now=101.0)
    assert dispatcher.requests[-1][0].metadata["camera_states"]["10"]["camera_name"] == "新名称"

    item["members"] = [member for member in item["members"] if member["camera_id"] != 11]
    cameras.pop(11)
    runtime.refresh_camera_all(11)
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 0, now=102.0), None)
    decision = runtime.evaluate(FEATURE, 3, now=102.0)
    status = runtime.get_channel_status(FEATURE, 3)

    assert decision.reason == "empty"
    assert status["camera_ids"] == [10]
    assert status["camera_counts"] == {"10": 0}


def test_stop_timeout_keeps_thread_reference_and_prevents_double_start():
    entered = Event()
    release = Event()

    class BlockingDispatcher(FakeDispatcher):
        def maybe_dispatch(self, request, alarm_interval=5.0):
            entered.set()
            assert release.wait(2.0)
            return super().maybe_dispatch(request, alarm_interval)

    dispatcher = BlockingDispatcher()
    item = channel(member_ids=(10,))
    runtime, _ = build_runtime(
        [item],
        dispatcher=dispatcher,
        start_background=True,
        clock=lambda: 100.0,
        stop_timeout=0.01,
    )
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)
    assert entered.wait(1.5)
    original_thread = runtime._thread

    with pytest.raises(RuntimeError, match="停止超时"):
        runtime.stop()
    assert runtime._thread is original_thread
    assert original_thread.is_alive()
    with pytest.raises(RuntimeError, match="禁止重复启动"):
        runtime.start()

    release.set()
    original_thread.join(1.0)
    assert original_thread.is_alive() is False
    runtime.stop()
    runtime.start()
    assert runtime._thread is not original_thread
    runtime.stop()
