"""Site 规则使用确定性时间和纯数据快照，不依赖模型或摄像头。"""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from AiVision.features.guard_behavior.constants import ALARM_INTERVAL_DEFAULTS
from AiVision.features.guard_behavior.schema import (
    GuardBehaviorRuntimeAlarmPolicy, GuardBehaviorRuntimeMember, GuardBehaviorRuntimePolicy,
    GuardBehaviorRuntimeSiteConfig,
)
from AiVision.features.guard_behavior.site_rules import (
    AbsenceState, aggregate_positive, camera_availability, expected_members, stale_seconds,
)
from AiVision.features.guard_behavior.state import (
    CameraAvailability, GuardCameraSnapshot, LocalRuleDecision, TrackedPerson, VehicleDetection, VehicleObservation,
)
from AiVision.features.guard_behavior.vehicle_episode import VehicleEpisodeTracker
from AiVision.features.guard_behavior.runtime import GuardBehaviorSiteRuntime, TILE_HEIGHT, TILE_WIDTH


def site_config(*, enabled=True, count=2, **policy):
    return GuardBehaviorRuntimeSiteConfig(
        site_id=1, site_name="南门", department="general_electric", enabled=enabled,
        members=tuple(GuardBehaviorRuntimeMember(
            camera_id=index, camera_name=f"Camera {index}", shm_name=f"camera-{index}",
            member_enabled=True, feature_enabled=True, physical_enabled=True, sort_order=index,
        ) for index in range(1, count + 1)),
        policy=GuardBehaviorRuntimePolicy(**policy),
        alarm_policies=tuple(GuardBehaviorRuntimeAlarmPolicy(violation_type=kind, alarm_interval=interval)
                             for kind, interval in ALARM_INTERVAL_DEFAULTS.items()),
    )


def snapshot(camera_id=1, now=100., present=False, **changes):
    value = GuardCameraSnapshot(
        camera_id, f"Camera {camera_id}", 1, "南门", now, True,
        present, None if present is None else int(present), .9 if present else 0.,
        LocalRuleDecision(), LocalRuleDecision(), VehicleObservation(False),
        {"yolo_guard_person_phone": "ready", "guard_uniform": "ready",
         "yolo_guard_pose": "ready", "yolo_vehicle": "not_applicable"},
        (TrackedPerson((10., 10., 30., 80.), .9, 1),) if present else (), (100, 100),
    )
    return replace(value, **changes)


def camera_states(config, snapshots, now):
    return {member.camera_id: camera_availability(member, snapshots.get(member.camera_id), now, stale_seconds(config),
                                                 physical_online=member.camera_id not in snapshots or snapshots[member.camera_id].online)
            for member in expected_members(config)}


def test_absence_requires_continuous_complete_negative_evidence():
    config = site_config(absent_alarm_seconds=3.)
    snapshots = {index: snapshot(index) for index in (1, 2)}
    absence = AbsenceState()
    result = absence.evaluate(config, snapshots, camera_states(config, snapshots, 100.), 100.)
    assert result.state == "pending" and result.duration_seconds == 0.
    result = absence.evaluate(config, snapshots, camera_states(config, snapshots, 103.), 103.)
    assert result.state == "alarm" and result.offending_camera_ids == (1, 2)
    snapshots[1] = snapshot(1, 103., True)
    assert absence.evaluate(config, snapshots, camera_states(config, snapshots, 103.), 103.).state == "normal"
    assert absence.since is None


@pytest.mark.parametrize("failure", ["offline", "stale", "error", "unknown", "physical_disabled"])
def test_unavailable_camera_breaks_absence_accumulation(failure):
    config = site_config(absent_alarm_seconds=1.)
    snapshots = {index: snapshot(index) for index in (1, 2)}
    absence = AbsenceState()
    absence.evaluate(config, snapshots, camera_states(config, snapshots, 100.), 100.)
    if failure == "offline":
        snapshots[2] = replace(snapshots[2], online=False)
    elif failure == "stale":
        snapshots[2] = replace(snapshots[2], updated_at=90.)
    elif failure == "error":
        snapshots[2] = replace(snapshots[2], guard_present=None, guard_count=None,
                               model_states={**snapshots[2].model_states, "guard_uniform": "error"})
    elif failure == "unknown":
        snapshots[2] = replace(snapshots[2], guard_present=None, guard_count=None)
    else:
        config = config.model_copy(update={"members": (config.members[0], config.members[1].model_copy(
            update={"physical_enabled": False}))})
    result = absence.evaluate(config, snapshots, camera_states(config, snapshots, 101.), 101.)
    assert result.state == "unknown" and absence.since is None


def test_absence_does_not_bridge_an_unobserved_stale_gap():
    config = site_config(count=1, absent_alarm_seconds=10.)
    absence = AbsenceState()
    snapshots = {1: snapshot()}
    absence.evaluate(config, snapshots, camera_states(config, snapshots, 100.), 100.)
    snapshots[1] = snapshot(now=120.)
    result = absence.evaluate(config, snapshots, camera_states(config, snapshots, 120.), 120.)
    assert result.state == "pending" and result.duration_seconds == 0.


@pytest.mark.parametrize("rule", ["phone", "prone"])
def test_positive_rules_select_one_primary_and_keep_all_offending_cameras(rule):
    config = site_config(count=3)
    snapshots = {index: snapshot(index, **{rule: LocalRuleDecision("alarm", "证据达标", confidence)})
                 for index, confidence in ((1, .7), (2, .95))}
    decision = aggregate_positive(rule, snapshots, camera_states(config, snapshots, 100.))
    assert decision.state == "alarm" and decision.availability == "degraded"
    assert decision.primary_camera_id == 2 and decision.offending_camera_ids == (1, 2)


def test_expected_cameras_exclude_disabled_site_members_and_feature():
    assert expected_members(site_config(enabled=False)) == ()
    config = site_config(count=3)
    config = config.model_copy(update={"members": (
        config.members[0], config.members[1].model_copy(update={"member_enabled": False}),
        config.members[2].model_copy(update={"feature_enabled": False}),
    )})
    assert tuple(member.camera_id for member in expected_members(config)) == (1,)


def test_staleness_uses_internal_threshold_and_physical_disabled_is_distinct():
    config = site_config(cap_interval=3.)
    assert stale_seconds(config) == 9.
    assert stale_seconds(site_config(cap_interval=.1)) == 5.
    member = config.members[0]
    assert camera_availability(member, snapshot(), 109., 9., physical_online=True) == CameraAvailability.READY
    assert camera_availability(member, snapshot(), 109.01, 9., physical_online=True) == CameraAvailability.STALE
    assert camera_availability(member.model_copy(update={"physical_enabled": False}), None, 100., 5., physical_online=True) == (
        CameraAvailability.PHYSICAL_DISABLED)


def vehicle_snapshot(now, *, bbox=(40., 40., 70., 90.), present=True, guard=False):
    vehicles = (VehicleDetection(bbox, .9, 2),) if present else ()
    return snapshot(now=now, present=guard, vehicle=VehicleObservation(True, vehicles),
                    guards=(TrackedPerson((35., 40., 50., 80.), .9, 1),) if guard else ())


@pytest.mark.parametrize("inspected", [False, True])
def test_vehicle_episode_closes_once_and_guard_proximity_suppresses_alarm(inspected):
    policy = GuardBehaviorRuntimePolicy(vehicle_near_px=5., vehicle_occlusion_seconds=2., vehicle_reassociate_seconds=3.)
    tracker = VehicleEpisodeTracker()
    started = tracker.update(vehicle_snapshot(100.), 100., policy).started
    assert len(started) == 1 and tracker.monitoring
    tracker.update(vehicle_snapshot(101., guard=inspected), 101., policy)
    assert not tracker.update(vehicle_snapshot(102., present=False), 102., policy).completed
    outcomes = tracker.update(vehicle_snapshot(105., present=False), 105., policy).completed
    assert len(outcomes) == 1 and outcomes[0].episode_id == started[0]
    assert outcomes[0].should_alarm is (not inspected)
    assert not tracker.monitoring
    assert not tracker.update(vehicle_snapshot(110., present=False), 110., policy).completed


def test_vehicle_occlusion_closes_at_two_seconds_despite_ten_second_reassociation():
    policy = GuardBehaviorRuntimePolicy(vehicle_occlusion_seconds=2., vehicle_reassociate_seconds=10.)
    tracker = VehicleEpisodeTracker()
    first = tracker.update(vehicle_snapshot(100.), 100., policy).started[0]
    assert not tracker.update(vehicle_snapshot(101.99, present=False), 101.99, policy).completed
    finished = tracker.update(vehicle_snapshot(102., present=False), 102., policy).completed
    assert len(finished) == 1 and finished[0].episode_id == first and finished[0].should_alarm
    assert finished[0].ended_at == 102. and not tracker.monitoring
    assert not tracker.update(vehicle_snapshot(103., present=False), 103., policy).completed


def test_vehicle_return_before_occlusion_deadline_keeps_same_episode():
    policy = GuardBehaviorRuntimePolicy(vehicle_occlusion_seconds=2., vehicle_reassociate_seconds=10.)
    tracker = VehicleEpisodeTracker()
    first = tracker.update(vehicle_snapshot(100.), 100., policy).started[0]
    tracker.update(vehicle_snapshot(101., present=False), 101., policy)
    returned = tracker.update(vehicle_snapshot(101.5), 101.5, policy)
    assert not returned.started and not returned.completed
    finished = tracker.update(vehicle_snapshot(103.5, present=False), 103.5, policy).completed
    assert len(finished) == 1 and finished[0].episode_id == first


@pytest.mark.parametrize("inspected", [False, True])
def test_return_after_occlusion_closes_old_episode_before_association(inspected):
    policy = GuardBehaviorRuntimePolicy(vehicle_occlusion_seconds=2., vehicle_reassociate_seconds=10.)
    tracker = VehicleEpisodeTracker()
    first = tracker.update(vehicle_snapshot(100., guard=inspected), 100., policy).started[0]
    tracker.update(vehicle_snapshot(101., present=False), 101., policy)
    returned = tracker.update(vehicle_snapshot(103.), 103., policy)
    assert len(returned.completed) == len(returned.started) == 1
    assert returned.completed[0].episode_id == first and returned.started[0] != first
    assert returned.completed[0].should_alarm is (not inspected)
    finished = tracker.update(vehicle_snapshot(105., present=False), 105., policy).completed
    assert len(finished) == 1 and finished[0].episode_id == returned.started[0]
    assert finished[0].inspected is inspected and finished[0].should_alarm is (not inspected)


@pytest.mark.parametrize("returned_at,expected_checked", [(109., True), (111., False)])
def test_recent_checked_state_expires_from_last_seen_without_extending_closed_episode(returned_at, expected_checked):
    policy = GuardBehaviorRuntimePolicy(vehicle_occlusion_seconds=2., vehicle_reassociate_seconds=10.)
    tracker = VehicleEpisodeTracker()
    first = tracker.update(vehicle_snapshot(100., guard=True), 100., policy).started[0]
    closed = tracker.update(vehicle_snapshot(102., present=False), 102., policy).completed
    assert len(closed) == 1 and closed[0].episode_id == first and not tracker.monitoring
    returned = tracker.update(vehicle_snapshot(returned_at), returned_at, policy)
    assert len(returned.started) == 1 and returned.started[0] != first and not returned.completed
    finished = tracker.update(vehicle_snapshot(returned_at + 2., present=False), returned_at + 2., policy).completed
    assert len(finished) == 1 and finished[0].inspected is expected_checked
    assert finished[0].should_alarm is (not expected_checked)
    tracker.update(vehicle_snapshot(returned_at + 13., present=False), returned_at + 13., policy)
    assert not tracker._recent_checked


def test_recent_checked_state_is_consumed_once_and_requires_matching_class_and_position():
    policy = GuardBehaviorRuntimePolicy(vehicle_occlusion_seconds=2., vehicle_reassociate_seconds=10.)
    tracker = VehicleEpisodeTracker()
    tracker.update(vehicle_snapshot(100., guard=True), 100., policy)
    tracker.update(vehicle_snapshot(102., present=False), 102., policy)
    vehicles = (VehicleDetection((40., 40., 70., 90.), .9, 3),
                VehicleDetection((0., 0., 20., 20.), .9, 2),
                VehicleDetection((40., 40., 70., 90.), .9, 2),
                VehicleDetection((41., 40., 71., 90.), .9, 2))
    tracker.update(snapshot(now=103., vehicle=VehicleObservation(True, vehicles)), 103., policy)
    finished = tracker.update(vehicle_snapshot(105., present=False), 105., policy).completed
    assert len(finished) == 4
    checked = [outcome for outcome in finished if outcome.inspected]
    assert len(checked) == 1 and checked[0].class_id == 2 and checked[0].first_bbox == vehicles[2].bbox


@pytest.mark.parametrize(("direction", "end_bbox", "expected"), [
    ("right", (52., 40., 82., 90.), True),
    ("left", (52., 40., 82., 90.), False),
    ("down", (40., 45., 70., 95.), True),
    ("up", (40., 35., 70., 85.), True),
    ("right", (41., 40., 71., 90.), False),
])
def test_vehicle_exit_direction_uses_original_frame_normalized_motion(direction, end_bbox, expected):
    policy = GuardBehaviorRuntimePolicy(vehicle_exit_direction=direction, vehicle_direction_min_delta_ratio=.03,
                                        vehicle_reassociate_seconds=0.)
    tracker = VehicleEpisodeTracker()
    tracker.update(vehicle_snapshot(100.), 100., policy)
    tracker.update(vehicle_snapshot(101., bbox=end_bbox), 101., policy)
    outcomes = tracker.update(vehicle_snapshot(104., present=False), 104., policy).completed
    assert len(outcomes) == 1 and outcomes[0].direction_matches is expected
    assert outcomes[0].should_alarm is expected


def test_vehicle_requires_observed_absence_and_cannot_alarm_across_unknown_interval():
    policy = GuardBehaviorRuntimePolicy(vehicle_reassociate_seconds=0.)
    tracker = VehicleEpisodeTracker()
    frame = vehicle_snapshot(100.)
    tracker.update(frame, 100., policy)
    assert not tracker.update(frame, 110., policy).completed
    tracker.mark_unknown()
    outcomes = tracker.update(vehicle_snapshot(111., present=False), 111., policy).completed
    assert len(outcomes) == 1 and outcomes[0].uncertain and not outcomes[0].should_alarm
    assert not tracker.uncertain


def test_two_vehicle_episodes_associate_independently_and_only_nearby_guard_counts():
    policy = GuardBehaviorRuntimePolicy(vehicle_near_px=5., vehicle_reassociate_seconds=0.)
    tracker = VehicleEpisodeTracker()
    vehicles = (VehicleDetection((0., 0., 20., 20.), .7, 2), VehicleDetection((70., 70., 90., 90.), .9, 2))
    observed = snapshot(present=True, guards=(TrackedPerson((22., 0., 30., 20.), .9, 1),),
                        vehicle=VehicleObservation(True, vehicles))
    first = tracker.update(observed, 100., policy)
    assert len(set(first.started)) == 2
    reordered = replace(observed, updated_at=101., vehicle=VehicleObservation(True, tuple(reversed(vehicles))))
    assert not tracker.update(reordered, 101., policy).started
    outcomes = tracker.update(vehicle_snapshot(104., present=False), 104., policy).completed
    assert len(outcomes) == 2
    assert sorted(outcome.should_alarm for outcome in outcomes) == [False, True]
    assert next(outcome for outcome in outcomes if outcome.should_alarm).first_bbox == vehicles[1].bbox


class FakeEvidence:
    def __init__(self):
        self.frames = {}
        self.episodes = {}
        self.cancelled = []
        self.finished = []
        self.sequence = 0

    def should_sample(self, source, now):
        return True

    def record_frame(self, source, frame, timestamp):
        self.frames[source] = frame.copy()

    def begin_episode(self, source, frame, timestamp):
        self.sequence += 1
        token = str(self.sequence)
        self.episodes[token] = source
        return token

    def finish_episode(self, token):
        self.finished.append(token)
        self.episodes.pop(token)
        return f"/fake/{token}.mp4"

    def cancel_episode(self, token):
        self.cancelled.append(token)
        self.episodes.pop(token, None)

    def clear_source(self, source):
        self.frames.pop(source, None)


@pytest.fixture
def runtime():
    configs, reads, requests, now = {1: site_config()}, [], [], [100.]
    online = {f"camera-{index}": True for index in range(1, 10)}
    evidence = FakeEvidence()
    service = SimpleNamespace(
        list_runtime_site_configs=lambda: reads.append("all") or list(configs.values()),
        get_runtime_site_config=lambda site_id: reads.append(site_id) or configs.get(site_id),
    )
    dispatcher = SimpleNamespace(evidence_recorder=evidence,
                                 maybe_dispatch=lambda request, **kwargs: requests.append((request, kwargs)) or True)
    instance = GuardBehaviorSiteRuntime(service=service, dispatcher=dispatcher, evidence_recorder=evidence,
                                        is_camera_active=online.__getitem__, clock=lambda: now[0], start_background=False)
    instance.start()

    def push(value, color=100):
        return instance.update_camera_snapshot(value, np.full((100, 100, 3), color, np.uint8))

    yield SimpleNamespace(instance=instance, configs=configs, reads=reads, requests=requests,
                          evidence=evidence, now=now, push=push, online=online)
    instance.stop()


def test_runtime_aggregates_cached_facts_without_database_reads_per_frame(runtime):
    runtime.configs[1] = site_config(absent_alarm_seconds=2.)
    runtime.instance.reload_site(1)
    for index in (1, 2):
        runtime.push(snapshot(index))
    result = runtime.instance.evaluate_after_camera_update(1)
    assert result.status == "healthy" and result.absence.state == "pending"
    runtime.now[0] = 102.
    assert runtime.instance.evaluate_after_camera_update(1).absence.state == "alarm"
    assert runtime.reads == ["all", 1] and not runtime.requests
    runtime.now[0] = 106.
    result = runtime.instance.evaluate_after_camera_update(1)
    assert result.status == "unavailable" and result.absence.state == "unknown"
    assert set(result.camera_states.values()) == {CameraAvailability.STALE}


@pytest.mark.parametrize("has_snapshot", [False, True])
def test_physical_video_status_is_independent_of_guard_snapshot(runtime, has_snapshot):
    runtime.configs[1] = site_config(count=3)
    runtime.instance.reload_site(1)
    if has_snapshot:
        for camera_id in (1, 2, 3):
            runtime.push(snapshot(camera_id))
    result = runtime.instance.evaluate_after_camera_update(1)
    expected = CameraAvailability.READY if has_snapshot else CameraAvailability.INFERENCE_ERROR
    assert result.camera_states == {camera_id: expected for camera_id in (1, 2, 3)}
    assert runtime.instance.get_camera_online(1) == {1: True, 2: True, 3: True}
    if not has_snapshot:
        assert result.absence.state == "unknown" and not runtime.requests

    # 即使已有 READY 快照，采集链路离线也必须立即使规则不可用。
    runtime.online["camera-2"] = False
    result = runtime.instance.evaluate_after_camera_update(1)
    assert result.camera_states[2] == CameraAvailability.OFFLINE
    assert runtime.instance.get_camera_online(1) == {1: True, 2: False, 3: True}
    assert result.absence.state == "unknown" and not runtime.requests


def test_disabled_site_and_member_do_not_hide_physical_video_status(runtime):
    config = site_config(enabled=False)
    runtime.configs[1] = config.model_copy(update={"members": tuple(
        member.model_copy(update={"member_enabled": False}) for member in config.members)})
    runtime.instance.reload_site(1)
    assert runtime.instance.evaluate_after_camera_update(1).status == "disabled"
    assert runtime.instance.get_camera_online(1) == {1: True, 2: True}


@pytest.mark.parametrize("rule,model", [("phone", "yolo_guard_person_phone"),
                                       ("prone", "yolo_guard_pose"), ("vehicle", "yolo_vehicle")])
@pytest.mark.parametrize("present", [False, True])
def test_subrule_failure_does_not_degrade_core_camera_availability(runtime, rule, model, present):
    runtime.configs[1] = site_config(count=1, absent_alarm_seconds=1., vehicle_inspection_enabled=True,
                                   vehicle_camera_id=1)
    runtime.instance.reload_site(1)
    value = snapshot(present=present, vehicle=VehicleObservation(True))
    changes = {"model_states": {**value.model_states, model: "error"}}
    changes[rule] = VehicleObservation(False, error="模型失败") if rule == "vehicle" else LocalRuleDecision("unknown")
    runtime.push(replace(value, **changes))
    result = runtime.instance.evaluate_after_camera_update(1)
    assert result.status == "healthy" and result.camera_states[1] == CameraAvailability.READY
    assert result.absence.availability == "available"
    assert result.absence.state == ("normal" if present else "pending")
    assert getattr(result, rule).state == "unknown" and getattr(result, rule).availability == "unavailable"
    for other in {"phone", "prone", "vehicle"} - {rule}:
        assert getattr(result, other).availability == "available"
    runtime.now[0] = 101.
    assert runtime.instance.evaluate_after_camera_update(1).absence.state == ("normal" if present else "alarm")


def test_partial_uniform_identity_keeps_presence_ready_but_invalidates_vehicle_negative_evidence(runtime):
    runtime.configs[1] = site_config(count=1, vehicle_inspection_enabled=True, vehicle_camera_id=1)
    runtime.instance.reload_site(1)
    runtime.push(vehicle_snapshot(100.))
    runtime.instance.evaluate_after_camera_update(1)
    partial = vehicle_snapshot(101., guard=True)
    partial = replace(partial, guard_count=None,
                      guards=(TrackedPerson((0., 0., 5., 5.), .9, 1),),
                      model_states={**partial.model_states, "guard_uniform": "error"})
    runtime.now[0] = 101.
    runtime.push(partial)
    assert runtime.evidence.cancelled == ["1"]
    result = runtime.instance.evaluate_after_camera_update(1)
    assert result.camera_states[1] == CameraAvailability.READY and result.absence.state == "normal"
    assert result.vehicle.state == "unknown" and result.vehicle.availability == "unavailable"
    runtime.now[0] = 102.
    runtime.push(vehicle_snapshot(102., present=False))
    assert runtime.instance.evaluate_after_camera_update(1).vehicle.state == "idle"
    assert not runtime.requests and not runtime.evidence.episodes


@pytest.mark.parametrize("rule", ["phone", "prone"])
def test_runtime_positive_alarm_is_site_level_with_highest_confidence_primary(runtime, rule):
    for index, confidence in ((1, .7), (2, .95)):
        runtime.push(snapshot(index, **{rule: LocalRuleDecision("alarm", "异常", confidence)}))
    result = runtime.instance.evaluate_after_camera_update(1)
    decision = getattr(result, rule)
    assert decision.primary_camera_id == 2 and decision.offending_camera_ids == (1, 2)
    runtime.push(snapshot(1, 101., online=False))
    runtime.now[0] = 101.
    result = runtime.instance.evaluate_after_camera_update(1)
    assert result.status == "degraded" and getattr(result, rule).state == "alarm"
    assert result.absence.state == "unknown"


def test_runtime_disabled_unconfigured_members_and_reloads_clear_cached_state(runtime):
    runtime.configs[1] = site_config(enabled=False)
    runtime.instance.reload_site(1)
    assert not runtime.push(snapshot())
    assert runtime.instance.evaluate_after_camera_update(1).status == "disabled"
    runtime.configs[1] = site_config(count=0)
    runtime.instance.reload_site(1)
    assert runtime.instance.evaluate_after_camera_update(1).status == "unconfigured"
    config = site_config()
    runtime.configs[1] = config.model_copy(update={"members": (
        config.members[0], config.members[1].model_copy(update={"member_enabled": False}))})
    runtime.instance.reload_site(1)
    assert runtime.push(snapshot()) and not runtime.push(snapshot(2))
    assert runtime.instance.evaluate_after_camera_update(1).status == "healthy"
    runtime.instance.remove_site(1)
    assert not runtime.instance.sites and not runtime.instance.latest_snapshots and not runtime.instance._frames
    assert runtime.instance.get_site_frame(1) is None


def test_site_composite_orders_members_and_does_not_mutate_single_camera_frames(runtime):
    config = site_config()
    runtime.configs[1] = config.model_copy(update={"members": (
        config.members[0].model_copy(update={"sort_order": 2}), config.members[1].model_copy(update={"sort_order": 1}))})
    runtime.instance.reload_site(1)
    runtime.push(snapshot(1), 30)
    runtime.push(snapshot(2), 200)
    composite = runtime.instance.get_site_frame(1)
    assert composite.shape == (TILE_HEIGHT, 2 * TILE_WIDTH, 3)
    assert tuple(composite[TILE_HEIGHT // 2, TILE_WIDTH // 2]) == (200, 200, 200)
    assert tuple(composite[TILE_HEIGHT // 2, TILE_WIDTH + TILE_WIDTH // 2]) == (30, 30, 30)
    assert np.all(runtime.instance._frames[1] == 30)
    assert np.all(runtime.instance._frames[2] == 200)


def test_vehicle_runtime_uses_one_episode_and_cancels_when_alarm_policy_is_muted(runtime):
    runtime.configs[1] = site_config(count=1, vehicle_inspection_enabled=True, vehicle_camera_id=1,
                                   vehicle_reassociate_seconds=0.)
    runtime.instance.reload_site(1)
    runtime.push(vehicle_snapshot(100.))
    assert runtime.instance.evaluate_after_camera_update(1).vehicle.state == "monitoring"
    assert len(runtime.evidence.episodes) == 1
    runtime.push(vehicle_snapshot(103., present=False))
    runtime.now[0] = 103.
    assert runtime.instance.evaluate_after_camera_update(1).vehicle.state == "alarm"
    assert runtime.evidence.cancelled == ["1"] and not runtime.evidence.episodes
    assert runtime.instance.evaluate_after_camera_update(1).vehicle.state == "idle"
    assert not runtime.requests


def test_runtime_reload_and_stop_cancel_active_episodes_without_stopping_shared_evidence(runtime):
    runtime.configs[1] = site_config(count=1, vehicle_inspection_enabled=True, vehicle_camera_id=1)
    runtime.instance.reload_site(1)
    runtime.push(vehicle_snapshot(100.))
    runtime.instance.evaluate_after_camera_update(1)
    runtime.instance.reload_site(1)
    assert runtime.evidence.cancelled == ["1"] and not runtime.instance.latest_snapshots
    runtime.push(vehicle_snapshot(101.))
    runtime.now[0] = 101.
    runtime.instance.evaluate_after_camera_update(1)
    runtime.instance.stop()
    assert runtime.evidence.cancelled == ["1", "2"] and not runtime.evidence.frames
    runtime.instance.start()
    assert runtime.reads[-1] == "all"


def test_runtime_background_lifecycle_is_repeatable_without_lingering_threads(runtime):
    runtime.instance.stop()
    runtime.instance._start_background = True
    for _ in range(2):
        runtime.instance.start()
        thread = runtime.instance._thread
        assert thread.is_alive()
        runtime.instance.stop()
        assert not thread.is_alive() and runtime.instance._thread is None


def test_runtime_can_be_constructed_before_dispatcher_configure_and_started_afterwards():
    from AiVision.alarms.dispatcher import AlarmDispatcher

    reads, dispatcher, evidence = [], AlarmDispatcher(), FakeEvidence()
    service = SimpleNamespace(list_runtime_site_configs=lambda: reads.append("all") or [])
    instance = GuardBehaviorSiteRuntime(service=service, dispatcher=dispatcher, evidence_recorder=evidence,
                                        is_camera_active=lambda _: True, start_background=False)
    assert not reads and not instance.running and dispatcher._wechat_thread is None
    with pytest.raises(ValueError, match="启动前"):
        instance.start()
    assert not reads and not instance.sites and instance._thread is None
    try:
        dispatcher.configure(horn_runtime_manager=None, wechat=None, violation_writer=None, evidence_recorder=evidence)
        instance.start()
        instance.start()
        assert instance.running and reads == ["all"]
    finally:
        instance.stop()
        dispatcher.stop()


@pytest.mark.parametrize("changed_to", [None, "different"])
def test_start_rechecks_final_evidence_binding_before_reading_configs(changed_to):
    evidence = FakeEvidence()
    dispatcher = SimpleNamespace(evidence_recorder=evidence)
    instance = GuardBehaviorSiteRuntime(service=None, dispatcher=dispatcher, evidence_recorder=evidence, is_camera_active=lambda _: True)
    dispatcher.evidence_recorder = None if changed_to is None else FakeEvidence()
    with pytest.raises(ValueError, match="启动前"):
        instance.start()
    assert not instance.running and instance._thread is None


def test_constructor_still_rejects_different_already_configured_evidence():
    with pytest.raises(ValueError, match="同一个"):
        GuardBehaviorSiteRuntime(service=None, dispatcher=SimpleNamespace(evidence_recorder=FakeEvidence()),
                                 evidence_recorder=FakeEvidence(), is_camera_active=lambda _: True)


def test_registered_guard_request_passes_formal_alarm_validation(runtime):
    config = site_config(count=1)
    policies = tuple(policy.model_copy(update={"sql_enable": True}) for policy in config.alarm_policies)
    runtime.configs[1] = config.model_copy(update={"alarm_policies": policies})
    runtime.instance.reload_site(1)
    runtime.push(snapshot(phone=LocalRuleDecision("alarm", "异常", .9)))
    runtime.instance.evaluate_after_camera_update(1)
    assert len(runtime.requests) == 1
    assert runtime.requests[0][0].violation_type == 9
    from AiVision.features.registry import all_specs
    from AiVision.alarms.types import VIOLATION_TYPE_META
    assert "guard_behavior" in all_specs()
    assert set(VIOLATION_TYPE_META) == set(range(1, 12))


@pytest.fixture
def formal_alarm_catalog():
    from AiVision.alarms.validation import validate_alarm_identity
    for kind in (8, 9, 10, 11):
        validate_alarm_identity(violation_type=kind, feature_name="guard_behavior", department="general_electric")


def enable_alarm_channels(runtime, config):
    policies = tuple(policy.model_copy(update={
        "sql_enable": True, "wechat_enable": True, "wechat_user": "test-user",
        "horn_enable": True, "horn_id": 12, "horn_event_id": 3,
    }) for policy in config.alarm_policies)
    runtime.configs[1] = config.model_copy(update={"alarm_policies": policies})
    runtime.instance.reload_site(1)


@pytest.mark.usefixtures("formal_alarm_catalog")
@pytest.mark.parametrize(("rule", "violation_type"), [("phone", 9), ("prone", 10)])
def test_multiple_positive_cameras_create_one_formal_site_request(runtime, rule, violation_type):
    from AiVision.alarms.dispatcher import AlarmRequest

    enable_alarm_channels(runtime, site_config(count=3))
    for index, confidence, color in ((1, .6, 30), (2, .95, 200)):
        runtime.push(snapshot(index, present=True, **{rule: LocalRuleDecision("alarm", "异常", confidence)}), color)
    result = runtime.instance.evaluate_after_camera_update(1)
    assert result.status == "degraded"
    assert len(runtime.requests) == 1
    request, arguments = runtime.requests[0]
    assert isinstance(request, AlarmRequest)
    assert request.violation_type == violation_type and request.camera_id == 2
    assert request.subject_type == request.cooldown_subject_type == "guard_behavior_site"
    assert request.subject_id == request.cooldown_subject_id == "1" and request.subject_name == "南门"
    assert request.department == "general_electric" and request.camera_key == "camera-2"
    assert request.metadata["primary_camera_id"] == 2
    assert [item["camera_id"] for item in request.metadata["offending_cameras"]] == [1, 2]
    assert request.evidence.source_key == "guard_behavior/camera/2" and request.evidence.mode == "clip"
    assert np.all(request.frame == 200) and request.frame.shape == (100, 100, 3)
    assert arguments == {"alarm_interval": ALARM_INTERVAL_DEFAULTS[violation_type]}
    assert request.alarm_config == {
        "sql": {"enable": True}, "wechat": {"enable": True, "parm": {"user": "test-user"}},
        "horn": {"enable": True, "parm": {"horn_id": 12, "horn_event_id": 3}},
    }


@pytest.mark.usefixtures("formal_alarm_catalog")
def test_absence_alarm_uses_site_composite_for_screenshot_and_common_clip(runtime):
    enable_alarm_channels(runtime, site_config(absent_alarm_seconds=2.))
    runtime.push(snapshot(1), 30)
    runtime.push(snapshot(2), 200)
    runtime.instance.evaluate_after_camera_update(1)
    assert not runtime.requests
    runtime.now[0] = 102.
    runtime.instance.evaluate_after_camera_update(1)
    request, arguments = runtime.requests[0]
    assert request.violation_type == 8 and arguments["alarm_interval"] == ALARM_INTERVAL_DEFAULTS[8]
    assert request.evidence.source_key == "guard_behavior/site/1" and request.evidence.mode == "clip"
    assert np.array_equal(request.frame, runtime.instance.get_site_frame(1))
    assert np.array_equal(runtime.evidence.frames[request.evidence.source_key], request.frame)
    assert [item["camera_id"] for item in request.metadata["offending_cameras"]] == [1, 2]


@pytest.mark.usefixtures("formal_alarm_catalog")
def test_four_guard_alarm_types_have_independent_site_cooldowns(runtime, monkeypatch):
    from AiVision.alarms.dispatcher import AlarmDispatcher

    enable_alarm_channels(runtime, site_config(count=1, absent_alarm_seconds=1., vehicle_inspection_enabled=True,
                                             vehicle_camera_id=1, vehicle_reassociate_seconds=0.))
    dispatcher, executed = AlarmDispatcher(), []
    dispatcher.evidence_recorder = runtime.evidence

    def execute(request):
        executed.append(request)
        if request.evidence.mode == "episode":
            dispatcher._start_evidence(request)

    monkeypatch.setattr(dispatcher, "_execute", execute)
    runtime.instance.dispatcher = dispatcher
    local_alarm = LocalRuleDecision("alarm", "异常", .9)
    runtime.push(replace(vehicle_snapshot(100.), phone=local_alarm, prone=local_alarm))
    runtime.instance.evaluate_after_camera_update(1)
    runtime.now[0] = 101.
    runtime.instance.evaluate_after_camera_update(1)
    runtime.now[0] = 103.
    runtime.push(replace(vehicle_snapshot(103., present=False), phone=local_alarm, prone=local_alarm))
    runtime.instance.evaluate_after_camera_update(1)
    assert sorted(request.violation_type for request in executed) == [8, 9, 10, 11]
    assert dispatcher._last_alarm.keys() == {("guard_behavior_site", "1", kind) for kind in (8, 9, 10, 11)}
    request = next(request for request in executed if request.violation_type == 11)
    assert request.evidence.mode == "episode" and request.evidence.episode_token == "1"
    assert request.metadata["episode"]["inspected"] is False
    assert runtime.evidence.finished == ["1"]
    runtime.instance.evaluate_after_camera_update(1)
    assert len(executed) == 4 and runtime.evidence.finished == ["1"]
    runtime.now[0] = 104.
    runtime.push(vehicle_snapshot(104.))
    runtime.instance.evaluate_after_camera_update(1)
    runtime.now[0] = 107.
    runtime.push(vehicle_snapshot(107., present=False))
    runtime.instance.evaluate_after_camera_update(1)
    assert len(executed) == 4 and runtime.evidence.cancelled == ["2"]
    assert dispatcher.maybe_dispatch(replace(executed[0], subject_id="2", cooldown_subject_id="2"))
    assert len(executed) == 5


@pytest.mark.parametrize("enabled,count", [(False, 2), (True, 0)])
def test_inactive_site_never_evaluates_rules_or_collects_evidence(runtime, monkeypatch, enabled, count):
    import AiVision.features.guard_behavior.runtime as module

    runtime.configs[1] = site_config(enabled=enabled, count=count)
    runtime.instance.reload_site(1)

    def forbidden(*args, **kwargs):
        raise AssertionError("inactive Site must not evaluate")

    monkeypatch.setattr(AbsenceState, "evaluate", forbidden)
    monkeypatch.setattr(module, "aggregate_positive", forbidden)
    monkeypatch.setattr(VehicleEpisodeTracker, "update", forbidden)
    monkeypatch.setattr(runtime.evidence, "record_frame", forbidden)
    result = runtime.instance.evaluate_after_camera_update(1)
    assert result.status == ("disabled" if not enabled else "unconfigured")
    assert not runtime.requests


def test_vehicle_unknown_interval_cancels_evidence_and_prevents_negative_alarm(runtime):
    runtime.configs[1] = site_config(count=1, vehicle_inspection_enabled=True, vehicle_camera_id=1,
                                   vehicle_reassociate_seconds=0.)
    runtime.instance.reload_site(1)
    runtime.push(vehicle_snapshot(100.))
    runtime.instance.evaluate_after_camera_update(1)
    runtime.now[0] = 106.
    assert runtime.instance.evaluate_after_camera_update(1).vehicle.state == "unknown"
    assert runtime.evidence.cancelled == ["1"]
    runtime.push(vehicle_snapshot(106., present=False))
    assert runtime.instance.evaluate_after_camera_update(1).vehicle.state == "idle"
    assert not runtime.requests and not runtime.evidence.episodes


@pytest.mark.usefixtures("formal_alarm_catalog")
def test_dispatch_failure_cannot_leak_evidence_of_an_already_closed_episode(runtime, monkeypatch):
    enable_alarm_channels(runtime, site_config(count=1, vehicle_inspection_enabled=True, vehicle_camera_id=1,
                                             vehicle_reassociate_seconds=0.))
    runtime.push(vehicle_snapshot(100.))
    runtime.instance.evaluate_after_camera_update(1)

    def reject(*args, **kwargs):
        raise RuntimeError("test dispatcher unavailable")

    monkeypatch.setattr(runtime.instance.dispatcher, "maybe_dispatch", reject)
    runtime.push(replace(vehicle_snapshot(103., present=False), phone=LocalRuleDecision("alarm", "异常", .9)))
    runtime.now[0] = 103.
    with pytest.raises(RuntimeError, match="dispatcher unavailable"):
        runtime.instance.evaluate_after_camera_update(1)
    assert not runtime.evidence.episodes and runtime.evidence.cancelled == ["1"]
    assert not runtime.instance.sites[1].episode_tokens


def test_runtime_rejects_old_snapshots_and_preserves_owned_frame_copy(runtime):
    value = snapshot()
    frame = np.full((100, 100, 3), 80, np.uint8)
    assert runtime.instance.update_camera_snapshot(value, frame)
    frame[:] = 0
    value.model_states["guard_uniform"] = "error"
    assert not runtime.push(snapshot(now=99.)) and not runtime.push(snapshot())
    assert np.all(runtime.instance._frames[1] == 80)
    assert runtime.instance.latest_snapshots[1].model_states["guard_uniform"] == "ready"


def test_unknown_snapshot_breaks_negative_evidence_even_before_next_evaluation(runtime):
    runtime.configs[1] = site_config(count=1, absent_alarm_seconds=1., vehicle_inspection_enabled=True,
                                   vehicle_camera_id=1, vehicle_reassociate_seconds=0.)
    runtime.instance.reload_site(1)
    runtime.push(vehicle_snapshot(100.))
    runtime.instance.evaluate_after_camera_update(1)
    runtime.now[0] = 100.2
    runtime.push(replace(vehicle_snapshot(100.2), guard_present=None, guard_count=None))
    assert runtime.instance.sites[1].absence.since is None
    assert runtime.evidence.cancelled == ["1"]
    runtime.now[0] = 100.3
    runtime.push(vehicle_snapshot(100.3))
    result = runtime.instance.evaluate_after_camera_update(1)
    assert result.absence.state == "pending" and result.absence.duration_seconds == 0.
    runtime.now[0] = 103.
    runtime.push(vehicle_snapshot(103., present=False))
    assert runtime.instance.evaluate_after_camera_update(1).vehicle.state == "idle"
    assert not runtime.evidence.episodes


def test_site_runtime_has_no_inference_capture_database_or_notification_dependencies():
    import ast
    from pathlib import Path

    root = Path(__file__).parents[1]
    for name in ("runtime.py", "site_rules.py", "vehicle_episode.py"):
        tree = ast.parse((root / "features/guard_behavior" / name).read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(part in name for name in imports for part in (
            "integrations", "inference", "tracking", "ultralytics", "torch", "sqlalchemy", "notifications", "records"))
        calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)}
        assert not calls.intersection({"dispatch_inference_sync", "VideoCapture", "VideoWriter", "get_session", "track"})
    public = (root / "alarms/evidence/evidence_recorder.py").read_text()
    assert "guard_behavior" not in public
