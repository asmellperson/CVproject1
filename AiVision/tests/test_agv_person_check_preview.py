"""AGV 标注预览与普通检测 ROI 一致，待机取图不触发推理的回归验证。"""
from concurrent.futures import ThreadPoolExecutor
import threading
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest


@pytest.fixture
def agv(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "tests", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "tests", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.features._shared import consumer as base
    from AiVision.features.agv_person_check import preview
    from AiVision.features.agv_person_check.consumer import AgvPersonCheckConsumer
    from AiVision.features.agv_person_check.spec import SPEC

    config = {"enable": True, "camera_enable": True, "shm_name": "camera_1",
              "roi_pos": [[.25, .25], [.75, .25], [.75, .75], [.25, .75]]}
    configs = {1: config}
    monkeypatch.setattr(base, "config_cache", SimpleNamespace(
        get_function_config=lambda camera_id, feature: configs.get(camera_id),
        get_all_function_configs=lambda: {(camera_id, SPEC.name): cfg for camera_id, cfg in configs.items()},
    ))
    consumer = AgvPersonCheckConsumer(
        spec=SPEC, infer_dict={}, result_queue=Queue(), latest_frames={}, is_camera_active=lambda key: True,
    )
    consumer._load_initial_configs()
    consumer.running = True
    consumer.dispatch_inference_sync = Mock(side_effect=AssertionError("预览不应触发推理"))
    yield SimpleNamespace(consumer=consumer, configs=configs, base=base, preview=preview)
    consumer.stop()


@pytest.mark.parametrize("shape", [(80, 160), (160, 80), (120, 120)])
def test_idle_preview_draws_saved_roi_like_other_features_on_current_frame(agv, shape):
    consumer = agv.consumer
    raw = np.full((*shape, 3), 40, dtype=np.uint8)
    consumer.frame_cache[1] = raw
    expected = agv.base.BaseFunctionConsumer._annotated_frame(consumer, 1)
    consumer.frame_cache[1] = np.full_like(raw, 5)
    consumer.result_dict["camera_1"] = np.full_like(raw, 7)
    result = consumer.get_live_preview("camera_1", raw, now=1000.)
    assert np.array_equal(result, expected)
    assert result[shape[0] // 4, shape[1] // 4].tolist() == list(consumer.ROI_COLOR)
    assert result[shape[0] // 2, shape[1] // 2].tolist() == [40, 40, 40]
    assert np.all(raw == 40)
    assert np.all(consumer.frame_cache[1] == 5)
    consumer.dispatch_inference_sync.assert_not_called()
    assert consumer.service.detecting_camera_ids() == set()


def test_consumer_stop_preserves_processing_until_response_releases_request(agv, monkeypatch):
    from AiVision.features.agv_person_check.schema import AgvPersonCheckValueSchema, PersonCheckResult

    consumer = agv.consumer
    request = consumer.service.submit(1, "camera_1", AgvPersonCheckValueSchema(
        http={"present_value": 1, "absent_value": 0},
    ).model_dump())
    stopping = threading.Event()
    begin = consumer.service.begin_shutdown

    def begin_shutdown(timeout):
        pending = begin(timeout)
        stopping.set()
        return pending

    monkeypatch.setattr(consumer.service, "begin_shutdown", begin_shutdown)
    with ThreadPoolExecutor(max_workers=1) as executor:
        stopped = executor.submit(consumer.stop)
        try:
            assert stopping.wait(2)
            assert consumer.running
            assert not request.future.done()
            request.future.set_result(PersonCheckResult(person_present=False))
            assert not stopped.done(), "判定结束还不能停止，须等回传释放请求"
        finally:
            consumer.service.release(request)
        stopped.result(timeout=2)
    assert not consumer.running
    assert request.error is None


def test_empty_roi_draws_full_frame_with_visible_final_pixel(agv):
    agv.configs[1] = {**agv.configs[1], "roi_pos": []}
    agv.consumer.update_config(1)
    raw = np.zeros((80, 160, 3), dtype=np.uint8)
    result = agv.consumer.get_live_preview("camera_1", raw, now=1000.)
    assert result[0, 0].tolist() == list(agv.consumer.ROI_COLOR)
    assert result[-1, -1].tolist() == list(agv.consumer.ROI_COLOR)
    assert result[40, 80].tolist() == [0, 0, 0]


def test_saved_roi_change_replaces_previous_outline_without_waiting_for_a_request(agv):
    agv.configs[1] = {**agv.configs[1], "roi_pos": [[.1, .1], [.9, .1], [.9, .9], [.1, .9]]}
    agv.consumer.update_config(1)
    result = agv.consumer.get_live_preview("camera_1", np.zeros((80, 160, 3), dtype=np.uint8), now=1000.)
    assert result[8, 16].tolist() == list(agv.consumer.ROI_COLOR)
    assert result[20, 40].tolist() == [0, 0, 0]
    agv.consumer.dispatch_inference_sync.assert_not_called()


@pytest.mark.parametrize("state", ["unbound", "camera_disabled", "stopped", "offline", "removed"])
def test_inactive_or_removed_camera_has_no_preview(agv, state):
    if state == "unbound":
        agv.consumer.update_status(1, False)
    elif state == "camera_disabled":
        agv.configs[1] = {**agv.configs[1], "camera_enable": False}
        agv.consumer.update_config(1)
    elif state == "stopped":
        agv.consumer.stop()
    elif state == "offline":
        agv.consumer.is_camera_active = lambda key: False
    else:
        agv.consumer.remove_camera(1)
    assert agv.consumer.get_live_preview("camera_1", np.zeros((80, 160, 3), dtype=np.uint8), now=1000.) is None
    assert agv.consumer.get_live_preview("camera_2", np.zeros((80, 160, 3), dtype=np.uint8), now=1000.) is None


def test_preview_does_not_wait_for_the_sampling_inference_lock(agv):
    executor = ThreadPoolExecutor(max_workers=1)
    agv.consumer._camera_state_lock.acquire()
    try:
        future = executor.submit(agv.consumer.get_live_preview, "camera_1", np.zeros((80, 160, 3), dtype=np.uint8), now=1000.)
        assert future.result(timeout=1.) is not None
    finally:
        agv.consumer._camera_state_lock.release()
        executor.shutdown(wait=True)


def test_roi_replaced_during_render_cannot_publish_old_outline(agv, monkeypatch):
    draw = agv.preview.annotate_roi

    def replace(*args):
        result = draw(*args)
        agv.consumer.update_status(1, False)
        return result

    monkeypatch.setattr(agv.preview, "annotate_roi", replace)
    assert agv.consumer.get_live_preview("camera_1", np.zeros((80, 160, 3), dtype=np.uint8), now=1000.) is None


@pytest.fixture
def orchestrator(agv, monkeypatch):
    from AiVision.runtime import orchestrator as module

    raw = np.full((80, 160, 3), 40, dtype=np.uint8)
    registry = SimpleNamespace(latest_frames={"camera_1": raw}, latest_frame_times={"camera_1": 999.})
    monkeypatch.setattr(module, "frame_reader_registry", registry)
    monkeypatch.setattr(module.time, "time", lambda: 1000.)
    runtime = module.Orchestrator.__new__(module.Orchestrator)
    runtime.consumers = {"agv_person_check": agv.consumer}
    return SimpleNamespace(runtime=runtime, registry=registry, raw=raw)


def test_shared_frame_entry_returns_live_agv_roi_and_unannotated_editor_frame(agv, orchestrator):
    result, updated_at = orchestrator.runtime.get_camera_frame_info("camera_1", feature="agv_person_check")
    assert updated_at == 1000.
    assert result[20, 40].tolist() == list(agv.consumer.ROI_COLOR)
    editor_frame, updated_at = orchestrator.runtime.get_camera_frame_info("camera_1")
    assert editor_frame is orchestrator.raw
    assert updated_at == 999.


def test_shared_frame_entry_rejects_stale_source_frame(orchestrator):
    orchestrator.registry.latest_frame_times["camera_1"] = 989.
    result, _ = orchestrator.runtime.get_camera_frame_info("camera_1", feature="agv_person_check")
    assert result is None


@pytest.mark.parametrize("capture_metadata, expected_age_ms", [
    (None, None), ((None, 999.), None), ((7, None), None),
    ((0, 999.), None), ((7, 0.), None), ((7, float("nan")), None),
    ((7, 999.), 1000.), ((7, 1001.), 0.),
])
def test_platform_frame_response_contains_roi_in_resized_jpeg(
    agv, orchestrator, monkeypatch, capture_metadata, expected_age_ms,
):
    from AiVision.api.routes import cameras
    from AiVision.cameras.frame_reader import FrameReaderRegistry

    registry = FrameReaderRegistry()
    if capture_metadata is not None:
        sequence, updated_at = capture_metadata
        if sequence is not None:
            registry.latest_frame_seq["camera_1"] = sequence
        if updated_at is not None:
            registry.latest_frame_times["camera_1"] = updated_at
    monkeypatch.setattr(cameras, "frame_reader_registry", registry)

    response = cameras.build_camera_frame_response(
        key="camera_1", feature="agv_person_check", quality=95,
        max_width=80, max_height=None, orchestrator=orchestrator.runtime,
    )
    image = cv2.imdecode(np.frombuffer(response.body, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert response.media_type == "image/jpeg"
    assert image.shape == (40, 80, 3)
    assert int(image[10, 20, 0]) - int(image[10, 20, 2]) > 70
    assert np.all(orchestrator.raw == 40)
    agv.consumer.dispatch_inference_sync.assert_not_called()
    timings = {
        name: float(duration.removeprefix("dur="))
        for name, duration in (
            entry.strip().split(";") for entry in response.headers["server-timing"].split(",")
        )
    }
    assert set(timings) == {"frame_lookup", "jpeg_encode", "frame_total"}
    assert all(duration >= 0 for duration in timings.values())
    assert timings["frame_total"] >= max(timings["frame_lookup"], timings["jpeg_encode"])
    if expected_age_ms is not None:
        assert response.headers["x-capture-sequence"] == "7"
        assert float(response.headers["x-capture-updated-at"]) == capture_metadata[1]
        assert float(response.headers["x-capture-age-ms"]) == expected_age_ms
    else:
        assert "x-capture-sequence" not in response.headers
        assert "x-capture-updated-at" not in response.headers
        assert "x-capture-age-ms" not in response.headers
