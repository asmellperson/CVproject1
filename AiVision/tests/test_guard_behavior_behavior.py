"""固定时间输入验证局部行为，不依赖旧实现、视频源或模型。"""
from dataclasses import replace

import pytest

from AiVision.features.guard_behavior.behavior import LocalBehaviorState
from AiVision.features.guard_behavior.pose_features import extract_pose_features, match_pose_features
from AiVision.features.guard_behavior.schema import GuardBehaviorRuntimePolicy
from AiVision.features.guard_behavior.state import GuardTrackMemory, PhoneDetection, TrackedPerson


PERSON = TrackedPerson((100., 100., 200., 300.), .9, 1)
PHONE = PhoneDetection((145., 135., 155., 150.), .9)


def pose_points():
    points = [[0., 0., .9] for _ in range(17)]
    points[0] = [150., 210., .9]
    points[5] = [125., 150., .9]
    points[6] = [175., 150., .9]
    return points


def evaluate(engine, now, *, persons=None, phones=None, features=None, pose_available=True,
             phone_failed_tracks=None, policy=None, identity_unknown=False):
    return engine.update(
        now=now, fps=2., frame_height=400, guards=[PERSON] if persons is None else persons,
        phones=[] if phones is None else phones,
        phone_failed_tracks=phone_failed_tracks or set(),
        pose_features={1: {"head_down_ratio": .3, "nose_x": .5, "nose_y": .55}} if features is None else features,
        pose_available=pose_available, identity_unknown=identity_unknown,
        policy=policy or GuardBehaviorRuntimePolicy(),
    )


def test_pose_best_iou_and_strict_match_threshold():
    pose = {"bbox": PERSON.bbox, "keypoints": pose_points()}
    distant = {"bbox": (600., 100., 700., 300.), "keypoints": pose_points()}
    assert match_pose_features([PERSON], [distant]) == {}
    best = match_pose_features([PERSON], [distant, pose])[1]
    assert best == {"nose_x": .5, "nose_y": .55, "shoulder_y": .25,
                    "head_down_ratio": pytest.approx(.3), "shoulder_span": .5, "person_h": 200.}
    threshold = {"bbox": (100., 100., 130., 300.), "keypoints": pose_points()}
    assert match_pose_features([PERSON], [threshold]) == {}
    assert match_pose_features([replace(PERSON, track_id=None)], [pose]) == {}


def test_pose_core_confidence_and_malformed_points():
    points = pose_points()
    points[5][2] = .29
    assert extract_pose_features(PERSON, points) is None
    with pytest.raises(ValueError, match="17"):
        extract_pose_features(PERSON, points[:16])
    points[5][0] = float("nan")
    with pytest.raises(ValueError, match="有限"):
        extract_pose_features(PERSON, points)


def test_uniform_probability_cache_hold_and_ttl():
    first, second = GuardTrackMemory(), GuardTrackMemory()
    for memory in (first, second):
        memory.observe([PERSON], 0., 2.)
    first.remember(1, .9, 0.)
    assert first.cached_probability(1, .05) == .9
    assert first.cached_probability(1, .11) is None
    assert second.cached_probability(1, .05) is None
    assert first.keep(1, True, 0., 1.3)
    assert first.keep(1, False, 1.3, 1.3)
    assert not first.keep(1, False, 1.31, 1.3)
    assert first.keep(None, True, 0., 1.3)
    assert not first.keep(None, False, .1, 1.3)
    first.observe([], 2.1, 2.)
    assert not first.tracks


def test_phone_window_min_hits_duration_and_grace():
    engine = LocalBehaviorState()
    policy = GuardBehaviorRuntimePolicy(phone_min_hits_in_window=2, phone_window_seconds=.6,
                                         phone_seconds=1., phone_grace_seconds=1.)
    assert evaluate(engine, 0., phones=[PHONE], policy=policy)[0].state == "pending"
    assert evaluate(engine, .5, phones=[PHONE], policy=policy)[0].state == "pending"
    result = evaluate(engine, 1., phones=[PHONE], policy=policy)[0]
    assert result.state == "alarm" and result.duration_seconds == 1.
    assert evaluate(engine, 1.8, policy=policy)[0].state == "pending"
    assert evaluate(engine, 2.1, policy=policy)[0].state == "normal"
    assert engine.person_states[1].phone_active_seconds == 0
    assert not engine.person_states[1].phone_hit_ts


def test_phone_spatial_filter_rejects_low_distant_objects():
    engine = LocalBehaviorState()
    phone = PhoneDetection((500., 350., 510., 365.), .95)
    assert evaluate(engine, 1., phones=[phone])[0].state == "normal"
    assert not engine.person_states[1].phone_hit_ts


def test_prone_consecutive_motion_soft_decay_and_duration():
    engine = LocalBehaviorState()
    policy = GuardBehaviorRuntimePolicy(prone_consecutive_frames=2, prone_sleep_seconds=1.,
                                         prone_bbox_height_ratio_threshold=.1)
    normal_features = {1: {"head_down_ratio": 0., "nose_x": .5, "nose_y": .1}}
    assert evaluate(engine, 0., features=normal_features, policy=policy)[1].state == "normal"
    assert evaluate(engine, .5, policy=policy)[1].state == "pending"
    assert evaluate(engine, 1., policy=policy)[1].duration_seconds == .5
    result = evaluate(engine, 1.5, policy=policy)[1]
    assert result.state == "alarm" and result.duration_seconds == 1.
    moved = replace(PERSON, bbox=(200., 100., 300., 300.))
    assert evaluate(engine, 2., persons=[moved], features=normal_features, policy=policy)[1].state == "pending"
    assert evaluate(engine, 2.5, persons=[moved], features=normal_features, policy=policy)[1].state == "normal"


def test_unknown_resets_evidence_without_affecting_other_camera_or_rule():
    first, second = LocalBehaviorState(), LocalBehaviorState()
    policy = GuardBehaviorRuntimePolicy(phone_min_hits_in_window=1, phone_seconds=.5)
    evaluate(first, 0., phones=[PHONE], policy=policy)
    phone, prone = evaluate(first, 1., phones=[PHONE], policy=policy, pose_available=False)
    assert phone.state == "alarm" and prone.state == "unknown"
    assert not second.person_states
    assert first.person_states[1].prone_frames == 0
    phone, _ = evaluate(first, 2., phone_failed_tracks={1}, policy=policy)
    assert phone.state == "unknown" and first.person_states[1].phone_active_seconds == 0
    first.mark_unknown(3., policy.state_ttl_seconds)
    assert first.person_states[1].last_phone_eval_ts is None
    evaluate(first, 30., persons=[], policy=policy)
    assert not first.person_states


def test_no_guard_and_unknown_identity_never_produce_local_alarm():
    engine = LocalBehaviorState()
    assert all(rule.state == "normal" for rule in evaluate(engine, 1., persons=[]))
    assert all(rule.state == "unknown" for rule in evaluate(engine, 2., persons=[], identity_unknown=True))
    untracked = replace(PERSON, track_id=None)
    assert all(rule.state == "unknown" for rule in evaluate(engine, 3., persons=[untracked], phones=[PHONE]))
    assert not engine.person_states
