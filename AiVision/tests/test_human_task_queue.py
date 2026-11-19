"""共享人体模型在普通队列持续积压时的调度与生命周期回归。"""
import multiprocessing as mp
from queue import Full, Queue
import time
from unittest.mock import Mock

import pytest

from AiVision.inference.base_worker import BaseModelWorker
from AiVision.inference.human_task_queue import (
    DEFAULT_ORDINARY_CAPACITY,
    HUMAN_MODEL_NAME,
    TAILGATING_CAPACITY,
    HumanTaskQueue,
)


_ORDINARY_MODELS = (HUMAN_MODEL_NAME, "yolo_phone", "yolo_guard_person_phone", "yolo_vehicle")


class ProbeWorker(BaseModelWorker):
    def load_model(self):
        return object()

    def infer(self, model, frame, task_meta):
        assert not task_meta.get("expired"), "排队到期的任务不能进入推理"
        return []


def task(feature, camera_id):
    return {
        "function_name": feature, "camera_id": camera_id, "roi_id": 0,
        "request_id": f"{feature}:{camera_id}", "model_name": "unused", "frame": None,
    }


def test_tailgating_uses_reserved_slots_and_reaches_fourth_camera_under_saturation():
    human = HumanTaskQueue(queue_factory=Queue)
    queues = {name: human if name == HUMAN_MODEL_NAME else Queue() for name in _ORDINARY_MODELS}
    worker = ProbeWorker(queues, {}, "shared", "")
    # 开始时上一项闯闸还在执行，此时补齐两类队列，覆盖最后一路的最坏轮转位置。
    human.put(task("tailgating", 99))
    assert worker._next_task()["camera_id"] == 99
    for camera_id in range(DEFAULT_ORDINARY_CAPACITY):
        human.put(task("detect_logistics_single_person", camera_id))
    with pytest.raises(Full):
        human.put(task("detect_intrusion", 10), block=False)
    for name in _ORDINARY_MODELS[1:]:
        queues[name].put(task(f"regular_{name}", 0))
    for camera_id in range(1, TAILGATING_CAPACITY + 1):
        human.put(task("tailgating", camera_id), block=False)
    with pytest.raises(Full):
        human.put(task("tailgating", 5), block=False)

    tail_results, ordinary_models = [], []
    for turn in range(12):
        received = worker._next_task()
        if received["function_name"] == "tailgating":
            tail_results.append((turn, received))
        else:
            model_name = received["model_name"]
            ordinary_models.append(model_name)
            queues[model_name].put(task(received["function_name"], 100 + turn), block=False)

    assert [turn for turn, _ in tail_results] == [2, 5, 8, 11]
    assert [result["camera_id"] for _, result in tail_results] == [1, 2, 3, 4]
    assert [result["request_id"] for _, result in tail_results] == [f"tailgating:{i}" for i in range(1, 5)]
    assert {result["model_name"] for _, result in tail_results} == {HUMAN_MODEL_NAME}
    assert ordinary_models == list(_ORDINARY_MODELS) * 2


def test_runtime_manager_uses_configured_human_ordinary_capacity(monkeypatch, tmp_path):
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "queue_test",
        "MYSQL_DB_PASSWORD": "queue_test", "MYSQL_DB_NAME": "queue_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "human-queue-capacity-test-key",
    }.items():
        monkeypatch.setenv(key, value)
    from AiVision.inference import runtime_manager

    monkeypatch.setattr(runtime_manager.settings.runtime, "human_ordinary_queue_capacity", 2)
    manager = runtime_manager.InferenceRuntimeManager()
    manager.initialize_queues()
    human = manager.infer_queues[HUMAN_MODEL_NAME]
    assert human._ordinary_capacity == 2
    human.put(task("detect_logistics_single_person", 1), block=False)
    human.put(task("detect_logistics_single_person", 2), block=False)
    with pytest.raises(Full):
        human.put(task("detect_logistics_single_person", 3), block=False)
    for camera_id in range(TAILGATING_CAPACITY):
        human.put(task("tailgating", camera_id), block=False)
    with pytest.raises(Full):
        human.put(task("tailgating", TAILGATING_CAPACITY), block=False)
    manager.stop_all()


def test_idle_lane_does_not_block_work_and_next_tailgating_is_not_starved():
    human = HumanTaskQueue(queue_factory=Queue)
    phone = Queue()
    worker = ProbeWorker({HUMAN_MODEL_NAME: human, "yolo_phone": phone}, {}, "shared", "")
    for index in range(4):
        human.put(task("tailgating", index))
    assert [worker._next_task()["camera_id"] for _ in range(4)] == [0, 1, 2, 3]
    assert worker._next_task() is None

    for index in range(3):
        human.put(task("detect_logistics_single_person", index))
        phone.put(task("detect_phone", index))
    assert [worker._next_task()["model_name"] for _ in range(4)] == [HUMAN_MODEL_NAME, "yolo_phone"] * 2
    human.put(task("tailgating", 7))
    assert worker._next_task()["request_id"] == "tailgating:7"


def test_full_result_queue_is_nonblocking_only_in_shared_human_group():
    full = Mock()
    full.put.side_effect = Full
    waiting = Queue()
    outputs = {"detect_logistics_single_person": full, "tailgating": waiting}
    regular = task("detect_logistics_single_person", 1)
    tailgating = task("tailgating", 2)
    shared = ProbeWorker({HUMAN_MODEL_NAME: HumanTaskQueue(queue_factory=Queue)}, outputs, "shared", "")

    shared._publish_result(regular)
    shared._publish_result(tailgating)

    full.put.assert_called_once_with(regular, timeout=0.0)
    assert waiting.get_nowait() == tailgating
    full.reset_mock()
    separate = ProbeWorker({"yolo_phone": Queue()}, outputs, "yolo_phone", "")
    separate._publish_result(regular)
    full.put.assert_called_once_with(regular, timeout=0.5)


def test_spawn_worker_keeps_both_queues_and_drops_an_expired_tailgating_frame(monkeypatch):
    from AiVision.inference import base_worker

    context = mp.get_context("spawn")
    monkeypatch.setattr(base_worker, "mp", context)
    channels = []

    def make_queue(maxsize):
        channel = context.Queue(maxsize)
        channels.append(channel)
        return channel

    human = HumanTaskQueue(queue_factory=make_queue)
    regular_output, tailgating_output = make_queue(1), make_queue(4)
    worker = ProbeWorker(
        {HUMAN_MODEL_NAME: human}, {"detect_logistics_single_person": regular_output, "tailgating": tailgating_output},
        "shared", "",
    )
    expired = {**task("tailgating", 5), "expired": True, "deadline_at_monotonic": time.monotonic() - .1}
    regular = task("detect_logistics_single_person", 6)
    fresh = task("tailgating", 7)
    human.put(expired)
    human.put(regular)
    human.put(fresh)

    try:
        worker.start()
        assert worker._ready_event.wait(5)
        stale = tailgating_output.get(timeout=5)
        valid = tailgating_output.get(timeout=5)
        normal = regular_output.get(timeout=5)
        assert (stale["request_id"], stale["status"], stale["model_name"]) == (expired["request_id"], "timeout", HUMAN_MODEL_NAME)
        assert (valid["request_id"], valid["status"], valid["model_name"]) == (fresh["request_id"], "ok", HUMAN_MODEL_NAME)
        assert (normal["request_id"], normal["status"], normal["model_name"]) == (regular["request_id"], "ok", HUMAN_MODEL_NAME)
        worker.stop()
        assert worker._proc.exitcode == 0
    finally:
        if worker.is_alive():
            worker.stop()
        for channel in channels:
            channel.close()
            channel.join_thread()


def test_shared_group_reload_and_shutdown_drain_both_lanes_and_keep_queue_identity(monkeypatch, tmp_path):
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "test",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path), "AUTH_SECRET": "human-task-queue-test-signing-key",
    }.items():
        monkeypatch.setenv(key, value)
    from AiVision.inference.runtime_manager import InferenceRuntimeManager

    manager = InferenceRuntimeManager()
    manager.initialize_queues()
    human = manager.infer_queues[HUMAN_MODEL_NAME]
    phone = manager.infer_queues["yolo_phone"]
    group = {"name": HUMAN_MODEL_NAME, "model_names": (HUMAN_MODEL_NAME, "yolo_phone")}
    owners = {name: HUMAN_MODEL_NAME for name in group["model_names"]}
    previous, reloaded = Mock(), Mock()
    manager._active = True
    manager._model_configs[HUMAN_MODEL_NAME] = group
    manager._model_owners.update(owners)
    manager._workers[HUMAN_MODEL_NAME] = previous
    monkeypatch.setattr(manager, "_build_model_groups", lambda: ({HUMAN_MODEL_NAME: group}, owners))
    monkeypatch.setattr(manager, "_wait_for_workers_ready", Mock())

    def start(_group):
        previous.stop.assert_called_once()
        assert human.discard_pending() == 0
        manager._workers[HUMAN_MODEL_NAME] = reloaded

    monkeypatch.setattr(manager, "_start_one", start)
    human.put(task("tailgating", 1))
    human.put(task("detect_logistics_single_person", 2))
    phone.put(task("detect_phone", 3))

    manager._reload_affected("yolo_phone")
    manager.initialize_queues()
    assert {value["status"] for value in manager._reload_results.values()} == {"succeeded"}
    assert manager.infer_queues[HUMAN_MODEL_NAME] is human
    assert manager.infer_queues["yolo_phone"] is phone

    human.put(task("tailgating", 4))
    human.put(task("detect_logistics_single_person", 5))
    manager.stop_all()
    reloaded.stop.assert_called_once()
    assert human.discard_pending() == 0
