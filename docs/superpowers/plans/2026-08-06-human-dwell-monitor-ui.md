# Human Dwell Monitor UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the existing human dwell tracker state through the current feature-status route and rebuild the human dwell monitor tab with the approved dashboard UI while preserving all frame, configuration, and alarm behavior.

**Architecture:** `DwellDetectionConsumer` publishes a read-only snapshot from its existing trackers; the generic orchestrator status response passes through dwell duration and threshold. `AiVisionMonitor` keeps the unchanged camera/frame lifecycle and opts into a focused human-dwell hook/view. Pure frontend state helpers derive alarm/leave timeline events and today's existing alarms.

**Tech Stack:** Python 3, FastAPI, pytest, React 19, TypeScript, Tailwind CSS, lucide-react, Node test runner, Vite

---

### Task 1: Publish human dwell tracker snapshots

**Files:**
- Modify: `AiVision/features/_base/dwell_consumer.py`
- Create: `AiVision/tests/test_dwell_monitor_status.py`

- [x] Write failing tests for `build_dwell_monitor_snapshot`, covering two visible tracks with different `first_seen` values, an alarmed track, missing tracks, threshold, and fixed `updated_at`.
- [x] Run `cd AiVision && pytest -q tests/test_dwell_monitor_status.py` and verify import failure.
- [x] Implement a pure snapshot helper that counts only `lost == 0` tracks belonging to the requested camera, calculates the longest dwell time, exposes `alarm`, `reason`, `duration_seconds`, `threshold_seconds`, and `updated_at_s`.
- [x] Add `monitor_status` storage to `DwellDetectionConsumer`; update it at the start of `post_process` using the existing `shm_name`, config `MAX_TIME`, and trackers. Add a copy-returning `get_monitor_status(camera_key)` method. Do not change `_process`, tracker updates, drawing, or `_handle_alarm`.
- [x] Re-run the focused test and verify it passes.

### Task 2: Pass dwell fields through the existing status route

**Files:**
- Modify: `AiVision/platform/orchestrator.py`
- Modify: `AiVision/tests/test_logistics_monitor_status_api.py`

- [x] Add failing assertions that a fresh snapshot returns `duration_seconds` and `threshold_seconds`, while a stale snapshot returns both as `None`.
- [x] Run the focused API test and verify failure for missing fields.
- [x] Extend `get_feature_monitor_status` response dictionaries with only these optional display fields, reading them from the existing snapshot and preserving all current fields/path/freshness behavior.
- [x] Run `pytest -q tests/test_dwell_monitor_status.py tests/test_logistics_monitor_status_api.py tests/test_camera_frame_response.py` and verify all pass.

### Task 3: Add typed frontend state and event derivation

**Files:**
- Modify: `unified_frontend/src/lib/aivision.ts`
- Create: `unified_frontend/src/components/human_dwell/monitorState.ts`
- Create: `unified_frontend/src/components/human_dwell/useHumanDwellMonitor.ts`
- Create: `unified_frontend/tests/human-dwell-monitor-contract.test.mjs`

- [x] Write failing source/behavior-contract assertions for `AiVisionHumanDwellStatus`, the existing status URL, timeout/leave labels, local-today alarm filtering, serialized one-second status polling, and five-second alarm polling.
- [x] Run `node tests/human-dwell-monitor-contract.test.mjs` and verify RED.
- [x] Add the typed status request without changing existing requests.
- [x] Implement pure state helpers that create one red event when `alarm` changes false→true, one gray event when a non-alarmed presence changes to zero, de-duplicate stable states, cap events at 8, and filter `detect_human` alarms by current camera/local date.
- [x] Implement a serialized recursive-`setTimeout` hook; isolate status/events by camera and retain the last successful alarm list.
- [x] Run the focused contract and `npm run build`.

### Task 4: Build and integrate the dashboard view

**Files:**
- Create: `unified_frontend/src/components/human_dwell/HumanDwellMonitorView.tsx`
- Modify: `unified_frontend/src/components/AiVisionMonitor.tsx`
- Modify: `unified_frontend/src/sections/HumanDetectionSection.tsx`
- Modify: `unified_frontend/tests/human-dwell-monitor-contract.test.mjs`

- [x] Extend the failing contract for the four metric labels; `grid-cols-2 lg:grid-cols-4`; left-column cards; `lg:col-span-2`; video header pills; cyan ROI styles/label; vignette; timestamp; and red timeout pill.
- [x] Assert `AiVisionMonitor` still contains the exact frame URL, 200ms recursive frame schedule, request abort timeout, Blob cleanup, image-size reading, and default/logistics presentations.
- [x] Implement the view using existing camera selection/refresh callbacks, `featureValue.MAX_TIME`, typed status, events, alarm summary, passed frame content, polygons, and frame coordinate size.
- [x] Add `presentation="human-dwell"` to `AiVisionMonitor`. Suppress only its generic ROI SVG in that mode, pass the unchanged frame image plus existing polygon coordinates to the new view, and leave all frame effects untouched.
- [x] Restyle only the outer title/primary tabs in `HumanDetectionSection`; pass the presentation prop and leave all nested configuration JSX/handlers unchanged.
- [x] Run the focused contract and production build.

### Task 5: Verify, review, and commit

**Files:**
- Modify: all files above
- Modify: `docs/superpowers/plans/2026-08-06-human-dwell-monitor-ui.md`

- [x] Run backend verification: `cd AiVision && pytest -q tests/test_dwell_monitor_status.py tests/test_logistics_monitor_status_api.py tests/test_camera_frame_response.py`.
- [x] Run frontend verification: `cd unified_frontend && node --test tests/*.test.mjs && npm run build && npm run lint`.
- [x] Run `git diff --check` and review that frame/config/alarm code and the default/logistics monitor paths are unchanged.
- [x] Request independent code review; fix all valid Critical/Important findings.
- [ ] Commit exact changed files with `git commit -m "feat: refresh human dwell monitor UI"`.
