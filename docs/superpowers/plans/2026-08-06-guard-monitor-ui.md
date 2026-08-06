# Guard Monitor UI Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the guard-behavior monitoring presentation to match the approved dashboard layout while preserving every API request, field binding, control handler, permission check, and stitched-frame playback behavior.

**Architecture:** `GuardBehaviorSection` owns the page title and segmented tabs. `MonitorSection` retains all effects and handlers, while focused presentational components in `components/guard_room/GuardMonitorUi.tsx` render repeated cards, status rows, and pills without making requests or holding business state.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Radix Tabs/Select, lucide-react, Node test runner, Vite

---

### Task 1: Lock the UI and playback contract

**Files:**
- Create: `unified_frontend/tests/guard-monitor-ui-contract.test.mjs`
- Modify: `unified_frontend/src/sections/GuardBehaviorSection.tsx`
- Modify: `unified_frontend/src/sections/MonitorSection.tsx`
- Create: `unified_frontend/src/components/guard_room/GuardMonitorUi.tsx`

- [x] **Step 1: Write the failing source contract**

Create a Node test that reads the three component sources and verifies:

```js
assert.match(guardPage, /通用电气保安行为规范监控与配置/)
assert.match(guardPage, /行为分析监控面板/)
assert.match(guardPage, /rounded-full border border-slate-200\/70 bg-white p-1/)
assert.match(monitor, /grid grid-cols-2 gap-4 lg:grid-cols-4/)
assert.match(monitor, /grid gap-5 lg:grid-cols-3/)
assert.match(monitor, /lg:col-span-2/)
assert.match(monitor, /status\?\.counts\.persons/)
assert.match(monitor, /status\?\.metrics\.person_confidence/)
assert.match(monitor, /status\?\.decisions\.phone_use/)
assert.match(monitor, /status\?\.decisions\.prone_sleep/)
assert.match(monitor, /status\?\.decisions\.vehicle_unattended/)
assert.match(monitor, /className="block h-auto w-full/)
assert.doesNotMatch(monitor, /aspect-video|object-cover/)
assert.match(monitor, /检测功能已关闭/)
assert.match(monitor, /点击左侧『检测开启』恢复行为分析/)
assert.match(monitor, /1080P · H\.265/)
assert.match(ui, /GuardMonitorStatCard/)
assert.match(ui, /GuardDetectionStatusRow/)
assert.match(ui, /GuardVideoStatusPill/)
```

Also preserve the behavior contract:

```js
assert.match(monitor, /getGuardRoomSiteStatus\(site\.id, department\)/)
assert.match(monitor, /startGuardRoomSiteRuntime\(site\.id\)/)
assert.match(monitor, /stopGuardRoomSiteRuntime\(site\.id\)/)
assert.match(monitor, /guardRoomSiteFrameUrl\(site\.id, department\)/)
assert.match(monitor, /window\.setInterval\(fetchStatus, POLL_MS\)/)
```

- [x] **Step 2: Run the contract and verify RED**

Run:

```bash
cd unified_frontend
node --test tests/guard-monitor-ui-contract.test.mjs
```

Expected: FAIL because the new UI component file and approved layout classes do not exist.

### Task 2: Build shared presentation components

**Files:**
- Create: `unified_frontend/src/components/guard_room/GuardMonitorUi.tsx`

- [x] **Step 1: Implement focused stat, row, and pill components**

Add typed components that accept already-computed labels and states:

```tsx
export function GuardMonitorStatCard(props: {
  label: string
  value: string
  detail: string
  icon: LucideIcon
  tone: 'emerald' | 'amber' | 'indigo' | 'rose'
  ping?: boolean
})

export function GuardDetectionStatusRow(props: {
  label: string
  icon: LucideIcon
  state: 'normal' | 'warning' | 'danger'
  stateLabel: string
})

export function GuardVideoStatusPill(props: {
  label: string
  state?: 'normal' | 'danger' | 'neutral'
  showDot?: boolean
})
```

All cards use `rounded-2xl border border-slate-200/70 bg-white shadow-sm`. These components contain no `fetch`, effects, site IDs, or API imports.

- [x] **Step 2: Run the focused contract**

Run `node --test tests/guard-monitor-ui-contract.test.mjs`.

Expected: still FAIL on page layout assertions, but the shared-component assertions pass.

### Task 3: Rebuild title and segmented tabs

**Files:**
- Modify: `unified_frontend/src/sections/GuardBehaviorSection.tsx`

- [x] **Step 1: Add the department-aware heading**

Render a header above `TabsContent` with general-electric and electronics-electrician titles. Keep existing `Tabs`, `MonitorSection`, `ConfigSection`, site CRUD handlers, and props unchanged.

- [x] **Step 2: Restyle the tab list**

Use a right-aligned `rounded-full border border-slate-200/70 bg-white p-1 shadow-sm` list. Each trigger uses `rounded-full px-4 py-1.5 text-slate-500` and `data-[state=active]:bg-[#132C72] data-[state=active]:text-white`.

- [x] **Step 3: Run the focused contract**

Run `node --test tests/guard-monitor-ui-contract.test.mjs`.

Expected: header and tab assertions pass; monitor layout assertions remain failing.

### Task 4: Recompose the live monitor dashboard

**Files:**
- Modify: `unified_frontend/src/sections/MonitorSection.tsx`

- [x] **Step 1: Preserve effects and derive display-only values**

Leave effects and handlers unchanged. Below `currentTime`, derive the display-only abnormal count and booleans from the existing status fields. Do not add API calls or change `BackendStatus`.

- [x] **Step 2: Render four statistic cards**

Use `grid grid-cols-2 gap-4 lg:grid-cols-4` and the shared stat component for camera status, persons/confidence, FPS/latency, and abnormal decisions.

- [x] **Step 3: Render the one-plus-two main grid**

Use `grid gap-5 lg:grid-cols-3`; place monitoring object, controls, and detection items in `space-y-5`, and place the video card in `lg:col-span-2`. Preserve site select values, handler bindings, permission checks, busy state, empty-site messaging, and disabled conditions.

- [x] **Step 4: Render the intrinsic-ratio stitched frame**

The frame wrapper uses only `relative overflow-hidden bg-slate-900`. The image uses `block h-auto w-full saturate-[.85]` plus paused grayscale/opacity classes. Add the vignette, status pills, FPS/LIVE header, codec pill, backend error overlay, and approved pause overlay. Do not render an SVG ROI or duplicate timestamp.

- [x] **Step 5: Preserve lower detail and alarm cards**

Keep current confidence progress values and `lastAlarm` bindings below the main grid, restyled with the global card system.

- [x] **Step 6: Run the focused contract and verify GREEN**

Run `node --test tests/guard-monitor-ui-contract.test.mjs`.

Expected: PASS.

### Task 5: Regression verification and commit

**Files:**
- Modify: `docs/superpowers/plans/2026-08-06-guard-monitor-ui.md`
- Modify: all files listed above

- [x] **Step 1: Run full verification**

```bash
cd unified_frontend
node --test tests/*.test.mjs
npm run build
npm run lint
```

Expected: all tests and build pass; lint has zero errors, allowing the four documented pre-existing hooks warnings.

- [x] **Step 2: Review scope**

```bash
git diff --check
git status --short
```

Confirm no API, type, backend, configuration-management, or media asset files changed.

- [x] **Step 3: Commit**

```bash
git add -- docs/superpowers/plans/2026-08-06-guard-monitor-ui.md unified_frontend/tests/guard-monitor-ui-contract.test.mjs unified_frontend/src/components/guard_room/GuardMonitorUi.tsx unified_frontend/src/sections/GuardBehaviorSection.tsx unified_frontend/src/sections/MonitorSection.tsx
git commit -m "feat: refresh guard monitor dashboard UI"
```
