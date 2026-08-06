# Platform Overview Interaction Refinements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-column scrollable camera grid with hover actions, compress global exception push into a wrapping row, and render the five latest alarms as a severity timeline.

**Architecture:** Keep all changes in the existing `HomeSection` and its source contract test. Extend `OverviewState` with `recentAlarms`, derive severity and location through pure helpers, and preserve all existing camera and settings handlers.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Node test runner, Vite

---

### Task 1: Add failing interaction contracts

**Files:**
- Modify: `unified_frontend/tests/overview-layout-contract.test.mjs`

- [x] **Step 1: Add camera grid and hover-action assertions**

Add a test that scopes to the camera list and requires these contracts:

```js
assert.match(cameraList, /grid-cols-1/)
assert.match(cameraList, /lg:grid-cols-2/)
assert.match(cameraList, /\bgroup\b/)
assert.match(cameraList, /opacity-0/)
assert.match(cameraList, /group-hover:opacity-100/)
assert.match(cameraList, /group-focus-within:opacity-100/)
assert.match(cameraList, /transition-opacity/)
```

- [x] **Step 2: Add push-row assertions**

Require a `flex flex-wrap` container containing, in order, `Bell`, the title and description, `Switch`, `Input`, and the save `Button`. Require light slate and dark slate backgrounds.

- [x] **Step 3: Add recent-alarm timeline assertions**

Require `recentAlarms`, `alarmItems.slice(0, 5)`, `getAlarmSeverity`, `getAlarmLocation`, red/yellow/gray dot classes, a vertical line, `overview.recentAlarms.map`, and `onClick={() => onNavigate('alarms')}`.

- [x] **Step 4: Verify RED**

Run: `node --test tests/overview-layout-contract.test.mjs`

Expected: FAIL because the current list is single-column, actions are always visible, push settings use two stacked rows, and overview stores only `latestAlarm`.

### Task 2: Implement the camera grid and push row

**Files:**
- Modify: `unified_frontend/src/sections/HomeSection.tsx`
- Test: `unified_frontend/tests/overview-layout-contract.test.mjs`

- [x] **Step 1: Convert the camera scroller to a responsive grid**

Keep the existing scroll wrapper and add an inner grid:

```tsx
<div className="grid grid-cols-1 lg:grid-cols-2">
  {aiVisionCameras.map(...)}
</div>
```

Give each camera item `group relative` and borders that visually divide rows and columns without changing its key or handlers.

- [x] **Step 2: Hide admin actions until interaction**

Wrap the existing buttons with:

```tsx
<div className="flex shrink-0 items-center gap-2 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100">
```

Do not change the edit and delete callbacks or disabled state.

- [x] **Step 3: Compress global exception push**

Replace the stacked layout with one `flex flex-wrap items-center` bar. Use a leading icon, a flexible title/description block, the existing switch, an input with `min-w-[220px] flex-1`, and the existing save button styled with `bg-[#001b43]`. Render success/error messages below the row inside the same container.

- [x] **Step 4: Run the focused test**

Run: `node --test tests/overview-layout-contract.test.mjs`

Expected: camera and push-row assertions pass; timeline assertions remain red.

### Task 3: Implement recent alarm timeline

**Files:**
- Modify: `unified_frontend/src/sections/HomeSection.tsx`
- Test: `unified_frontend/tests/overview-layout-contract.test.mjs`

- [x] **Step 1: Extend overview state**

Replace `latestAlarm` with:

```ts
recentAlarms: AlarmEvent[]
```

Initialize it to `[]` and set it in `loadOverview` with `alarmItems.slice(0, 5)`.

- [x] **Step 2: Add pure display helpers**

Implement:

```ts
type AlarmSeverity = 'critical' | 'warning' | 'normal'

function getAlarmSeverity(eventType: string): AlarmSeverity {
  if (new Set(['blocks', 'guard_absent']).has(eventType)) return 'critical'
  if (new Set(['detect_door', 'detect_phone', 'guard_phone_use', 'guard_prone_sleep', 'security_vlm_non_compliant', 'security_vlm_error']).has(eventType)) return 'warning'
  return 'normal'
}

function getAlarmLocation(alarm: AlarmEvent) {
  return alarm.camera_name || alarm.site_name || alarm.camera_no || '未知位置'
}
```

Use module-level sets rather than creating new sets on every helper call.

- [x] **Step 3: Render the timeline**

Map over `overview.recentAlarms`. Render an absolute vertical slate line, a white-ringed dot with red/yellow/gray tone based on `getAlarmSeverity`, and time/title/location text. Keep the no-alarm state.

- [x] **Step 4: Add the alarm navigation footer**

Add a full-width text button at the bottom:

```tsx
<button type="button" onClick={() => onNavigate('alarms')}>
  查看全部报警 <ArrowRight />
</button>
```

- [x] **Step 5: Verify GREEN**

Run: `node --test tests/overview-layout-contract.test.mjs`

Expected: PASS with zero failures.

### Task 4: Verify and commit

**Files:**
- Modify: `unified_frontend/src/sections/HomeSection.tsx`
- Modify: `unified_frontend/tests/overview-layout-contract.test.mjs`
- Add: `docs/superpowers/plans/2026-08-06-overview-interactions.md`

- [x] **Step 1: Run all contract tests**

Run: `node --test tests/*.test.mjs`

Expected: 3 test files pass with zero failures.

- [x] **Step 2: Run lint**

Run: `npm run lint`

Expected: zero errors; the four existing logistics Hook dependency warnings may remain.

- [x] **Step 3: Build production assets**

Run: `npm run build`

Expected: TypeScript and Vite exit successfully.

- [x] **Step 4: Inspect the exact diff**

Run: `git diff --check && git status --short && git diff --stat`

Expected: only `HomeSection.tsx`, its contract test, and this plan are uncommitted.

- [x] **Step 5: Commit**

```bash
git add -- unified_frontend/src/sections/HomeSection.tsx unified_frontend/tests/overview-layout-contract.test.mjs docs/superpowers/plans/2026-08-06-overview-interactions.md
git commit -m "feat: refine overview camera and alarm interactions"
```
