# Security VLM Queue Stall Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep VLM consumers alive under task failures, make shared JSON status writes concurrency-safe, and apply the configured DashScope request timeout.

**Architecture:** Preserve the existing filesystem queue and worker-thread model. Make the shared JSON primitive safe with per-call temporary files, add one top-level queue-item execution boundary that the nested worker loop reuses, and pass DashScope's supported transport-timeout keyword.

**Tech Stack:** Python 3.10, pathlib, tempfile, queue, threading, DashScope SDK, pytest

---

## File map

- Modify `security_vlm/src/frame_hub.py`: concurrency-safe atomic JSON replacement.
- Modify `security_vlm/src/vlm_worker.py`: DashScope timeout keyword and reusable worker exception boundary.
- Create `security_vlm/tests/conftest.py`: make `security_vlm/src` importable in focused tests.
- Create `security_vlm/tests/test_frame_hub.py`: concurrent-write regression test.
- Create `security_vlm/tests/test_vlm_worker.py`: worker-survival and timeout regression tests.

### Task 1: Reproduce and fix concurrent JSON replacement

**Files:**
- Create: `security_vlm/tests/conftest.py`
- Create: `security_vlm/tests/test_frame_hub.py`
- Modify: `security_vlm/src/frame_hub.py:21-44`

- [ ] **Step 1: Add the test import path**

```python
from pathlib import Path
import sys

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))
```

- [ ] **Step 2: Write the failing concurrent-write test**

```python
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

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
```

- [ ] **Step 3: Run the test and verify RED**

Run:

```bash
/root/miniconda3/envs/security_vlm/bin/python -m pytest security_vlm/tests/test_frame_hub.py -v
```

Expected: FAIL because concurrent calls race on `vlm_latest_stats.json.tmp`, with collected `FileNotFoundError` instances.

- [ ] **Step 4: Implement unique same-directory temporary files**

Add `NamedTemporaryFile` to the imports and replace `atomic_write_json` with:

```python
def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
```

- [ ] **Step 5: Run the focused test and verify GREEN**

Run the command from Step 3.

Expected: `1 passed` with zero collected write failures.

### Task 2: Keep a worker alive after an unexpected task failure

**Files:**
- Modify: `security_vlm/src/vlm_worker.py:20-40, 639-646`
- Create: `security_vlm/tests/test_vlm_worker.py`

- [ ] **Step 1: Write the failing worker-boundary test**

```python
import queue
from pathlib import Path

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
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
/root/miniconda3/envs/security_vlm/bin/python -m pytest security_vlm/tests/test_vlm_worker.py::test_process_queued_item_contains_task_exception -v
```

Expected: FAIL with `AttributeError` because `process_queued_item` does not exist.

- [ ] **Step 3: Implement the task exception boundary**

Import `traceback`. Add one top-level helper before `main`; when `item` is omitted it gets an item itself for direct tests, while the production loop supplies the item obtained with its existing timeout:

```python
def process_queued_item(task_q: queue.Queue, process_one, item=None) -> None:
    queued_item = task_q.get() if item is None else item
    try:
        process_one(Path(queued_item))
    except Exception:
        print(f"[vlm] worker 任务异常: {queued_item}", file=sys.stderr, flush=True)
        traceback.print_exc()
    finally:
        task_q.task_done()
```

The worker loop becomes:

```python
def worker_loop():
    while not _STOP.is_set():
        try:
            p = task_q.get(timeout=0.5)
        except queue.Empty:
            continue
        process_queued_item(task_q, process_one, p)
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the command from Step 2.

Expected: `1 passed`; the traceback is captured and the second task is processed.

### Task 3: Apply the configured DashScope request timeout

**Files:**
- Modify: `security_vlm/src/vlm_worker.py:264-271`
- Modify: `security_vlm/tests/test_vlm_worker.py`

- [ ] **Step 1: Write the failing timeout-keyword test**

```python
from types import SimpleNamespace

import numpy as np


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
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
/root/miniconda3/envs/security_vlm/bin/python -m pytest security_vlm/tests/test_vlm_worker.py::test_vlm_judge_passes_request_timeout -v
```

Expected: FAIL with `KeyError: 'request_timeout'`; the current call captured `timeout=45.0`.

- [ ] **Step 3: Implement the supported timeout keyword**

Replace the compatibility block with:

```python
response = self.MMC.call(
    model=self.model,
    messages=messages,
    request_timeout=self.api_timeout,
)
```

- [ ] **Step 4: Run both VLM worker tests and verify GREEN**

Run:

```bash
/root/miniconda3/envs/security_vlm/bin/python -m pytest security_vlm/tests/test_vlm_worker.py -v
```

Expected: `2 passed`.

### Task 4: Full focused verification

**Files:**
- Verify: `security_vlm/src/frame_hub.py`
- Verify: `security_vlm/src/vlm_worker.py`
- Verify: `security_vlm/tests/`

- [ ] **Step 1: Run the complete security_vlm test suite**

```bash
/root/miniconda3/envs/security_vlm/bin/python -m pytest security_vlm/tests -v
```

Expected: all tests pass without warnings or unhandled thread exceptions.

- [ ] **Step 2: Compile modified modules**

```bash
/root/miniconda3/envs/security_vlm/bin/python -m py_compile security_vlm/src/frame_hub.py security_vlm/src/vlm_worker.py
```

Expected: exit code 0 with no output.

- [ ] **Step 3: Repeat a higher-volume concurrent-write check**

```bash
/root/miniconda3/envs/security_vlm/bin/python -m pytest security_vlm/tests/test_frame_hub.py -v --count=10
```

If `pytest-repeat` is not installed, run the standard focused test once and rely on its 200 synchronized writes; do not add a dependency solely for repetition.

- [ ] **Step 4: Inspect the final diff**

Confirm only the two source modules, two focused test modules, test configuration, design, and plan documents changed. Do not include runtime results or real configuration files.

- [ ] **Step 5: Commit when Git metadata is restored**

The current `.git` file points to the missing path `/usr/zyy/Fuda_CVPreject/.git/worktrees/Fuda_CVPreject_V1`, so commits are blocked. Do not reconstruct or replace Git metadata without user authorization. Once restored, commit only the files listed in this plan.
