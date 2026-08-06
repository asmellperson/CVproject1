# Guard Monitor Left Column Card Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the existing detection-detail and recent-alarm cards below the real-time detection card in the monitor dashboard's left column.

**Architecture:** Keep `MonitorSection` as the owner of all existing status data and handlers. Change only JSX placement: move the two existing cards into the current `space-y-5` left-column container, preserve their `site` condition, and remove the obsolete lower grid wrapper.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Node test runner, Vite

---

### Task 1: Lock the card-order contract

**Files:**
- Modify: `unified_frontend/tests/guard-monitor-ui-contract.test.mjs`

- [x] **Step 1: Add a failing source-order test**

Add a test that locates the left-column marker, `实时检测项`, `检测详情`, `最近报警`, and the video-card marker in `MonitorSection.tsx`, then asserts this order:

```js
test('places details and alarms below real-time items in the left column', () => {
  const leftColumn = monitor.indexOf('<div className="space-y-5">')
  const realtimeItems = monitor.indexOf('实时检测项', leftColumn)
  const details = monitor.indexOf('检测详情', realtimeItems)
  const recentAlarm = monitor.indexOf('最近报警', details)
  const video = monitor.indexOf("'overflow-hidden lg:col-span-2'", recentAlarm)

  assert.ok(leftColumn >= 0)
  assert.ok(leftColumn < realtimeItems)
  assert.ok(realtimeItems < details)
  assert.ok(details < recentAlarm)
  assert.ok(recentAlarm < video)
  assert.doesNotMatch(monitor, /<section className="grid gap-5 lg:grid-cols-2">/)
})
```

- [x] **Step 2: Verify the test fails before implementation**

Run:

```bash
cd unified_frontend
node tests/guard-monitor-ui-contract.test.mjs
```

Expected: the new card-order test fails because both cards currently follow the video card in a lower two-column section.

### Task 2: Move the existing cards

**Files:**
- Modify: `unified_frontend/src/sections/MonitorSection.tsx`

- [x] **Step 1: Move both cards into the left column**

Immediately after the existing real-time detection card, add the existing detection-detail and recent-alarm card JSX inside the current left-column `space-y-5` container. Wrap them in the existing `site && (...)` condition without changing any status expressions:

```tsx
{site && (
  <>
    {/* existing 检测详情 card */}
    {/* existing 最近报警 card */}
  </>
)}
```

Remove the original lower `<section className="grid gap-5 lg:grid-cols-2">` wrapper and its duplicate card locations. Do not edit card content, progress bindings, alarm bindings, requests, effects, handlers, or video classes.

- [x] **Step 2: Verify the focused contract passes**

Run:

```bash
cd unified_frontend
node tests/guard-monitor-ui-contract.test.mjs
```

Expected: all guard-monitor contract tests pass.

### Task 3: Regression verification and commit

**Files:**
- Modify: `docs/superpowers/plans/2026-08-06-guard-monitor-left-column.md`
- Modify: `unified_frontend/tests/guard-monitor-ui-contract.test.mjs`
- Modify: `unified_frontend/src/sections/MonitorSection.tsx`

- [x] **Step 1: Run complete frontend verification**

```bash
cd unified_frontend
node --test tests/*.test.mjs
npm run build
npm run lint
```

Expected: all tests and production build pass; lint reports zero errors, allowing the four known out-of-scope hooks warnings.

- [x] **Step 2: Check the exact change scope**

```bash
git diff --check
git status --short
```

Expected: only the plan, guard-monitor contract test, and `MonitorSection.tsx` are modified after the already committed design record.

- [ ] **Step 3: Commit the implementation**

```bash
git add -- docs/superpowers/plans/2026-08-06-guard-monitor-left-column.md unified_frontend/tests/guard-monitor-ui-contract.test.mjs unified_frontend/src/sections/MonitorSection.tsx
git commit -m "feat: move guard details into monitor sidebar"
```
