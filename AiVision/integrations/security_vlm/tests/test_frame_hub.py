import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, Thread

import numpy as np
import pytest

from frame_hub import FrameHubReader, FrameHubWriter, atomic_write_json, reset_frame_hub


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


def test_frame_hub_resolution_change_keeps_old_mapping_safe(tmp_path):
    old_frame = np.full((4, 6, 3), 7, dtype=np.uint8)
    old_writer = FrameHubWriter(tmp_path, height=4, width=6)
    old_writer.write(old_frame, frame_id=1)
    old_reader = FrameHubReader(tmp_path)

    reset_frame_hub(tmp_path)
    assert not (tmp_path / "frame_meta.json").exists()

    new_frame = np.full((2, 3, 3), 9, dtype=np.uint8)
    new_writer = FrameHubWriter(tmp_path, height=2, width=3)
    new_writer.write(new_frame, frame_id=1)
    new_reader = FrameHubReader(tmp_path)

    assert np.array_equal(old_reader.read_frame(), old_frame)
    assert np.array_equal(new_reader.read_frame(), new_frame)
    assert (new_reader.height, new_reader.width) == (2, 3)


def test_frame_hub_reader_retries_when_meta_precedes_slots(tmp_path):
    atomic_write_json(tmp_path / "frame_meta.json", {
        "height": 4,
        "width": 6,
        "channels": 3,
        "slot_idx": 0,
        "frame_id": -1,
    })
    frame = np.full((2, 3, 3), 11, dtype=np.uint8)

    def start_writer():
        time.sleep(0.1)
        writer = FrameHubWriter(tmp_path, height=2, width=3)
        writer.write(frame, frame_id=1)

    thread = Thread(target=start_writer)
    thread.start()
    reader = FrameHubReader(tmp_path, wait_timeout_sec=1.0)
    thread.join()

    assert (reader.height, reader.width) == (2, 3)
    assert np.array_equal(reader.read_frame(), frame)
