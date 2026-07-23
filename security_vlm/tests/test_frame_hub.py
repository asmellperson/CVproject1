import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest

from frame_hub import atomic_write_json


def test_atomic_write_json_supports_concurrent_writers(tmp_path):
    workers = 4
    rounds = 50
    barrier = Barrier(workers)
    failures = []
    failures_lock = Lock()
    target = tmp_path / "vlm_latest_stats.json"

    def write_many(worker_id):
        for index in range(rounds):
            barrier.wait()
            try:
                atomic_write_json(
                    target,
                    {"worker": worker_id, "index": index, "padding": "x" * 65536},
                )
            except Exception as exc:
                with failures_lock:
                    failures.append(exc)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(write_many, range(workers)))

    assert failures == []
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["worker"] in range(workers)
    assert payload["index"] in range(rounds)


def test_atomic_write_json_removes_temp_file_after_serialization_error(tmp_path):
    target = tmp_path / "vlm_latest_stats.json"

    with pytest.raises(TypeError):
        atomic_write_json(target, {"not_json": object()})

    assert list(tmp_path.iterdir()) == []
