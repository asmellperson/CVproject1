# Logistics Variant Monitor Snapshots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish fresh read-only person-count snapshots from the three department-specific logistics single-person consumers through the already existing generic status endpoint.

**Architecture:** Reuse the existing pure `build_monitor_snapshot` aggregator from the General Electric logistics consumer. Each variant stores the aggregate before frame drawing and exposes a defensive-copy getter; no detection, drawing, alarm, API, or frontend behavior is changed.

**Tech Stack:** Python 3, pytest, existing AiVision consumer/orchestrator architecture

---

### Task 1: Add failing snapshot publication tests

**Files:**
- Modify: `AiVision/tests/test_logistics_single_person.py`

- [ ] **Step 1: Import the three variant consumers and pytest**

Add imports for:

```python
import pytest
from features.detect_logistics_single_person_electronics_electrician.consumer import LogisticsSinglePersonElectronicsElectricianConsumer
from features.detect_logistics_single_person_electrical_components.consumer import LogisticsSinglePersonElectricalComponentsConsumer
from features.detect_logistics_single_person_precious_metal_recycling.consumer import LogisticsSinglePersonPreciousMetalRecyclingConsumer
```

- [ ] **Step 2: Add one parameterized behavior test**

Use all three classes and construct a minimal consumer without invoking model infrastructure:

```python
@pytest.mark.parametrize("consumer_class", VARIANT_CONSUMER_CLASSES)
def test_logistics_variant_publishes_defensive_monitor_snapshot(consumer_class):
    consumer = object.__new__(consumer_class)
    consumer.monitor_status = {}
    consumer.config_cache = {7: {"shm_name": "cam-variant"}}
    consumer.frame_cache = {}
    result = [
        (False, {"reason": "normal", "person_count": 1}),
        (True, {"reason": "multiple", "person_count": 2}),
    ]

    assert consumer.post_process(7, result) is None
    snapshot = consumer.get_monitor_status("cam-variant")
    assert snapshot["count"] == 3
    assert snapshot["alarm"] is True
    assert snapshot["reason"] == "multiple"
    assert snapshot["updated_at_s"] > 0

    snapshot["count"] = 99
    assert consumer.get_monitor_status("cam-variant")["count"] == 3
```

- [ ] **Step 3: Run the focused test and verify RED**

Run:

```bash
cd AiVision
pytest -q tests/test_logistics_single_person.py
```

Expected: three parameter cases fail because the variants do not yet have `monitor_status` publication or `get_monitor_status`.

### Task 2: Add minimal snapshot capability to each variant

**Files:**
- Modify: `AiVision/features/detect_logistics_single_person_electronics_electrician/consumer.py`
- Modify: `AiVision/features/detect_logistics_single_person_electrical_components/consumer.py`
- Modify: `AiVision/features/detect_logistics_single_person_precious_metal_recycling/consumer.py`

- [ ] **Step 1: Import the existing pure aggregator**

In each consumer add:

```python
from features.detect_logistics_single_person.consumer import build_monitor_snapshot
```

- [ ] **Step 2: Initialize the status dictionary**

Immediately after the existing `_presence_states` initialization add:

```python
self.monitor_status: dict[str, dict] = {}
```

- [ ] **Step 3: Publish before frame drawing**

At the beginning of each existing `post_process` add:

```python
camera_key = str(self.config_cache.get(camera_id, {}).get("shm_name") or "").strip()
if camera_key:
    self.monitor_status[camera_key] = build_monitor_snapshot(result)
```

Keep every existing OpenCV statement and return path unchanged.

- [ ] **Step 4: Add the read-only getter**

Before `_label_for`, add:

```python
def get_monitor_status(self, camera_key: str) -> dict | None:
    value = self.monitor_status.get(camera_key)
    return dict(value) if value else None
```

- [ ] **Step 5: Run the focused test and verify GREEN**

Run `pytest -q tests/test_logistics_single_person.py` from `AiVision`.

Expected: all existing tests and all three new parameter cases pass.

### Task 3: Verify the existing status path and change boundary

**Files:**
- Verify all files changed in Tasks 1–2

- [ ] **Step 1: Run related backend tests**

Run:

```bash
cd AiVision
pytest -q tests/test_logistics_single_person.py tests/test_logistics_monitor_status_api.py
```

Expected: all tests pass, confirming snapshot aggregation and the unchanged generic status route.

- [ ] **Step 2: Run syntax compilation**

Run:

```bash
python -m compileall -q features/detect_logistics_single_person_electronics_electrician features/detect_logistics_single_person_electrical_components features/detect_logistics_single_person_precious_metal_recycling
```

Expected: exit code 0.

- [ ] **Step 3: Review the diff**

Run `git diff --check` and `git diff --name-only` from the repository root.

Expected: only this plan, the three consumer files, and `AiVision/tests/test_logistics_single_person.py` are uncommitted; no frontend, orchestrator, API, detection-decision, ROI, drawing, or alarm files are modified.

- [ ] **Step 4: Commit the implementation**

Commit the three consumers and test with:

```bash
git commit -m "feat: expose logistics variant monitor status"
```

Do not push or move V4 unless the user separately requests it.
