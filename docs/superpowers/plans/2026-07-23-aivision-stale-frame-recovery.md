# AiVision Stale Frame Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop AiVision monitoring endpoints from serving indefinitely stale annotated frames and make the frontend visibly recover from frame failures without retaining a misleading frozen image.

**Architecture:** Keep frame freshness ownership in `Orchestrator.get_camera_frame_info`, where annotated and raw timestamps are already available. Add a small frontend frame-request helper for preview parameters and timeout scheduling, then make `AiVisionMonitor` clear stale object URLs on failure while retaining its existing retry loop.

**Tech Stack:** Python 3, pytest, FastAPI response semantics, React 19, TypeScript 5.9, Vite 7.

---

## File Structure

- Create `AiVision/tests/test_orchestrator_camera_frame.py`: regression tests for annotated/raw frame freshness selection.
- Modify `AiVision/platform/orchestrator.py`: reject expired annotated frames and return the most recent known timestamp when no frame is usable.
- Create `unified_frontend/src/components/AiVisionMonitor.frame.ts`: focused preview URL and request-timeout helpers.
- Create `unified_frontend/src/components/AiVisionMonitor.frame.test.ts`: standalone TypeScript regression tests for those helpers.
- Modify `unified_frontend/src/components/AiVisionMonitor.tsx`: use bounded preview requests and clear the last object URL on failure.

### Task 1: Backend Frame Freshness Regression

**Files:**
- Create: `AiVision/tests/test_orchestrator_camera_frame.py`
- Modify: `AiVision/platform/orchestrator.py:355-373`

- [ ] **Step 1: Write the failing tests**

```python
import importlib
import sys
from types import SimpleNamespace


sys.modules.pop("platform", None)
orchestrator_module = importlib.import_module("platform.orchestrator")
Orchestrator = orchestrator_module.Orchestrator


def _orchestrator(*, raw, raw_updated_at, annotated, annotated_updated_at):
    instance = object.__new__(Orchestrator)
    instance.consumers = {
        "detect_logistics_single_person": SimpleNamespace(
            result_dict={"logistics": annotated} if annotated is not None else {},
            result_updated_at={"logistics": annotated_updated_at} if annotated is not None else {},
        )
    }
    orchestrator_module.frame_reader_registry.latest_frames = (
        {"logistics": raw} if raw is not None else {}
    )
    orchestrator_module.frame_reader_registry.latest_frame_times = (
        {"logistics": raw_updated_at} if raw_updated_at else {}
    )
    return instance


def test_missing_raw_frame_does_not_return_expired_annotated_frame(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    annotated = object()
    instance = _orchestrator(
        raw=None,
        raw_updated_at=0.0,
        annotated=annotated,
        annotated_updated_at=90.0,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (None, 90.0)


def test_fresh_annotated_frame_is_preferred(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    raw, annotated = object(), object()
    instance = _orchestrator(
        raw=raw,
        raw_updated_at=99.0,
        annotated=annotated,
        annotated_updated_at=99.5,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (annotated, 99.5)


def test_expired_annotated_frame_falls_back_to_fresh_raw(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    raw, annotated = object(), object()
    instance = _orchestrator(
        raw=raw,
        raw_updated_at=99.0,
        annotated=annotated,
        annotated_updated_at=90.0,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (raw, 99.0)


def test_all_expired_frames_return_latest_known_timestamp(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    instance = _orchestrator(
        raw=object(),
        raw_updated_at=80.0,
        annotated=object(),
        annotated_updated_at=90.0,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (None, 90.0)
```

- [ ] **Step 2: Run tests and verify the regression test fails**

Run:

```bash
cd AiVision
uv run pytest tests/test_orchestrator_camera_frame.py -q
```

Expected: `test_missing_raw_frame_does_not_return_expired_annotated_frame` fails because the old annotated object is returned.

- [ ] **Step 3: Implement minimal freshness selection**

Replace the selection body in `get_camera_frame_info` with:

```python
now = time.time()
raw = frame_reader_registry.latest_frames.get(shm_name)
raw_updated_at = frame_reader_registry.latest_frame_times.get(shm_name, 0.0)
raw_is_fresh = raw is not None and raw_updated_at > 0 and now - raw_updated_at <= 10.0
annotated_updated_at = 0.0

if feature and feature in self.consumers:
    consumer = self.consumers[feature]
    annotated = consumer.result_dict.get(shm_name)
    annotated_updated_at = consumer.result_updated_at.get(shm_name, 0.0)
    annotated_is_fresh = (
        annotated is not None
        and annotated_updated_at > 0
        and now - annotated_updated_at <= 2.0
    )
    if annotated_is_fresh:
        return annotated, annotated_updated_at

if raw_is_fresh:
    return raw, raw_updated_at
return None, max(raw_updated_at, annotated_updated_at)
```

- [ ] **Step 4: Run focused and adjacent backend tests**

Run:

```bash
cd AiVision
uv run pytest tests/test_orchestrator_camera_frame.py tests/test_orchestrator_camera_update.py tests/test_logistics_single_person.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the backend regression fix**

```bash
git add AiVision/tests/test_orchestrator_camera_frame.py AiVision/platform/orchestrator.py
git commit -m "fix: reject stale aivision annotated frames"
```

### Task 2: Frontend Bounded Frame Requests

**Files:**
- Create: `unified_frontend/src/components/AiVisionMonitor.frame.ts`
- Create: `unified_frontend/src/components/AiVisionMonitor.frame.test.ts`
- Modify: `unified_frontend/src/components/AiVisionMonitor.tsx:24-184`

- [ ] **Step 1: Write the failing standalone TypeScript test**

```typescript
import { buildAiVisionPreviewFrameUrl, scheduleFrameRequestAbort } from './AiVisionMonitor.frame'

function assertEqual(actual: unknown, expected: unknown) {
  if (actual !== expected) throw new Error(`expected ${String(expected)}, got ${String(actual)}`)
}

assertEqual(
  buildAiVisionPreviewFrameUrl('logistics camera', 'detect_logistics_single_person', 123),
  '/api/aivision/cameras/logistics%20camera/frame.jpg?feature=detect_logistics_single_person&t=123&max_width=960&quality=72',
)

const controller = new AbortController()
let scheduledDelay = 0
let scheduledCallback: (() => void) | undefined
scheduleFrameRequestAbort(controller, 5000, (callback, delay) => {
  scheduledCallback = callback
  scheduledDelay = delay
  return 1
})

assertEqual(scheduledDelay, 5000)
assertEqual(controller.signal.aborted, false)
scheduledCallback?.()
assertEqual(controller.signal.aborted, true)
```

- [ ] **Step 2: Compile the test and verify it fails because the helper is missing**

Run:

```bash
cd unified_frontend
FRONTEND_TEST_DIR="$(mktemp -d /tmp/aivision-monitor-frame-test.XXXXXX)"
./node_modules/.bin/tsc \
  --target ES2022 \
  --module commonjs \
  --moduleResolution node \
  --lib ES2022,DOM \
  --skipLibCheck \
  --outDir "$FRONTEND_TEST_DIR" \
  src/components/AiVisionMonitor.frame.test.ts \
  src/components/AiVisionMonitor.frame.ts
```

Expected: compilation fails because `AiVisionMonitor.frame.ts` and its exports do not exist.

- [ ] **Step 3: Add the minimal helper implementation**

```typescript
import { aiVisionFrameUrl } from '../lib/aivision'

export const PREVIEW_MAX_WIDTH = 960
export const PREVIEW_QUALITY = 72
export const FRAME_REQUEST_TIMEOUT_MS = 5000

type ScheduleTimeout = (callback: () => void, delay: number) => ReturnType<typeof setTimeout>

export function buildAiVisionPreviewFrameUrl(cameraKey: string, feature: string, nonce: number) {
  return aiVisionFrameUrl(cameraKey, feature, nonce, {
    maxWidth: PREVIEW_MAX_WIDTH,
    quality: PREVIEW_QUALITY,
  })
}

export function scheduleFrameRequestAbort(
  controller: AbortController,
  timeoutMs = FRAME_REQUEST_TIMEOUT_MS,
  schedule: ScheduleTimeout = setTimeout,
) {
  return schedule(() => controller.abort(), timeoutMs)
}
```

- [ ] **Step 4: Integrate the helper and clear stale UI state on failure**

In `AiVisionMonitor.tsx`:

- Import `buildAiVisionPreviewFrameUrl`, `FRAME_REQUEST_TIMEOUT_MS`, and `scheduleFrameRequestAbort`.
- Remove the local `PREVIEW_QUALITY` constant.
- Add `let requestTimeoutId: ReturnType<typeof setTimeout> | undefined` beside the existing retry timer.
- Build the request URL with `buildAiVisionPreviewFrameUrl(selectedCamera, feature, Date.now())`.
- Immediately after creating the controller, schedule its abort with `scheduleFrameRequestAbort(controller, FRAME_REQUEST_TIMEOUT_MS)`.
- After `response.blob()` succeeds, clear the request timeout before installing the new object URL.
- In the non-cancelled `catch` path, call `revokeFrameUrl()` and `setFrameSrc('')` before setting the failure message. Treat timeout aborts as failures; only suppress abort errors after the effect has been cancelled.
- In `finally` and effect cleanup, clear `requestTimeoutId` when present.

The catch condition must be:

```typescript
if (!cancelled) {
  revokeFrameUrl()
  setFrameSrc('')
  setMessage('画面读取失败：请确认 AiVision 后端已启动、摄像头运行中，并且该检测功能已启用。')
}
```

- [ ] **Step 5: Compile and execute the helper regression test**

Run:

```bash
cd unified_frontend
FRONTEND_TEST_DIR="$(mktemp -d /tmp/aivision-monitor-frame-test.XXXXXX)"
./node_modules/.bin/tsc \
  --target ES2022 \
  --module commonjs \
  --moduleResolution node \
  --lib ES2022,DOM \
  --skipLibCheck \
  --outDir "$FRONTEND_TEST_DIR" \
  src/components/AiVisionMonitor.frame.test.ts \
  src/components/AiVisionMonitor.frame.ts \
  src/lib/aivision.ts
node "$FRONTEND_TEST_DIR/components/AiVisionMonitor.frame.test.js"
```

Expected: compilation and execution exit with status 0.

- [ ] **Step 6: Run frontend type/build verification**

Run:

```bash
cd unified_frontend
npm run build
```

Expected: TypeScript and Vite build complete successfully.

- [ ] **Step 7: Commit the frontend recovery fix**

```bash
git add unified_frontend/src/components/AiVisionMonitor.frame.ts \
  unified_frontend/src/components/AiVisionMonitor.frame.test.ts \
  unified_frontend/src/components/AiVisionMonitor.tsx
git commit -m "fix: recover aivision monitor from stale frames"
```

### Task 3: Full Focused Verification and Handoff

**Files:**
- Verify only; no planned source changes.

- [ ] **Step 1: Run the complete AiVision test suite**

```bash
cd AiVision
uv run pytest -q
```

Expected: all AiVision tests pass.

- [ ] **Step 2: Run frontend lint and build**

```bash
cd unified_frontend
npm run lint
npm run build
```

Expected: both commands exit with status 0.

- [ ] **Step 3: Inspect the final scoped diff**

```bash
git diff HEAD~2 --check
git diff HEAD~2 -- AiVision/platform/orchestrator.py \
  AiVision/tests/test_orchestrator_camera_frame.py \
  unified_frontend/src/components/AiVisionMonitor.tsx \
  unified_frontend/src/components/AiVisionMonitor.frame.ts \
  unified_frontend/src/components/AiVisionMonitor.frame.test.ts
```

Expected: no whitespace errors; changes are limited to stale-frame selection, bounded preview requests, failure-state cleanup, and regression tests.

- [ ] **Step 4: Provide deployment verification commands**

After deploying to the formal server, verify from an authenticated browser or session:

```text
GET /api/aivision/cameras/{camera_key}/frame.jpg?feature=detect_logistics_single_person&max_width=960&quality=72
```

Expected behavior:

- New frames return `200 image/jpeg`.
- A camera with no fresh raw or annotated frame returns `503` rather than a cached historical JPEG.
- The monitor clears the old picture, shows the failure message, and automatically reconnects when fresh frames resume.
