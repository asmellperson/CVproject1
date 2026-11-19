"""保安室多路调度与感知证据配对回归，使用本地队列代替模型。"""
from queue import Queue
from threading import Event
from time import time
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture
def make_consumer(monkeypatch, tmp_path):
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "test",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path), "AUTH_SECRET": "test-guard-signing-key-0000000000",
    }.items():
        monkeypatch.setenv(key, value)
    from AiVision.features.guard_behavior import consumer as module
    from AiVision.features.guard_behavior.schema import GuardBehaviorRuntimeCameraConfig, GuardBehaviorRuntimePolicy
    from AiVision.features.guard_behavior.spec import SPEC
    from AiVision.features.guard_behavior.state import TrackedPerson

    def persons(items, camera_id, frame, config):
        return [TrackedPerson(tuple(item["bbox"]), item["confidence"], 1) for item in items]

    instances = []

    def make(count, *, vehicle=False, start_thread=False):
        configs = {camera_id: GuardBehaviorRuntimeCameraConfig(
            camera_id=camera_id, camera_name=f"测试摄像头{camera_id}", shm_name=f"camera_{camera_id}",
            fps=10., department="general_electric", site_id=1, site_name="测试保安室",
            site_enabled=True, member_enabled=True, feature_enabled=True, vehicle_roi_pos=(),
            policy=GuardBehaviorRuntimePolicy(
                cap_interval=.1, vehicle_inspection_enabled=vehicle, vehicle_camera_id=1 if vehicle else None,
            ),
        ) for camera_id in range(1, count + 1)}
        frames = {config.shm_name: np.full((80, 80, 3), camera_id, dtype=np.uint8)
                  for camera_id, config in configs.items()}
        snapshots, published = [], Event()

        def receive(snapshot, annotated):
            snapshots.append((snapshot, annotated))
            published.set()

        consumer = module.GuardBehaviorConsumer(
            spec=SPEC, infer_dict={name: Queue() for name in SPEC.model_names}, result_queue=Queue(),
            latest_frames=frames, latest_frame_times={key: time() - .01 for key in frames},
            is_camera_active=lambda key: True, model_running_provider=lambda name: True,
            guard_config_provider=SimpleNamespace(
                list_runtime_camera_configs=lambda: list(configs.values()), get_runtime_camera_config=configs.get,
            ), snapshot_sink=receive,
        )
        monkeypatch.setattr(consumer, "_persons", persons)
        instances.append(consumer)
        if start_thread:
            consumer.start()
        else:
            consumer._load_initial_configs()
            consumer.running = True
            consumer.result_router.start()
        return consumer, snapshots, published

    yield make
    for consumer in instances:
        consumer.stop()


def complete(consumer, task, detections):
    from AiVision.inference.contracts import build_inference_result

    request = consumer._pending_samples[task["camera_id"]].request
    consumer.result_queue.put(build_inference_result(task, status="ok", detections=detections))
    assert request.pending.event.wait(1)


def test_live_consumer_rotates_past_pending_camera(make_consumer):
    consumer, snapshots, published = make_consumer(4, start_thread=True)
    queue = consumer.infer_dict["yolo_guard_person_phone"]
    first, second = queue.get(timeout=1.), queue.get(timeout=1.)
    assert (first["camera_id"], second["camera_id"]) == (1, 2)
    assert queue.empty()

    complete(consumer, second, [])

    assert published.wait(1)
    assert snapshots[0][0].camera_id == 2
    assert snapshots[0][0].guard_present is False
    assert queue.get(timeout=1.)["camera_id"] == 3
    assert not consumer._pending_samples[1].request.pending.event.is_set()


def test_stages_publish_evidence_from_same_frame(make_consumer):
    consumer, snapshots, published = make_consumer(1, vehicle=True, start_thread=True)
    latest = consumer.latest_frames["camera_1"]
    captured_at = consumer.latest_frame_times["camera_1"]
    stages = [
        ("yolo_guard_person_phone", [{"bbox": [10, 12, 50, 70], "confidence": .98, "type": "person"}]),
        ("yolo_vehicle", [{"bbox": [50, 45, 65, 64], "confidence": .98, "type": "vehicle", "class_id": 2}]),
        ("guard_uniform", [{"confidence": .98, "type": "uniform"}]),
        ("yolo_guard_person_phone", [{"bbox": [10, 10, 14, 14], "confidence": .98, "type": "phone"}]),
        ("yolo_guard_pose", []),
    ]
    for index, (name, detections) in enumerate(stages):
        task = consumer.infer_dict[name].get(timeout=1.)
        if index == 0:
            consumer.latest_frames["camera_1"] = np.full_like(latest, 230)
            consumer.latest_frame_times["camera_1"] = time()
        assert np.all(task["frame"] == latest[0, 0, 0])
        complete(consumer, task, detections)

    assert published.wait(1)
    assert len(snapshots) == 1
    snapshot, annotated = snapshots[0]
    assert snapshot.updated_at == captured_at
    assert snapshot.guard_count == 1
    assert snapshot.vehicle.available
    assert snapshot.vehicle.detections[0].class_id == 2
    assert snapshot.model_states["yolo_guard_pose"] == "ready"
    assert snapshot.phone.state == "pending"
    assert annotated[-1, -1].tolist() == latest[-1, -1].tolist()


@pytest.mark.parametrize("cause", ["reload", "stale"])
def test_discard_partially_processed_sample(make_consumer, monkeypatch, cause):
    from AiVision.features.guard_behavior import consumer as module

    consumer, snapshots, _ = make_consumer(1)
    consumer._before_camera_round()
    queue = consumer.infer_dict["yolo_guard_person_phone"]
    task = queue.get_nowait()
    complete(consumer, task, [{"bbox": [10, 12, 50, 70], "confidence": .98, "type": "person"}])
    consumer._before_camera_round()
    assert 1 in consumer._guard_memories
    assert consumer.result_router.snapshot()["pending_count"] == 1

    if cause == "reload":
        consumer.reload_camera_config(1)
    else:
        stale_at = time() + 5.1
        monkeypatch.setattr(module, "time", lambda: stale_at)
        consumer._before_camera_round()

    assert not consumer._pending_samples
    assert not consumer._guard_memories
    assert not consumer._behaviors
    assert consumer.result_router.snapshot()["pending_count"] == 0
    assert not snapshots
