"""慢推理不能冻结监控视频，检测框不能残留在不对应的视频画面。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest


NOW = 1000.0
OLD_BOX = [20, 30, 40, 70]
NEW_BOX = [80, 30, 100, 70]
GREEN = (60, 200, 80)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "tests", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "tests", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)


def image_with_person(box, background):
    frame = np.full((96, 128, 3), background, dtype=np.uint8)
    x1, y1, x2, y2 = box
    frame[y1:y2, x1:x2] = 255
    frame.setflags(write=False)
    return frame


@pytest.fixture(params=["fence", "tailgating"])
def preview(request):
    kwargs = {"infer_dict": {}, "result_queue": Queue(), "latest_frames": {}, "is_camera_active": lambda key: True}
    if request.param == "fence":
        from AiVision.features.security_fence.consumer import FenceConsumer
        from AiVision.features.security_fence.runtime import current_mode
        from AiVision.features.security_fence.schema import FenceValue

        value = FenceValue()
        consumer = FenceConsumer(spec=SimpleNamespace(name="security_fence", alarm_types=()), **kwargs)

        def configure(camera_id, cfg):
            consumer.preview.configure(camera_id, cfg)

        def detail(box):
            return {"persons": [{"bbox": list(box), "track_id": 1, "identity": "allowed", "alarm": False}],
                    "faces": [], "mode": current_mode(value, datetime.fromtimestamp(NOW, timezone.utc)),
                    "frame_width": 128, "frame_height": 96, "updated_at_s": NOW}
    else:
        from AiVision.features.tailgating.consumer import TailgatingConsumer
        from AiVision.features.tailgating.schema import TailgatingValue

        value = TailgatingValue(roi_pos=[[0, 0], [1, 0], [1, 1], [0, 1]])
        consumer = TailgatingConsumer(spec=SimpleNamespace(name="tailgating", alarm_types=()), **kwargs)

        def configure(camera_id, cfg):
            consumer._configure_camera(camera_id)

        def detail(box):
            return {"persons": [{"bbox": list(box), "track_id": 1}], "events": [], "reason": "clear",
                    "frame_width": 128, "frame_height": 96, "updated_at_s": NOW}

    def setup(camera_id=1):
        cfg = {**value.model_dump(), "enable": True, "camera_enable": True, "shm_name": f"camera_{camera_id}"}
        consumer.config_cache[camera_id] = cfg
        configure(camera_id, cfg)

    def publish(frame, *, camera_id=1, sampled_at=NOW - .1, box=OLD_BOX, result=None):
        consumer.frame_cache[camera_id] = frame
        consumer._last_process_at[camera_id] = sampled_at
        return consumer.post_process(camera_id, (False, result if result is not None else detail(box)))

    setup()
    return SimpleNamespace(consumer=consumer, setup=setup, publish=publish, detail=detail, kind=request.param)


def test_moving_person_boxes_use_detection_source_instead_of_newer_video_frame(preview):
    source = image_with_person(OLD_BOX, 20)
    live = image_with_person(NEW_BOX, 80)
    evidence = preview.publish(source)
    rendered = preview.consumer.get_live_preview("camera_1", live, now=NOW)
    assert np.array_equal(rendered, evidence)
    assert rendered[50, 30].tolist() == [255, 255, 255]
    assert rendered[50, 90].tolist() == [20, 20, 20]
    assert rendered[50, 20].tolist() == list(GREEN)
    assert source[50, 20].tolist() == [255, 255, 255]
    assert live[50, 20].tolist() == [80, 80, 80]


@pytest.mark.parametrize("sample_age", [.31, .8, 3.0, -1.0])
def test_late_inference_or_invalid_sample_clock_cannot_make_old_boxes_fresh(preview, sample_age):
    source = image_with_person(OLD_BOX, 20)
    live = image_with_person(NEW_BOX, 80)
    # 结果刚完成，但原图已经过期；证据保留原图，监控撤销过期的空间标注。
    evidence = preview.publish(source, sampled_at=NOW - sample_age)
    rendered = preview.consumer.get_live_preview("camera_1", live, now=NOW)
    assert evidence[50, 20].tolist() == list(GREEN)
    assert rendered[50, 20].tolist() == [80, 80, 80]
    assert rendered[50, 90].tolist() == [255, 255, 255]


def test_slow_detection_keeps_live_video_moving_without_clearing_business_status(preview):
    evidence = preview.publish(image_with_person(OLD_BOX, 20), sampled_at=NOW - .8)
    status = preview.consumer.get_monitor_status("camera_1")
    for offset, background in enumerate([60, 80, 100, 120]):
        live = image_with_person(NEW_BOX, background)
        rendered = preview.consumer.get_live_preview("camera_1", live, now=NOW + offset * .2)
        assert rendered[50, 20].tolist() == [background] * 3
        assert rendered[50, 90].tolist() == [255] * 3
        assert np.all(live[50, 20] == background)
    assert evidence[50, 20].tolist() == list(GREEN)
    assert preview.consumer.get_monitor_status("camera_1") == status


def test_new_empty_observation_removes_previous_boxes_without_waiting_for_track_ttl(preview):
    source = image_with_person(OLD_BOX, 20)
    preview.publish(source)
    empty = np.full_like(source, 80)
    result = preview.detail(OLD_BOX)
    result["persons"] = []
    preview.publish(empty, result=result)
    rendered = preview.consumer.get_live_preview("camera_1", empty, now=NOW)
    assert rendered[50, 20].tolist() == [80, 80, 80]
    assert rendered[50, 30].tolist() == [80, 80, 80]


def test_resolution_or_configuration_change_clears_spatial_annotations(preview):
    preview.publish(image_with_person(OLD_BOX, 20))
    resized = np.full((120, 160, 3), 80, dtype=np.uint8)
    assert preview.consumer.get_live_preview("camera_1", resized, now=NOW)[50, 20].tolist() == [80, 80, 80]
    preview.setup()
    live = image_with_person(NEW_BOX, 80)
    assert preview.consumer.get_live_preview("camera_1", live, now=NOW)[50, 20].tolist() == [80, 80, 80]


def test_camera_sources_are_isolated_and_new_result_replaces_old_coordinates(preview):
    preview.setup(2)
    preview.publish(image_with_person(OLD_BOX, 20))
    preview.publish(image_with_person(NEW_BOX, 80), camera_id=2, box=NEW_BOX)
    live = image_with_person(NEW_BOX, 100)
    first = preview.consumer.get_live_preview("camera_1", live, now=NOW)
    second = preview.consumer.get_live_preview("camera_2", live, now=NOW)
    assert first[50, 20].tolist() == list(GREEN)
    assert second[50, 20].tolist() == [80, 80, 80]
    assert second[50, 80].tolist() == list(GREEN)
    preview.publish(live, box=NEW_BOX)
    updated = preview.consumer.get_live_preview("camera_1", live, now=NOW)
    assert updated[50, 20].tolist() == [100, 100, 100]
    assert updated[50, 80].tolist() == list(GREEN)


@pytest.mark.parametrize("feature", ["person_dwell", "face_dwell"])
@pytest.mark.parametrize("alarmed", [False, True])
def test_dwell_lost_tracks_remain_matchable_but_are_never_drawn(feature, alarmed):
    from AiVision.features._shared.dwell_consumer import DwellObservationClock
    from AiVision.features._shared.tracking import IouTracker
    from AiVision.features.face_dwell.consumer import FaceConsumer
    from AiVision.features.person_dwell.consumer import HumanConsumer

    cls = HumanConsumer if feature == "person_dwell" else FaceConsumer
    consumer = cls(spec=SimpleNamespace(name=feature, alarm_types=()), infer_dict={}, result_queue=Queue(),
                   latest_frames={}, is_camera_active=lambda key: True)
    consumer.config_cache[1] = {"shm_name": "camera_1", "roi_pos": [], "MAX_TIME": 10}
    consumer.frame_cache[1] = image_with_person(NEW_BOX, 80)
    consumer._observation_clocks[1] = DwellObservationClock(valid=True)
    tracker = consumer._trackers[1] = IouTracker(max_lost=5)
    tracks = tracker.update([{"bbox": OLD_BOX}], now=0)
    old_id = next(iter(tracks))
    tracks[old_id].alarmed = alarmed
    tracks = tracker.update([{"bbox": NEW_BOX}], now=1)
    assert tracks[old_id].lost == 1
    rendered = consumer.post_process(1, (False, None))
    assert rendered[50, 20].tolist() == [80, 80, 80]
    assert rendered[50, 80].tolist() == list(consumer.BBOX_COLOR_NORMAL)
    assert consumer.monitor_status["camera_1"]["count"] == 1
    # 重连容忍仍保留，避免为了清理残影重置轨迹编号和停留计时。
    tracker.update([{"bbox": OLD_BOX}], now=2)
    assert tracker.tracks[old_id].lost == 0
    assert tracker.tracks[old_id].alarmed is alarmed


@pytest.fixture
def common_preview(monkeypatch):
    from AiVision.features._shared.consumer import BaseFunctionConsumer

    class Consumer(BaseFunctionConsumer):
        def _process(self, roi, camera_id):
            return False, None

        def post_process(self, camera_id, result):
            import cv2

            frame = self._annotated_frame(camera_id)
            cv2.rectangle(frame, tuple(OLD_BOX[:2]), tuple(OLD_BOX[2:]), GREEN, 2)
            return frame

    source = image_with_person(OLD_BOX, 20)
    consumer = Consumer(
        spec=SimpleNamespace(name="test_preview", alarm_types=()), infer_dict={}, result_queue=Queue(),
        latest_frames={"camera_1": source}, latest_frame_times={"camera_1": NOW - .1},
        is_camera_active=lambda _: True,
    )
    consumer.config_cache[1] = {
        "enable": True, "camera_enable": True, "shm_name": "camera_1", "cap_interval": .1,
        "roi_pos": [[.1, .1], [.9, .1], [.9, .9], [.1, .9]],
    }
    consumer._handle_alarm = Mock()
    monkeypatch.setattr(consumer, "_after_process", lambda *_: setattr(consumer, "running", False))
    monkeypatch.setattr("AiVision.features._shared.consumer.time.time", lambda: NOW)

    def publish():
        consumer.running = True
        consumer._run()
        consumer.running = True

    publish()
    yield SimpleNamespace(consumer=consumer, publish=publish, source=source)
    consumer.running = False


def test_common_preview_keeps_matched_fresh_boxes_and_drops_slow_result_without_freezing(common_preview):
    consumer = common_preview.consumer
    live = image_with_person(NEW_BOX, 80)
    fresh = consumer.get_live_preview("camera_1", live, now=NOW)
    assert fresh is consumer.result_dict["camera_1"]
    assert fresh[50, 20].tolist() == list(GREEN)
    for index, background in enumerate([60, 80, 100, 120]):
        current = image_with_person(NEW_BOX, background)
        result = consumer.get_live_preview("camera_1", current, now=NOW + .4 + index * .2)
        assert result[50, 20].tolist() == [background] * 3
        assert result[50, 90].tolist() == [255] * 3
        assert result[10, 13].tolist() == list(consumer.ROI_COLOR)
    assert consumer.result_dict["camera_1"][50, 20].tolist() == list(GREEN)
    consumer._handle_alarm.assert_called_once()
    assert consumer._handle_alarm.call_args.args[2] is fresh
    assert common_preview.source[50, 20].tolist() == [255] * 3


@pytest.mark.parametrize("source_age", [.8, 3., -1.])
def test_common_preview_age_counts_capture_and_inference_wait(common_preview, source_age):
    consumer = common_preview.consumer
    consumer.latest_frame_times["camera_1"] = NOW - source_age
    consumer.frame_change_samples.clear()
    common_preview.publish()
    # 刚完成的结果不能把等待或过时的输入图重新标成当前画面。
    assert consumer.result_updated_at["camera_1"] == NOW
    live = image_with_person(NEW_BOX, 80)
    result = consumer.get_live_preview("camera_1", live, now=NOW)
    assert result[50, 20].tolist() == [80] * 3
    assert result[50, 90].tolist() == [255] * 3


def test_common_preview_does_not_wait_for_inference_lock(common_preview):
    consumer = common_preview.consumer
    live = image_with_person(NEW_BOX, 80)
    with ThreadPoolExecutor(max_workers=1) as executor:
        consumer._camera_state_lock.acquire()
        try:
            future = executor.submit(consumer.get_live_preview, "camera_1", live, now=NOW + .8)
            assert future.result(timeout=1.)[50, 90].tolist() == [255] * 3
        finally:
            consumer._camera_state_lock.release()


@pytest.mark.parametrize("state", ["disabled", "camera_disabled", "removed", "stopped", "changed", "resized"])
def test_common_preview_rejects_old_config_and_inactive_camera(common_preview, state):
    consumer = common_preview.consumer
    live = image_with_person(NEW_BOX, 80)
    if state == "disabled":
        consumer.config_cache[1] = {**consumer.config_cache[1], "enable": False}
    elif state == "camera_disabled":
        consumer.config_cache[1] = {**consumer.config_cache[1], "camera_enable": False}
    elif state == "removed":
        consumer.config_cache.pop(1)
    elif state == "stopped":
        consumer.running = False
    elif state == "changed":
        consumer.config_cache[1] = {**consumer.config_cache[1], "roi_pos": []}
    else:
        live = np.full((120, 160, 3), 80, np.uint8)
    result = consumer.get_live_preview("camera_1", live, now=NOW)
    if state in {"changed", "resized"}:
        assert result[50, 20].tolist() == [80] * 3
        assert result.shape == live.shape
    else:
        assert result is None
    assert consumer.get_live_preview("camera_other", live, now=NOW) is None


def test_common_config_replaced_during_render_cannot_return_old_roi(common_preview, monkeypatch):
    from AiVision.features._shared import consumer as module

    consumer = common_preview.consumer
    draw = module.annotate_roi

    def replace(*args):
        rendered = draw(*args)
        consumer.config_cache[1] = {**consumer.config_cache[1], "roi_pos": []}
        return rendered

    monkeypatch.setattr(module, "annotate_roi", replace)
    assert consumer.get_live_preview("camera_1", image_with_person(NEW_BOX, 80), now=NOW + .8) is None


def test_orchestrator_common_preview_advances_with_video_when_detection_is_slow(common_preview, monkeypatch):
    from AiVision.runtime import orchestrator as module

    consumer = common_preview.consumer
    runtime = module.Orchestrator.__new__(module.Orchestrator)
    runtime.consumers = {"test_preview": consumer}
    registry = SimpleNamespace(latest_frames={}, latest_frame_times={})
    monkeypatch.setattr(module, "frame_reader_registry", registry)
    for background in [60, 80, 100]:
        registry.latest_frames["camera_1"] = image_with_person(NEW_BOX, background)
        registry.latest_frame_times["camera_1"] = NOW - .01
        # 检测采样时间比当前时刻早 0.8 秒，但业务处理状态仍保持不变。
        monkeypatch.setattr(module.time, "time", lambda: NOW + .8)
        frame, _ = runtime.get_camera_frame_info("camera_1", feature="test_preview")
        assert frame[50, 20].tolist() == [background] * 3
        assert frame[50, 90].tolist() == [255] * 3


def test_logistics_monitor_uses_live_tiles_and_preserves_detection_evidence(monkeypatch):
    from AiVision.features.logistics_channel.constants import LOGISTICS_FEATURES
    from AiVision.features.logistics_channel.runtime import LogisticsChannelRuntime
    from AiVision.features.logistics_channel.state import CameraSnapshot

    feature = next(iter(LOGISTICS_FEATURES))
    raw = {"camera_1": np.full((96, 128, 3), 60, np.uint8)}
    snapshot = CameraSnapshot(1, count=2, updated_at=NOW - .8)
    detected = np.full((96, 128, 3), 20, np.uint8)
    runtime = LogisticsChannelRuntime(
        preview_frame_provider=lambda name, key: raw[key], clock_provider=lambda: NOW,
        start_background=False,
    )
    channel = SimpleNamespace(feature_name=feature, channel_id=1,
                              cameras=(SimpleNamespace(camera_id=1, shm_name="camera_1", name="camera"),))
    runtime._loaded_features.add(feature)
    runtime._channels[(feature, 1)] = channel
    runtime._snapshots[(feature, 1)] = snapshot
    runtime._frames[(feature, 1)] = detected
    monkeypatch.setattr(runtime, "_channel_is_active", lambda _: True)
    monkeypatch.setattr(runtime, "_camera_online", lambda _: True)
    monkeypatch.setattr(runtime, "_compose", lambda cfg, tiles: tiles[0].frame)
    for background in [60, 80, 100]:
        raw["camera_1"] = np.full_like(detected, background)
        monitor = runtime.get_channel_frame(feature, 1)
        assert np.all(monitor == background)
    evidence = runtime._snapshot_channel(feature, 1)
    assert np.all(evidence.frames[0] == 20)
    assert runtime._snapshots[(feature, 1)] is snapshot
    assert runtime._frames[(feature, 1)] is detected


def guard_configs():
    from AiVision.features.guard_behavior.constants import ALARM_INTERVAL_DEFAULTS, GUARD_ALARM_TYPES
    from AiVision.features.guard_behavior.schema import (
        GuardBehaviorRuntimeAlarmPolicy, GuardBehaviorRuntimeCameraConfig,
        GuardBehaviorRuntimeMember, GuardBehaviorRuntimePolicy,
        GuardBehaviorRuntimeSiteConfig,
    )

    policy = GuardBehaviorRuntimePolicy()
    camera = GuardBehaviorRuntimeCameraConfig(
        camera_id=1, camera_name="camera", shm_name="camera_1", fps=5,
        department="general_electric", site_id=1, site_name="site", site_enabled=True,
        member_enabled=True, feature_enabled=True,
        vehicle_roi_pos=((.25, .25), (.75, .25), (.75, .75), (.25, .75)), policy=policy,
    )
    site = GuardBehaviorRuntimeSiteConfig(
        site_id=1, site_name="site", department="general_electric", enabled=True,
        policy=policy, alarm_policies=tuple(GuardBehaviorRuntimeAlarmPolicy(
            violation_type=kind, alarm_interval=ALARM_INTERVAL_DEFAULTS[kind],
        ) for kind in GUARD_ALARM_TYPES), members=(GuardBehaviorRuntimeMember(
            camera_id=1, camera_name="camera", shm_name="camera_1", member_enabled=True,
            physical_enabled=True, feature_enabled=True, sort_order=1,
        ),),
    )
    return camera, site


def test_guard_monitor_mosaic_keeps_live_video_while_evidence_keeps_original_frame():
    from AiVision.features.guard_behavior.runtime import GuardBehaviorSiteRuntime, SiteRuntimeState

    _, site = guard_configs()
    raw = {"camera_1": np.full((360, 640, 3), 60, np.uint8)}
    recorder = Mock()
    runtime = GuardBehaviorSiteRuntime(
        service=Mock(), dispatcher=SimpleNamespace(evidence_recorder=recorder), evidence_recorder=recorder,
        is_camera_active=lambda _: True, start_background=False, clock=lambda: NOW,
        preview_frame_provider=lambda key: raw[key],
    )
    runtime.sites[1] = SiteRuntimeState(site)
    runtime._frames[1] = np.full((360, 640, 3), 20, np.uint8)
    for background in [60, 80, 100]:
        raw["camera_1"] = np.full((360, 640, 3), background, np.uint8)
        monitor = runtime.get_site_frame(1)
        assert monitor[150, 150].tolist() == [background] * 3
    evidence = runtime.get_site_frame(1, live_preview=False)
    assert evidence[150, 150].tolist() == [20] * 3
    assert np.all(runtime._frames[1] == 20)


def test_guard_live_background_keeps_vehicle_roi_without_requiring_model_results():
    from AiVision.features.guard_behavior.consumer import GuardBehaviorConsumer

    config, _ = guard_configs()
    consumer = GuardBehaviorConsumer(
        spec=SimpleNamespace(name="guard_behavior", alarm_types=()), infer_dict={}, result_queue=Queue(),
        latest_frames={}, is_camera_active=lambda _: True,
        guard_config_provider=Mock(), model_running_provider=lambda _: True,
    )
    consumer._install_config(1, config)
    consumer.running = True
    raw = np.full((96, 128, 3), 80, np.uint8)
    rendered = consumer.get_live_preview("camera_1", raw, now=NOW)
    assert rendered[24, 32].tolist() == list(consumer.ROI_COLOR)
    assert rendered[50, 50].tolist() == [80] * 3
    assert np.all(raw == 80)
