# Logistics Single-Person Monitor UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a typed read-only logistics detection snapshot and rebuild the logistics single-person monitor tab with the approved guard-style dashboard without changing existing frame playback, configuration, alarm dispatch, or embedded frame annotations.

**Architecture:** The logistics consumer publishes its latest aggregate detection snapshot, the orchestrator and compatibility API expose that snapshot read-only, and the frontend polls it independently from the unchanged JPEG loop. `AiVisionMonitor` keeps ownership of camera/frame lifecycle and opts into a focused logistics dashboard view; a small state helper handles semantic count transitions and today's existing alarm records.

**Tech Stack:** Python 3, FastAPI, pytest, React 19, TypeScript, Tailwind CSS, lucide-react, Node test runner, Vite

---

### Task 1: Publish the latest logistics detection snapshot

**Files:**
- Modify: `AiVision/features/detect_logistics_single_person/consumer.py`
- Modify: `AiVision/tests/test_logistics_single_person.py`

- [x] **Step 1: Write failing aggregation tests**

Extend the existing test file with pure aggregation cases:

```python
from features.detect_logistics_single_person.consumer import build_monitor_snapshot


def test_monitor_snapshot_sums_known_roi_counts_and_preserves_alarm():
    result = [
        (False, {"reason": "normal", "person_count": 1}),
        (True, {"reason": "multiple", "person_count": 2}),
    ]
    snapshot = build_monitor_snapshot(result, updated_at=100.0)
    assert snapshot == {
        "count": 3,
        "alarm": True,
        "reason": "multiple",
        "updated_at_s": 100.0,
    }


def test_monitor_snapshot_keeps_unknown_count_neutral():
    snapshot = build_monitor_snapshot(
        [(False, {"reason": "unknown", "person_count": None})],
        updated_at=101.0,
    )
    assert snapshot["count"] is None
    assert snapshot["alarm"] is False
    assert snapshot["reason"] == "unknown"
```

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd AiVision
pytest -q tests/test_logistics_single_person.py
```

Expected: collection fails because `build_monitor_snapshot` does not exist.

- [x] **Step 3: Implement snapshot publication without changing drawing or alarm logic**

Add a pure `build_monitor_snapshot(result, updated_at=None)` helper. It sums integer `person_count` values, returns `None` if none are known, sets `alarm` from existing result flags, chooses `multiple`, then `empty`, then `normal`, then `unknown` reason priority, and records epoch seconds.

In `LogisticsSinglePersonConsumer.__init__`, add:

```python
self.monitor_status: dict[str, dict] = {}
```

At the start of `post_process`, resolve the existing `shm_name` from `self.config_cache[camera_id]` and atomically assign the helper result to `monitor_status`. Add:

```python
def get_monitor_status(self, camera_key: str) -> dict | None:
    value = self.monitor_status.get(camera_key)
    return dict(value) if value else None
```

Do not edit OpenCV ROI, label, box drawing, `_handle_alarm`, thresholds, or result tuples.

- [x] **Step 4: Run the focused test and verify GREEN**

Run `pytest -q tests/test_logistics_single_person.py`.

Expected: all logistics single-person tests pass.

### Task 2: Expose the snapshot through a read-only compatibility route

**Files:**
- Modify: `AiVision/platform/orchestrator.py`
- Modify: `AiVision/api/compat.py`
- Create: `AiVision/tests/test_logistics_monitor_status_api.py`

- [x] **Step 1: Write failing orchestrator and route tests**

Create fakes for a running camera, consumer snapshot, and orchestrator. Cover:

```python
def test_compat_status_returns_typed_snapshot():
    response = compat_get_camera_feature_status(
        key="cam1",
        feature="detect_logistics_single_person",
        orchestrator=StatusOrchestrator(),
    )
    assert response["camera_key"] == "cam1"
    assert response["online"] is True
    assert response["count"] == 1
    assert response["alarm"] is False
    assert response["reason"] == "normal"
    assert response["updated_at"]


def test_compat_status_returns_unknown_when_snapshot_is_missing():
    response = compat_get_camera_feature_status(
        key="missing",
        feature="detect_logistics_single_person",
        orchestrator=EmptyStatusOrchestrator(),
    )
    assert response["online"] is False
    assert response["count"] is None
    assert response["alarm"] is False
    assert response["reason"] == "unknown"
```

- [x] **Step 2: Run the API test and verify RED**

Run:

```bash
cd AiVision
pytest -q tests/test_logistics_monitor_status_api.py
```

Expected: import fails because the compatibility handler does not exist.

- [x] **Step 3: Add the read-only lookup and route**

Add `Orchestrator.get_feature_monitor_status(shm_name, feature)` that reads the consumer getter, checks camera membership in `camera_manager.list_running()`, treats snapshots older than the existing annotated-frame freshness window as unknown, and returns:

```python
{
    "camera_key": shm_name,
    "feature": feature,
    "online": online,
    "count": count,
    "alarm": alarm,
    "reason": reason,
    "updated_at": iso_timestamp_or_none,
}
```

Add the GET route:

```python
@router.get("/api/aivision/cameras/{key}/features/{feature}/status")
def compat_get_camera_feature_status(
    key: str,
    feature: str,
    orchestrator=Depends(get_current_orchestrator),
):
    return orchestrator.get_feature_monitor_status(key, feature)
```

This route performs no writes and does not call or alter the frame endpoint.

- [x] **Step 4: Run focused backend tests**

Run:

```bash
cd AiVision
pytest -q tests/test_logistics_single_person.py tests/test_logistics_monitor_status_api.py tests/test_camera_frame_response.py
```

Expected: all selected tests pass.

### Task 3: Add typed frontend status and event derivation

**Files:**
- Modify: `unified_frontend/src/lib/aivision.ts`
- Create: `unified_frontend/src/components/logistics_single_person/monitorState.ts`
- Create: `unified_frontend/tests/logistics-single-person-monitor-contract.test.mjs`

- [x] **Step 1: Write the failing frontend contract**

Assert the source contains:

```js
assert.match(api, /export type AiVisionLogisticsSinglePersonStatus/)
assert.match(api, /getAiVisionLogisticsSinglePersonStatus/)
assert.match(api, /cameras\/\$\{encodeURIComponent\(cameraKey\)\}\/features\/detect_logistics_single_person\/status/)
assert.match(state, /export function classifyLogisticsCount/)
assert.match(state, /ROI 内人数恢复正常：1 人/)
assert.match(state, /ROI 内无人异常：0 人/)
assert.match(state, /ROI 内多人异常：\$\{count\} 人/)
assert.doesNotMatch(state, /通行/)
```

- [x] **Step 2: Run the contract and verify RED**

Run:

```bash
cd unified_frontend
node tests/logistics-single-person-monitor-contract.test.mjs
```

Expected: FAIL because the status type, request, and state helper do not exist.

- [x] **Step 3: Add typed status request and pure state helpers**

Add optional `fps?: number` to `AiVisionCamera`, the typed status response, and a credentials-included GET request in `aivision.ts`.

In `monitorState.ts`, define `unknown | normal | empty | multiple` classification, formatted event labels, same-state de-duplication, a capped event list, and a helper that filters existing `AlarmEvent[]` by local day, feature type, and selected camera. Do not create a normal-event persistence request.

- [x] **Step 4: Run the focused contract and build**

Run:

```bash
cd unified_frontend
node tests/logistics-single-person-monitor-contract.test.mjs
npm run build
```

Expected: the data-layer assertions and TypeScript build pass; layout assertions added in Task 4 still do not exist.

### Task 4: Build the logistics dashboard presentation

**Files:**
- Create: `unified_frontend/src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx`
- Create: `unified_frontend/src/components/logistics_single_person/useLogisticsSinglePersonMonitor.ts`
- Modify: `unified_frontend/src/components/AiVisionMonitor.tsx`
- Modify: `unified_frontend/tests/logistics-single-person-monitor-contract.test.mjs`

- [x] **Step 1: Extend the failing layout contract**

Assert the view contains the four requested metric labels, `grid grid-cols-2 gap-4 lg:grid-cols-4`, `grid gap-5 lg:grid-cols-3`, `lg:col-span-2`, `监控对象`, `判定说明`, `实时事件`, all three ROI rule labels, video title, `当前`, `FPS`, `LIVE`, `人员异常告警`, glass pill classes, and vignette classes. Assert it contains no `通行` text and no replacement `alarm_line` or ROI SVG label.

Also assert `AiVisionMonitor.tsx` retains the exact existing frame request, polling timeout, blob cleanup, natural-size handling, and default render markers.

- [x] **Step 2: Run the contract and verify RED**

Run `node tests/logistics-single-person-monitor-contract.test.mjs`.

Expected: FAIL because the logistics hook and view do not exist.

- [x] **Step 3: Implement the status/alarm hook**

`useLogisticsSinglePersonMonitor` receives `enabled`, `selectedCamera`, and selected camera name. It polls the new status endpoint every second and the existing `getAlarms(1000, ['detect_logistics_single_person'])` every five seconds. It retains the last successful alarm list, resets semantic event state on camera change, and inserts only transition events generated by `monitorState.ts`.

- [x] **Step 4: Implement the pure dashboard view**

Render the approved reference hierarchy:

```text
statistics row
main three-column grid
  left: monitoring object -> decision guide -> real-time events
  right span 2: video card
```

Use `#132C72`, `#F3F5FA`, `rounded-2xl`, slate borders, lucide icons, emerald normal state, and rose abnormal state. Reuse the existing select values/callback and refresh handler. Render existing frame content and overlay coordinates passed by `AiVisionMonitor`; add only glass status pills and a pointer-events-none vignette.

- [x] **Step 5: Opt `AiVisionMonitor` into the new view without altering its lifecycle**

Add an optional `presentation="logistics-single-person"` prop. Keep all existing effects and frame-fetch statements unchanged. Call the logistics hook with an `enabled` flag and return the new view only for that presentation; leave the existing default JSX as the fallback for every other page.

- [x] **Step 6: Run the focused contract and build**

Run:

```bash
cd unified_frontend
node tests/logistics-single-person-monitor-contract.test.mjs
npm run build
```

Expected: contract and build pass.

### Task 5: Restyle the page shell and preserve configuration

**Files:**
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonDetectionSection.tsx`
- Modify: `unified_frontend/tests/logistics-single-person-monitor-contract.test.mjs`

- [x] **Step 1: Add failing page-shell assertions**

Assert the section contains `物流通道单人检测监控与配置`, an ROI single-person subtitle, `bg-[#F3F5FA]`, the rounded segmented tab classes, and:

```tsx
<AiVisionMonitor
  title="物流通道单人检测监控"
  feature="detect_logistics_single_person"
  presentation="logistics-single-person"
/>
```

Keep source-contract assertions for `loadConfig`, `loadCameras`, `saveConfig`, camera add/remove handlers, `FeatureCameraManager`, `AiVisionRoiEditor`, and all configuration tab values.

- [x] **Step 2: Run the contract and verify RED**

Run `node tests/logistics-single-person-monitor-contract.test.mjs`.

Expected: page-shell assertions fail before styling.

- [x] **Step 3: Restyle only the outer page and primary tabs**

Add the approved title/subtitle and guard-style segmented control. Pass the presentation prop in the monitor tab. Leave the nested configuration tabs, fields, requests, permissions, and handlers untouched.

- [x] **Step 4: Run the focused contract and verify GREEN**

Run `node tests/logistics-single-person-monitor-contract.test.mjs`.

Expected: all logistics monitor contract tests pass.

### Task 6: Regression verification, review, and commit

**Files:**
- Modify: `docs/superpowers/plans/2026-08-06-logistics-single-person-monitor-ui.md`
- Modify/Create: all files listed above

- [x] **Step 1: Run complete verification**

```bash
cd AiVision
pytest -q tests/test_logistics_single_person.py tests/test_logistics_monitor_status_api.py tests/test_camera_frame_response.py

cd ../unified_frontend
node --test tests/*.test.mjs
npm run build
npm run lint

cd ..
git diff --check
git status --short
```

Expected: selected backend tests, all frontend contracts, and production build pass; lint has zero errors, allowing the four known out-of-scope hooks warnings.

- [x] **Step 2: Review protected behavior**

Confirm the diff does not alter configuration requests/handlers, existing frame URL, 200ms frame refresh, request timeout, blob URL cleanup, image-size reading, OpenCV region drawing, label text, or alarm dispatch. Confirm no page text contains `通行`.

- [x] **Step 3: Commit the implementation**

```bash
git add -- AiVision/features/detect_logistics_single_person/consumer.py AiVision/platform/orchestrator.py AiVision/api/compat.py AiVision/tests/test_logistics_single_person.py AiVision/tests/test_logistics_monitor_status_api.py unified_frontend/src/lib/aivision.ts unified_frontend/src/components/AiVisionMonitor.tsx unified_frontend/src/components/logistics_single_person/monitorState.ts unified_frontend/src/components/logistics_single_person/useLogisticsSinglePersonMonitor.ts unified_frontend/src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx unified_frontend/src/sections/LogisticsSinglePersonDetectionSection.tsx unified_frontend/tests/logistics-single-person-monitor-contract.test.mjs docs/superpowers/plans/2026-08-06-logistics-single-person-monitor-ui.md
git commit -m "feat: refresh logistics single-person monitor UI"
```
