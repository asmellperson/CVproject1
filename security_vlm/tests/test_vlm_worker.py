import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import vlm_worker


def test_pending_task_lock_entries_release_after_all_waiters_exit():
    processor = vlm_worker.PendingTaskProcessor(
        stores=None,
        accumulators=None,
        judge=None,
        queue_timeout=1,
    )
    key = ("general_electric", "camera-a", "session-a")
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first():
        with processor._hold_task_lock(key):
            first_entered.set()
            assert release_first.wait(timeout=2)

    def second():
        assert first_entered.wait(timeout=2)
        with processor._hold_task_lock(key):
            second_entered.set()

    first_thread = threading.Thread(target=first)
    second_thread = threading.Thread(target=second)
    first_thread.start()
    second_thread.start()
    assert first_entered.wait(timeout=2)
    assert not second_entered.wait(timeout=0.05)
    assert len(processor._task_locks) == 1

    release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert second_entered.is_set()
    assert processor._task_locks == {}


def test_department_fair_queue_concurrent_semantics_and_counts(tmp_path):
    task_q = vlm_worker.DepartmentFairTaskQueue()
    tasks = [
        vlm_worker.PendingTask(
            (
                "general_electric"
                if index % 2 == 0
                else "electronics_electrician"
            ),
            f"camera-{index % 3}",
            tmp_path / f"{index}.pkl",
        )
        for index in range(30)
    ]
    consumed = []

    def producer():
        for task in tasks:
            task_q.put(task)

    def consumer():
        for _index in range(len(tasks)):
            consumed.append(task_q.get(timeout=2))
            task_q.task_done()

    producer_thread = threading.Thread(target=producer)
    consumer_thread = threading.Thread(target=consumer)
    consumer_thread.start()
    producer_thread.start()
    producer_thread.join(timeout=2)
    consumer_thread.join(timeout=2)

    assert not producer_thread.is_alive()
    assert not consumer_thread.is_alive()
    assert {task.path for task in consumed} == {task.path for task in tasks}
    assert task_q.unfinished_tasks == 0
    assert task_q.qsize() == 0
    assert task_q.empty() is True
    assert vlm_worker.queued_department_counts(task_q) == {
        department: 0 for department in vlm_worker.SECURITY_DEPARTMENTS
    }
    with pytest.raises(queue.Empty):
        task_q.get(timeout=0.01)
    with pytest.raises(ValueError, match="task_done"):
        task_q.task_done()


def test_process_queued_item_contains_task_exception(capsys):
    task_q = queue.Queue()
    first = Path("first.pkl")
    second = Path("second.pkl")
    task_q.put(first)
    task_q.put(second)
    processed = []

    def process_one(path):
        processed.append(path)
        if path == first:
            raise RuntimeError("broken task")

    vlm_worker.process_queued_item(task_q, process_one)
    vlm_worker.process_queued_item(task_q, process_one)

    assert processed == [first, second]
    assert task_q.unfinished_tasks == 0
    assert "broken task" in capsys.readouterr().err


def test_shutdown_drains_task_put_after_global_stop_during_scanner_scan(tmp_path):
    task_q = vlm_worker.DepartmentFairTaskQueue()
    late_task = vlm_worker.PendingTask(
        "general_electric",
        "camera-late",
        tmp_path / "late.pkl",
    )
    scan_started = threading.Event()
    allow_late_put = threading.Event()
    worker_stop = threading.Event()
    processed = []
    worker_stop_states = []

    class DelayedScanner(threading.Thread):
        def run(self):
            scan_started.set()
            assert allow_late_put.wait(timeout=2)
            task_q.put(late_task)

        def stop(self):
            allow_late_put.set()

    def process_one(task):
        worker_stop_states.append(worker_stop.is_set())
        processed.append(task)

    scanner = DelayedScanner()
    workers = [
        threading.Thread(
            target=vlm_worker.run_task_worker,
            args=(task_q, process_one, worker_stop),
            kwargs={"poll_sec": 0.01},
        )
        for _index in range(2)
    ]
    for worker in workers:
        worker.start()
    scanner.start()
    assert scan_started.wait(timeout=2)

    try:
        vlm_worker._STOP.set()
        drained = vlm_worker.shutdown_task_workers(
            scanner,
            task_q,
            worker_stop,
            workers,
            drain_timeout_sec=2,
            poll_sec=0.01,
        )
    finally:
        vlm_worker._STOP.clear()
        allow_late_put.set()
        scanner.join(timeout=2)
        worker_stop.set()
        for worker in workers:
            worker.join(timeout=2)

    assert drained is True
    assert processed == [late_task]
    assert worker_stop_states == [False]
    assert task_q.unfinished_tasks == 0
    assert task_q.empty() is True
    assert all(not worker.is_alive() for worker in workers)


def test_shutdown_timeout_leaves_in_progress_task_for_recovery(tmp_path):
    task_path = tmp_path / "global" / "processing" / "camera-a" / "slow.pkl"
    task_path.parent.mkdir(parents=True)
    task_path.write_bytes(b"recoverable")
    task = vlm_worker.PendingTask(
        "general_electric",
        "camera-a",
        task_path,
    )
    task_q = vlm_worker.DepartmentFairTaskQueue()
    task_q.put(task)
    process_started = threading.Event()
    release_process = threading.Event()
    scanner_stopped = threading.Event()
    worker_stop = threading.Event()

    class IdleScanner(threading.Thread):
        def run(self):
            scanner_stopped.wait()

        def stop(self):
            scanner_stopped.set()

    def process_one(_task):
        process_started.set()
        assert release_process.wait(timeout=2)

    scanner = IdleScanner()
    worker = threading.Thread(
        target=vlm_worker.run_task_worker,
        args=(task_q, process_one, worker_stop),
        kwargs={"poll_sec": 0.01},
    )
    scanner.start()
    worker.start()
    assert process_started.wait(timeout=2)

    try:
        drained = vlm_worker.shutdown_task_workers(
            scanner,
            task_q,
            worker_stop,
            [worker],
            drain_timeout_sec=0.01,
            poll_sec=0.005,
            worker_join_timeout_sec=0.01,
        )
        assert drained is False
        assert task_path.read_bytes() == b"recoverable"
        assert task_q.unfinished_tasks == 1
    finally:
        release_process.set()
        worker_stop.set()
        worker.join(timeout=2)
        scanner_stopped.set()
        scanner.join(timeout=2)

    assert not worker.is_alive()
    assert task_q.unfinished_tasks == 0


def test_draw_text_falls_back_when_configured_font_cannot_be_opened(monkeypatch):
    original_truetype = vlm_worker.ImageFont.truetype

    def unavailable_file_font(font, *args, **kwargs):
        if isinstance(font, (str, Path)):
            raise OSError("cannot open resource")
        return original_truetype(font, *args, **kwargs)

    monkeypatch.setattr(vlm_worker.ImageFont, "truetype", unavailable_file_font)
    image = np.zeros((90, 480, 3), dtype=np.uint8)

    rendered = vlm_worker._draw_text_pil(
        image,
        "session-1 [不合规：安检流程未完成]",
        (10, 8),
    )

    assert rendered.shape == image.shape
    assert rendered.dtype == image.dtype


def test_vlm_judge_passes_request_timeout(tmp_path):
    calls = []

    class FakeMMC:
        @classmethod
        def call(cls, **kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content='{"compliant": true}')
            choice = SimpleNamespace(message=message)
            output = SimpleNamespace(choices=[choice])
            return SimpleNamespace(status_code=200, output=output, usage=None)

    judge = object.__new__(vlm_worker.VLMJudge)
    judge.MMC = FakeMMC
    judge.model = "test-model"
    judge.api_timeout = 45.0
    judge.image_max_side = 960
    judge.image_quality = 85
    judge.budget = SimpleNamespace(try_consume=lambda: True)
    judge.tmp_dir = tmp_path

    result = judge.judge(
        "session-1",
        "security_staff_1",
        [0, 0, 10, 10],
        [np.zeros((10, 10, 3), dtype=np.uint8)],
        department="electrical_components",
    )

    assert result["compliant"] is True
    assert calls[0]["request_timeout"] == 45.0
    assert "timeout" not in calls[0]
    image_uri = calls[0]["messages"][1]["content"][0]["image"]
    assert "/electrical_components/" in image_uri


def test_budget_guard_restores_same_day_and_persists_each_consumption():
    today = vlm_worker.datetime.now().strftime("%Y-%m-%d")
    persisted = []
    budget = vlm_worker.BudgetGuard(
        daily_limit=10,
        est_cost_per_call=0.5,
        initial_state={
            "date": today,
            "call_count": 3,
            "spent_yuan": 1.5,
        },
        on_change=persisted.append,
    )

    assert budget.try_consume() is True
    assert budget.snapshot()["call_count"] == 4
    assert budget.snapshot()["spent_yuan"] == 2.0
    assert persisted[-1]["call_count"] == 4


def test_budget_persistence_snapshots_never_move_backwards_under_concurrency():
    persisted = []
    budget = vlm_worker.BudgetGuard(
        daily_limit=100,
        est_cost_per_call=0.5,
        on_change=lambda snapshot: persisted.append(snapshot["call_count"]),
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: budget.try_consume(), range(20)))

    assert all(results)
    assert persisted == list(range(1, 21))
