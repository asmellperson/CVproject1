import queue
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
