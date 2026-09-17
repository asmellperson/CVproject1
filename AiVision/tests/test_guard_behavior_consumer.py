"""单摄感知合同测试，模型调用与跟踪输出使用可控输入。"""
from dataclasses import asdict
import json
import queue
from types import SimpleNamespace

import numpy as np
import pytest

from AiVision.features.guard_behavior import consumer as module
from AiVision.features.guard_behavior.consumer import GuardBehaviorConsumer
from AiVision.features.guard_behavior.schema import GuardBehaviorRuntimeCameraConfig, GuardBehaviorRuntimePolicy
from AiVision.features.guard_behavior.spec import SPEC
from AiVision.features.guard_behavior.site_rules import camera_availability
from AiVision.features.guard_behavior.state import CameraAvailability, TrackedPerson


def runtime_config(camera_id=1, **policy):
    return GuardBehaviorRuntimeCameraConfig(
        camera_id=camera_id, camera_name=f"Camera {camera_id}", shm_name=f"cam-{camera_id}", fps=10.,
        department="general_electric", site_id=1, site_name="Site", site_enabled=True,
        member_enabled=True, feature_enabled=True, vehicle_roi_pos=(),
        policy=GuardBehaviorRuntimePolicy(**policy),
    )


def detection(kind="person", bbox=(200., 200., 400., 600.), confidence=.9, **kwargs):
    return {"type": kind, "bbox": list(bbox), "confidence": confidence, **kwargs}


@pytest.fixture
def consumer(monkeypatch):
    configs = {index: runtime_config(index) for index in (1, 2)}
    reads = []
    provider = SimpleNamespace(
        list_runtime_camera_configs=lambda: reads.append("all") or list(configs.values()),
        get_runtime_camera_config=lambda camera_id: reads.append(camera_id) or configs.get(camera_id),
    )
    available = {name: True for name in SPEC.model_names}
    available[module.POSE_MODEL] = False
    now = [100.]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])
    instance = GuardBehaviorConsumer(
        spec=SPEC, infer_dict={}, result_queue=queue.Queue(), latest_frames={}, is_camera_active=lambda _: True,
        guard_config_provider=provider, model_running_provider=available.__getitem__,
    )
    instance._load_initial_configs()
    calls, outputs = [], {}

    def infer(camera_id, model_name, roi, task_meta=None, timeout=.8):
        stage = model_name
        if model_name == module.PERSON_MODEL:
            stage = "person" if roi.shape == (1000, 1000, 3) else "phone"
        calls.append((camera_id, stage, roi.shape, task_meta))
        value = outputs.get(stage, [{"type": "uniform", "confidence": .9}] if stage == module.UNIFORM_MODEL else [])
        if callable(value):
            value = value(camera_id)
        return value if isinstance(value, dict) else {"status": "ok", "detections": value}

    # 感知规则测试只控制跟踪结果；真实 BYTETracker 的隔离由独立测试覆盖。
    def tracked(items, camera_id, frame, config):
        persons = [item for item in items if item["type"] == "person"]
        return [TrackedPerson(module._box(item), module._confidence(item), index + 1)
                for index, item in enumerate(persons)]

    monkeypatch.setattr(instance, "dispatch_inference_sync", infer)
    monkeypatch.setattr(instance, "_persons", tracked)
    context = SimpleNamespace(consumer=instance, configs=configs, reads=reads, calls=calls, outputs=outputs,
                              available=available, now=now, frame=np.zeros((1000, 1000, 3), dtype=np.uint8))

    def process(camera_id=1):
        result = instance._process(context.frame, camera_id)
        assert result[0] is False
        instance.post_process(camera_id, result)
        return instance.latest_snapshots[camera_id], result[1]

    context.process = process
    yield context
    instance.stop()


def test_empty_person_success_is_explicit_absence_without_uniform_call(consumer):
    snapshot, _ = consumer.process()
    assert snapshot.guard_present is False and snapshot.guard_count == 0
    assert snapshot.phone.state == "normal"
    assert not any(call[1] == module.UNIFORM_MODEL for call in consumer.calls)


@pytest.mark.parametrize("status", ["error", "timeout", "dropped", "unavailable"])
def test_person_failure_is_unknown(consumer, status):
    consumer.outputs["person"] = {"status": status, "detections": []}
    snapshot, _ = consumer.process()
    assert snapshot.guard_present is None and snapshot.guard_count is None
    assert snapshot.phone.state == snapshot.prone.state == "unknown"
    assert not any(call[1] == module.UNIFORM_MODEL for call in consumer.calls)


@pytest.mark.parametrize(("probability", "expected"), [(.8, True), (.79, False)])
def test_uniform_threshold_and_expanded_crop(consumer, probability, expected):
    consumer.outputs["person"] = [detection()]
    consumer.outputs[module.UNIFORM_MODEL] = [{"type": "uniform", "confidence": probability}]
    snapshot, _ = consumer.process()
    assert snapshot.guard_present is expected and snapshot.guard_count == int(expected)
    assert next(call[2] for call in consumer.calls if call[1] == module.UNIFORM_MODEL) == (480, 240, 3)
    assert consumer.calls[0][3] == {"conf": .25, "iou": .45, "imgsz": 960}


@pytest.mark.parametrize("positive", [False, True])
def test_partial_uniform_failure_preserves_unknown_or_known_positive(consumer, positive):
    consumer.outputs["person"] = [detection(), detection(bbox=(600., 200., 800., 600.))]
    values = iter(([{"type": "uniform", "confidence": .95}] if positive else {"status": "error"},
                   {"status": "timeout"}))
    consumer.outputs[module.UNIFORM_MODEL] = lambda _: next(values)
    snapshot, _ = consumer.process()
    assert snapshot.guard_present is (True if positive else None)
    assert snapshot.guard_count is None
    assert snapshot.model_states[module.UNIFORM_MODEL] == "error"
    assert camera_availability(SimpleNamespace(physical_enabled=True), snapshot, snapshot.updated_at, 5.) == (
        CameraAvailability.READY if positive else CameraAvailability.INFERENCE_ERROR)


def test_uniform_cache_is_per_camera_and_hold_expires(consumer):
    consumer.outputs["person"] = [detection()]
    consumer.process(1)
    consumer.now[0] += .05
    consumer.process(1)
    consumer.process(2)
    assert len([call for call in consumer.calls if call[1] == module.UNIFORM_MODEL]) == 2
    consumer.outputs[module.UNIFORM_MODEL] = [{"type": "uniform", "confidence": .1}]
    consumer.now[0] = 100.5
    assert consumer.process(1)[0].guard_present is True
    consumer.now[0] = 101.5
    assert consumer.process(1)[0].guard_present is False
    consumer.now[0] = 125.
    consumer.outputs["person"] = []
    consumer.process(1)
    assert consumer.consumer._guard_memories[1].tracks == {}
    assert consumer.consumer._behaviors[1].person_states == {}


def test_phone_crop_offsets_filter_and_dedup_ignore_full_frame_phone(consumer):
    consumer.outputs["person"] = [detection(), detection("phone", (10., 10., 20., 20.))]
    consumer.outputs["phone"] = [
        detection("phone", (120., 180., 135., 210.), .9),
        detection("phone", (121., 181., 136., 211.), .8),
        detection("phone", (0., 0., 110., 150.), .99),
    ]
    snapshot, result = consumer.process()
    assert snapshot.guard_present is True
    assert len(result.phones) == 1
    assert result.phones[0].bbox == (250., 300., 265., 330.)
    call = next(call for call in consumer.calls if call[1] == "phone")
    assert call[2] == (540, 340, 3)
    assert call[3] == {"conf": .35, "iou": .45, "imgsz": 640}
    assert snapshot.prone.state == "unknown" and snapshot.phone.state == "pending"


def test_phone_inference_failure_does_not_destroy_guard_presence(consumer):
    consumer.outputs["person"] = [detection()]
    consumer.outputs["phone"] = {"status": "timeout"}
    snapshot, _ = consumer.process()
    assert snapshot.guard_present is True and snapshot.phone.state == "unknown"
    assert snapshot.model_states[module.PERSON_MODEL] == "error"
    assert camera_availability(SimpleNamespace(physical_enabled=True), snapshot, snapshot.updated_at, 5.) == (
        CameraAvailability.READY)


def test_pose_uses_own_default_conf_and_full_frame(consumer):
    consumer.available[module.POSE_MODEL] = True
    consumer.outputs["person"] = [detection()]
    points = [[0., 0., .9] for _ in range(17)]
    points[0], points[5], points[6] = [300., 450., .9], [240., 300., .9], [360., 300., .9]
    consumer.outputs[module.POSE_MODEL] = [detection("pose", keypoints=points)]
    snapshot, _ = consumer.process()
    assert snapshot.prone.state == "pending"
    call = next(call for call in consumer.calls if call[1] == module.POSE_MODEL)
    assert call[2] == consumer.frame.shape and call[3] == {"iou": .45, "imgsz": 640}
    consumer.outputs[module.POSE_MODEL] = {"status": "error"}
    consumer.now[0] += 1
    snapshot, _ = consumer.process()
    assert snapshot.prone.state == "unknown" and snapshot.guard_present is True
    assert camera_availability(SimpleNamespace(physical_enabled=True), snapshot, snapshot.updated_at, 5.) == (
        CameraAvailability.READY)


@pytest.mark.parametrize("designated", [None, 2])
def test_vehicle_disabled_or_other_camera_does_not_infer(consumer, designated):
    if designated:
        consumer.configs[1] = runtime_config(vehicle_inspection_enabled=True, vehicle_camera_id=designated)
        consumer.consumer.reload_camera_config(1)
    snapshot, _ = consumer.process()
    assert not snapshot.vehicle.available
    assert snapshot.model_states[module.VEHICLE_MODEL] == "not_applicable"
    assert not any(call[1] == module.VEHICLE_MODEL for call in consumer.calls)


def test_vehicle_optional_unavailable_and_normalized_bottom_center_roi(consumer):
    config = runtime_config(vehicle_inspection_enabled=True, vehicle_camera_id=1)
    config = config.model_copy(update={"vehicle_roi_pos": ((.1, .5), (.9, .5), (.9, .9), (.1, .9))})
    consumer.configs[1] = config
    consumer.consumer.reload_camera_config(1)
    consumer.available[module.VEHICLE_MODEL] = False
    snapshot, _ = consumer.process()
    assert not snapshot.vehicle.available and snapshot.guard_present is False
    assert snapshot.model_states[module.VEHICLE_MODEL] == "unavailable"
    assert camera_availability(SimpleNamespace(physical_enabled=True), snapshot, snapshot.updated_at, 5.) == (
        CameraAvailability.READY)
    consumer.available[module.VEHICLE_MODEL] = True
    consumer.outputs[module.VEHICLE_MODEL] = [
        detection("vehicle", (200., 100., 400., 600.), class_id=2),
        detection("vehicle", (200., 100., 400., 300.), class_id=3),
    ]
    snapshot, _ = consumer.process()
    assert snapshot.vehicle.available and len(snapshot.vehicle.detections) == 1
    assert snapshot.vehicle.detections[0].class_id == 2
    call = next(call for call in consumer.calls if call[1] == module.VEHICLE_MODEL)
    assert call[3] == {"conf": .35, "iou": .45, "imgsz": 960}
    assert call[2] == consumer.frame.shape


def test_snapshot_plain_data_preview_sink_and_no_alarm_dispatch(consumer, monkeypatch):
    from AiVision.features._shared import consumer as base_module

    def forbidden(*args, **kwargs):
        pytest.fail("Guard 单摄层不得调用报警分发或冷却")

    monkeypatch.setattr(base_module.alarm_dispatcher, "maybe_dispatch", forbidden)
    monkeypatch.setattr(base_module.alarm_dispatcher, "reset_cooldown", forbidden)
    sink = []
    consumer.consumer.snapshot_sink = lambda snapshot, frame: sink.append((snapshot, frame))
    consumer.outputs["person"] = [detection()]
    snapshot, _ = consumer.process()
    assert json.loads(json.dumps(asdict(snapshot)))["camera_id"] == 1
    assert sink[0][0] is snapshot
    assert sink[0][1] is consumer.consumer.result_dict["cam-1"]
    assert not np.shares_memory(sink[0][1], consumer.frame)
    assert set(snapshot.model_states) == set(SPEC.model_names)
    consumer.consumer._handle_alarm(1, (True, {}), consumer.frame)
    consumer.consumer.update_config(1)
    consumer.consumer.update_status(1, False)
    consumer.consumer.update_status(1, True)
    consumer.consumer.remove_camera(1)


def test_configuration_is_cached_full_frame_and_camera_clear_is_complete(consumer):
    instance = consumer.consumer
    consumer.outputs["person"] = [detection()]
    consumer.process(1)
    consumer.process(2)
    assert consumer.reads == ["all"]
    assert instance._get_roi(1, consumer.frame) is consumer.frame
    assert instance._process_static_frames(1, {})
    assert instance._processing_interval_seconds(1, {}) == .1
    instance._trackers[1] = object()
    instance.update_status(1, False)
    for cache in (instance._trackers, instance._guard_memories, instance._behaviors,
                  instance.latest_snapshots, instance._runtime_configs, instance.frame_cache):
        assert 1 not in cache
    assert "cam-1" not in instance.result_dict
    assert 2 in instance.latest_snapshots
    consumer.configs[1] = runtime_config(cap_interval=.5)
    instance.reload_camera_config(1)
    assert instance._processing_interval_seconds(1, {}) == .5
    assert "policy" not in instance.config_cache[1]


def test_consumer_start_stop_uses_router_and_reloads_once(consumer):
    instance = consumer.consumer
    for _ in range(2):
        instance.start()
        thread = instance._thread
        assert thread.is_alive()
        instance.stop()
        assert not thread.is_alive() and not instance.latest_snapshots
        assert not instance.config_cache
    assert consumer.reads == ["all", "all", "all"]


def test_crops_clip_to_real_frame_bounds_and_reject_empty():
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    crop, offset = module._crop(frame, (0., 0., 120., 100.), horizontal=.35, top=.20, bottom=.15)
    assert offset == (0, 0) and crop.shape == frame.shape
    with pytest.raises(ValueError, match="越界或为空"):
        module._crop(frame, (200., 200., 300., 300.), horizontal=.1, top=.1, bottom=.1)


@pytest.mark.parametrize("probability", [float("nan"), 1.1, -.1])
def test_malformed_uniform_probability_is_unknown_and_observable(consumer, probability):
    consumer.outputs["person"] = [detection()]
    consumer.outputs[module.UNIFORM_MODEL] = [{"type": "uniform", "confidence": probability}]
    snapshot, _ = consumer.process()
    assert snapshot.guard_present is None
    assert snapshot.model_states[module.UNIFORM_MODEL] == "error"
    status = consumer.consumer.inference_status()
    assert status["totals"]["error"] == 1


def test_explicit_reload_disables_inactive_members_and_clears_old_snapshot(consumer):
    instance = consumer.consumer
    consumer.process()
    consumer.configs[1] = consumer.configs[1].model_copy(update={"member_enabled": False})
    instance.reload_camera_config(1)
    assert 1 not in instance.config_cache and 1 not in instance.latest_snapshots
    consumer.configs.pop(2)
    instance.reload_camera_config(2)
    assert 2 not in instance.config_cache


def test_static_frames_and_changed_frames_obey_site_interval(consumer, monkeypatch):
    instance = consumer.consumer
    monkeypatch.setattr(module, "time", lambda: 50.)
    instance._last_process_at[1] = 49.95
    assert not instance._should_process_now(1, {})
    instance._last_process_at[1] = 49.8
    assert instance._should_process_now(1, {})


def test_vehicle_inference_error_does_not_change_guard_state(consumer):
    consumer.configs[1] = runtime_config(vehicle_inspection_enabled=True, vehicle_camera_id=1)
    consumer.consumer.reload_camera_config(1)
    consumer.outputs[module.VEHICLE_MODEL] = {"status": "error"}
    snapshot, _ = consumer.process()
    assert snapshot.guard_present is False
    assert not snapshot.vehicle.available and snapshot.vehicle.error
    assert snapshot.model_states[module.VEHICLE_MODEL] == "error"


def tracker_person(x=20.):
    return {"bbox": (x, 20., x + 60., 180.), "confidence": .9}


@pytest.mark.parametrize("package_name", ["ultralytics", "lap"])
def test_bytetrack_installed_versions_match_declared_pins(package_name):
    import importlib
    from importlib.metadata import version
    from pathlib import Path
    import sys
    from packaging.requirements import Requirement

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        # Python 3.10 使用 pytest 已声明的 tomli 依赖读取同一份 TOML。
        import tomli as tomllib

    path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
    requirements = {item.name: item for item in map(Requirement, project["dependencies"])}
    installed = importlib.import_module(package_name).__version__
    assert installed == version(package_name)
    assert installed in requirements[package_name].specifier
    assert str(requirements[package_name].specifier) == f"=={installed}"


@pytest.mark.parametrize("lap_state", ["missing", "missing_version", "empty_version"])
def test_bytetrack_rejects_unusable_lap_before_upstream_auto_install(monkeypatch, lap_state):
    import builtins
    import subprocess
    from AiVision.features.guard_behavior import tracking

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "lap":
            if lap_state == "missing":
                raise ModuleNotFoundError("lap")
            return SimpleNamespace() if lap_state == "missing_version" else SimpleNamespace(__version__="")
        if name == "ultralytics" or name.startswith("ultralytics."):
            pytest.fail("无有效 lap 时必须在上游导入及自动安装之前失败")
        return original_import(name, *args, **kwargs)

    def forbidden_process(*args, **kwargs):
        pytest.fail("运行时不得启动 pip 或其他依赖安装进程")

    # 强制走首次构造，不能让已缓存的 Tracker 类型绕过依赖检查。
    tracking._tracker_types.cache_clear()
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(subprocess, "Popen", forbidden_process)
    try:
        with pytest.raises(RuntimeError, match="禁止运行时下载安装"):
            tracking.CameraByteTracker(10.)
    finally:
        tracking._tracker_types.cache_clear()


def test_real_bytetrack_ids_are_stable_and_independent_across_cameras(monkeypatch):
    from AiVision.features.guard_behavior.tracking import CameraByteTracker
    from ultralytics.trackers.basetrack import BaseTrack

    monkeypatch.setattr(BaseTrack, "_count", 700)
    first = CameraByteTracker(10.)
    assert [person.track_id for person in first.update([tracker_person(), tracker_person(300.)], (1000, 1000, 3))] == [1, 2]
    # 在 A 已有轨迹之后创建 B，不能清零 A 的分配器。
    second = CameraByteTracker(10.)
    assert [person.track_id for person in second.update([tracker_person()], (1000, 1000, 3))] == [1]
    assert [person.track_id for person in first.update([tracker_person(300.), tracker_person()], (1000, 1000, 3))] == [2, 1]
    first.update([tracker_person(), tracker_person(300.), tracker_person(600.)], (1000, 1000, 3))
    assert [person.track_id for person in first.update(
        [tracker_person(), tracker_person(300.), tracker_person(600.)], (1000, 1000, 3))] == [1, 2, 3]
    first.reset()
    assert [person.track_id for person in first.update([tracker_person()], (1000, 1000, 3))] == [1]
    second.update([tracker_person(), tracker_person(300.)], (1000, 1000, 3))
    assert [person.track_id for person in second.update([tracker_person(), tracker_person(300.)], (1000, 1000, 3))] == [1, 2]
    assert BaseTrack._count == 700


def test_real_bytetrack_parallel_construction_and_allocation_are_local():
    import threading
    from AiVision.features.guard_behavior.tracking import CameraByteTracker

    barrier = threading.Barrier(2)
    outcomes = queue.Queue()

    def run():
        try:
            tracker = CameraByteTracker(10.)
            barrier.wait(timeout=5)
            persons = tracker.update([tracker_person(), tracker_person(300.)], (1000, 1000, 3))
            outcomes.put([person.track_id for person in persons])
        except Exception as exc:
            outcomes.put(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert outcomes.get_nowait() == outcomes.get_nowait() == [1, 2]


def test_matching_lost_reassociation_and_removal_use_official_bytetrack():
    from AiVision.features.guard_behavior.tracking import CameraByteTracker
    from ultralytics.trackers.byte_tracker import BYTETracker, STrack
    from ultralytics.trackers.basetrack import TrackState

    wrapper = CameraByteTracker(10.)
    tracker = wrapper.tracker
    assert isinstance(tracker, BYTETracker)
    for name in ("update", "reset", "get_kalmanfilter", "get_dists", "multi_predict",
                 "joint_stracks", "sub_stracks", "remove_duplicate_stracks"):
        assert getattr(type(tracker), name) is getattr(BYTETracker, name)
    assert wrapper.update([tracker_person()], (1000, 1000, 3))[0].track_id == 1
    track = tracker.tracked_stracks[0]
    for name in ("activate", "re_activate", "update", "predict", "multi_predict"):
        assert getattr(type(track), name) is getattr(STrack, name)
    assert wrapper.update([], (1000, 1000, 3)) == []
    assert track.state == TrackState.Lost and track in tracker.lost_stracks
    assert wrapper.update([tracker_person()], (1000, 1000, 3))[0].track_id == 1
    assert tracker.tracked_stracks[0] is track
    for _ in range(tracker.max_frames_lost + 2):
        wrapper.update([], (1000, 1000, 3))
    assert track.state == TrackState.Removed and track in tracker.removed_stracks
    wrapper.update([tracker_person(600.)], (1000, 1000, 3))
    assert wrapper.update([tracker_person(600.)], (1000, 1000, 3))[0].track_id == 2


def test_consumer_real_tracking_clear_affects_only_current_camera(consumer, monkeypatch):
    instance = consumer.consumer
    monkeypatch.setattr(instance, "_persons", GuardBehaviorConsumer._persons.__get__(instance))
    consumer.outputs["person"] = [detection()]
    assert consumer.process(1)[1].persons[0].track_id == 1
    assert consumer.process(2)[1].persons[0].track_id == 1
    second = instance._trackers[2]
    instance.remove_camera(1)
    assert 1 not in instance._trackers and instance._trackers[2] is second
    assert consumer.process(2)[1].persons[0].track_id == 1
    instance.reload_camera_config(1)
    assert consumer.process(1)[1].persons[0].track_id == 1


def test_unconfirmed_tracks_remain_visible_without_shared_temporal_identity(consumer, monkeypatch):
    instance = consumer.consumer
    monkeypatch.setattr(instance, "_persons", GuardBehaviorConsumer._persons.__get__(instance))
    assert consumer.process()[0].guard_present is False
    consumer.outputs["person"] = [detection()]
    snapshot, detail = consumer.process()
    assert detail.persons[0].track_id is None
    assert snapshot.guard_present is True and snapshot.phone.state == "unknown"
    assert not instance._guard_memories[1].tracks
    assert not instance._behaviors[1].person_states
    assert consumer.process()[1].persons[0].track_id == 1


def test_consumer_snapshot_reaches_site_runtime_and_formal_dispatcher(consumer, monkeypatch):
    from AiVision.alarms.dispatcher import AlarmDispatcher
    from AiVision.features.guard_behavior.runtime import GuardBehaviorSiteRuntime
    from test_guard_behavior_runtime import FakeEvidence, site_config

    config = site_config(absent_alarm_seconds=1.)
    config = config.model_copy(update={"alarm_policies": tuple(
        policy.model_copy(update={"sql_enable": True}) for policy in config.alarm_policies)})
    evidence, dispatcher, requests = FakeEvidence(), AlarmDispatcher(), []
    dispatcher.evidence_recorder = evidence
    monkeypatch.setattr(dispatcher, "_execute", requests.append)
    monkeypatch.setattr(module, "time", lambda: consumer.now[0])
    runtime = GuardBehaviorSiteRuntime(
        service=SimpleNamespace(list_runtime_site_configs=lambda: [config]),
        dispatcher=dispatcher, evidence_recorder=evidence,
        clock=lambda: consumer.now[0], start_background=False,
    )
    runtime.start()
    consumer.consumer.snapshot_sink = runtime.update_camera_snapshot
    try:
        consumer.process(1)
        consumer.process(2)
        assert runtime.evaluate_after_camera_update(1).absence.state == "pending"
        assert not requests
        consumer.now[0] += 1.
        assert runtime.evaluate_after_camera_update(1).absence.state == "alarm"
        assert len(requests) == 1
        request = requests[0]
        assert request.violation_type == 8 and request.feature_name == "guard_behavior"
        assert request.subject_type == request.cooldown_subject_type == "guard_behavior_site"
        assert request.evidence.source_key == "guard_behavior/site/1"
    finally:
        consumer.consumer.snapshot_sink = None
        runtime.stop()


def test_missing_packaged_tracker_configuration_fails_explicitly(monkeypatch, tmp_path):
    import ultralytics
    from AiVision.features.guard_behavior.tracking import CameraByteTracker

    monkeypatch.setattr(ultralytics, "__file__", str(tmp_path / "__init__.py"))
    with pytest.raises(RuntimeError, match="默认配置不存在"):
        CameraByteTracker(10.)


def test_consumer_processing_thread_routes_real_queue_results_into_snapshot(consumer, monkeypatch):
    import threading
    from AiVision.features._shared.consumer import BaseFunctionConsumer
    from AiVision.inference.contracts import build_inference_result

    instance = consumer.consumer
    instance.infer_dict = {name: queue.Queue() for name in SPEC.model_names}
    instance.latest_frames["cam-1"] = consumer.frame
    monkeypatch.setattr(instance, "dispatch_inference_sync", BaseFunctionConsumer.dispatch_inference_sync.__get__(instance))
    monkeypatch.setattr(instance, "_persons", GuardBehaviorConsumer._persons.__get__(instance))
    completed, stop_worker = threading.Event(), threading.Event()
    requests, failures = [], []
    instance.snapshot_sink = lambda *_: completed.set()

    def model_results():
        try:
            while not stop_worker.is_set():
                for name, tasks in instance.infer_dict.items():
                    try:
                        task = tasks.get(timeout=.01)
                    except queue.Empty:
                        continue
                    requests.append(task)
                    if name == module.UNIFORM_MODEL:
                        detections = [{"type": "uniform", "confidence": .95}]
                    elif task["frame"].shape == consumer.frame.shape:
                        detections = [detection()]
                    else:
                        detections = []
                    instance.result_queue.put(build_inference_result(task, status="ok", detections=detections))
        except Exception as exc:
            failures.append(exc)
            completed.set()

    worker = threading.Thread(target=model_results)
    worker.start()
    try:
        instance.start()
        assert completed.wait(timeout=5), "单摄处理线程未发布快照"
        assert not failures
        assert instance.latest_snapshots[1].guard_present is True
        assert instance.latest_snapshots[1].prone.state == "unknown"
        assert "cam-1" in instance.result_dict
        assert {task["model_name"] for task in requests} == {module.PERSON_MODEL, module.UNIFORM_MODEL}
        assert len({task["request_id"] for task in requests}) == len(requests)
        assert all(task["function_name"] == "guard_behavior" and task["camera_id"] == 1 for task in requests)
    finally:
        instance.stop()
        stop_worker.set()
        worker.join(timeout=3)
    assert not worker.is_alive() and instance._thread is None
