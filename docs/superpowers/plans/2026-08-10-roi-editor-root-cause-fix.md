# ROI Editor Root-Cause Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplicate annotated ROI lines and prevent logistics polling from overwriting an unsaved ROI draft without adding new UI controls.

**Architecture:** The shared ROI editor will always request a raw camera frame and remain the only renderer of editable ROI geometry. Logistics per-camera configuration loading will be keyed by stable feature, channel ID, and camera ID primitives rather than the polled channel-detail object.

**Tech Stack:** React 19, TypeScript, Node.js built-in test runner, ESLint, Vite

---

## File Map

- Create `unified_frontend/tests/roi-editor-root-cause.test.mjs`: source-contract regressions for raw preview frames and stable logistics configuration identity.
- Modify `unified_frontend/src/components/AiVisionRoiEditor.tsx`: remove the feature input and build raw-frame preview URLs.
- Modify `unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx`: remove the editor feature prop and make configuration hydration depend on stable IDs.
- Modify `unified_frontend/src/sections/DoorDetectionSection.tsx`: remove the obsolete ROI editor feature prop.
- Modify `unified_frontend/src/sections/FaceDetectionSection.tsx`: remove the obsolete ROI editor feature prop.
- Modify `unified_frontend/src/sections/HumanDetectionSection.tsx`: remove the obsolete ROI editor feature prop.
- Modify `unified_frontend/src/sections/IntrusionDetectionSection.tsx`: remove the obsolete ROI editor feature prop.
- Modify `unified_frontend/src/sections/PhoneDetectionSection.tsx`: remove the obsolete ROI editor feature prop.

### Task 1: Add failing raw-frame regression

**Files:**
- Create: `unified_frontend/tests/roi-editor-root-cause.test.mjs`
- Test: `unified_frontend/tests/roi-editor-root-cause.test.mjs`

- [ ] **Step 1: Write the failing test**

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('ROI editor uses a raw frame and exposes no feature prop', () => {
  const editor = read('src/components/AiVisionRoiEditor.tsx')
  assert.match(editor, /aiVisionFrameUrl\(cameraKey, undefined, nonce\)/)
  assert.doesNotMatch(editor, /feature\?: string/)
})
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd unified_frontend && node --test tests/roi-editor-root-cause.test.mjs`

Expected: FAIL because the editor still calls `aiVisionFrameUrl(cameraKey, feature, nonce)` and declares `feature?: string`.

- [ ] **Step 3: Implement raw-frame preview semantics**

In `AiVisionRoiEditor.tsx`, remove `feature?: string` from `AiVisionRoiEditorProps`, remove `feature` from component destructuring, and replace the preview memo with:

```tsx
const frameUrl = useMemo(
  () => (cameraKey ? aiVisionFrameUrl(cameraKey, undefined, nonce) : ''),
  [cameraKey, nonce],
)
```

Remove only the `feature` property from each `AiVisionRoiEditor` JSX invocation in the five detection sections and `LogisticsChannelConfigView.tsx`. Do not alter `AiVisionMonitor` or `FeatureCameraManager` feature properties.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `cd unified_frontend && node --test tests/roi-editor-root-cause.test.mjs`

Expected: PASS.

### Task 2: Add failing logistics draft-preservation regression

**Files:**
- Modify: `unified_frontend/tests/roi-editor-root-cause.test.mjs`
- Modify: `unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx`

- [ ] **Step 1: Add the failing test**

```javascript
test('logistics ROI hydration depends on stable IDs instead of polled objects', () => {
  const config = read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')
  const hydration = config.slice(
    config.indexOf("useEffect(() => {\n    if (!selectedCamera"),
    config.indexOf('  const invalidateMemberships'),
  )

  assert.match(config, /const selectedChannelDetailId = selectedChannelDetail\?\.id \?\? null/)
  assert.match(hydration, /getLogisticsCameraConfig\(feature, selectedChannelDetailId, selectedCameraId\)/)
  assert.match(hydration, /\[feature, selectedCameraId, selectedChannelDetailId\]/)
  assert.doesNotMatch(hydration, /\[feature, selectedCamera, selectedChannelDetail\]/)
})
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd unified_frontend && node --test tests/roi-editor-root-cause.test.mjs`

Expected: FAIL because hydration currently depends on `selectedCamera` and the polled `selectedChannelDetail` object.

- [ ] **Step 3: Implement stable hydration identity**

Add the stable channel primitive near the existing selected-camera derivation:

```tsx
const selectedChannelDetailId = selectedChannelDetail?.id ?? null
```

Change the configuration hydration effect to use IDs only:

```tsx
useEffect(() => {
  if (selectedCameraId === null || selectedChannelDetailId === null) {
    setCameraConfig(null)
    setRoiJson('[]')
    return
  }
  let active = true
  setCameraConfig(null)
  getLogisticsCameraConfig(feature, selectedChannelDetailId, selectedCameraId)
    .then((result) => {
      if (!active) return
      setCameraConfig(result)
      setRoiJson(JSON.stringify(result.config.value.roi_pos ?? []))
    })
    .catch((reason) => active && setMessage(`逐路 ROI 读取失败：${messageOf(reason)}`))
  return () => { active = false }
}, [feature, selectedCameraId, selectedChannelDetailId])
```

- [ ] **Step 4: Run the test and verify GREEN**

Run: `cd unified_frontend && node --test tests/roi-editor-root-cause.test.mjs`

Expected: both tests PASS.

### Task 3: Verify integration and commit

**Files:**
- Test: `unified_frontend/tests/roi-editor-root-cause.test.mjs`
- Test: `unified_frontend/tests/logistics-channel-ui-contract.test.mjs`

- [ ] **Step 1: Run focused regression tests**

Run: `cd unified_frontend && node --test tests/roi-editor-root-cause.test.mjs tests/logistics-channel-*.test.mjs`

Expected: all test files PASS with zero failures.

- [ ] **Step 2: Run targeted lint**

Run: `cd unified_frontend && npx eslint src/components/AiVisionRoiEditor.tsx src/components/logistics_single_person/LogisticsChannelConfigView.tsx src/sections/DoorDetectionSection.tsx src/sections/FaceDetectionSection.tsx src/sections/HumanDetectionSection.tsx src/sections/IntrusionDetectionSection.tsx src/sections/PhoneDetectionSection.tsx tests/roi-editor-root-cause.test.mjs`

Expected: exit code 0 with no errors.

- [ ] **Step 3: Run production build**

Run: `cd unified_frontend && npm run build`

Expected: TypeScript and Vite build exit with code 0. Existing non-fatal PostCSS warnings may remain.

- [ ] **Step 4: Inspect final scope**

Run: `git diff --check && git status --short && git diff -- unified_frontend docs/superpowers/plans/2026-08-10-roi-editor-root-cause-fix.md`

Expected: no whitespace errors; only the planned ROI files plus the user's pre-existing `AGENTS.md` modification are shown.

- [ ] **Step 5: Commit implementation files only**

```bash
git add -- unified_frontend/tests/roi-editor-root-cause.test.mjs unified_frontend/src/components/AiVisionRoiEditor.tsx unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx unified_frontend/src/sections/DoorDetectionSection.tsx unified_frontend/src/sections/FaceDetectionSection.tsx unified_frontend/src/sections/HumanDetectionSection.tsx unified_frontend/src/sections/IntrusionDetectionSection.tsx unified_frontend/src/sections/PhoneDetectionSection.tsx
git commit -m "fix: preserve editable ROI drafts"
```
