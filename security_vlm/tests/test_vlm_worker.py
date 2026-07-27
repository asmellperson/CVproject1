import queue
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import vlm_worker


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
    )

    assert result["compliant"] is True
    assert calls[0]["request_timeout"] == 45.0
    assert "timeout" not in calls[0]


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
