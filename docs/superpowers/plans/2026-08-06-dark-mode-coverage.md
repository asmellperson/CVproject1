# Complete Dark Mode Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dark mode the first-visit default, preserve manual theme choices, and complete dark styling for every routed frontend page without changing backend, video, configuration, or detection behavior.

**Architecture:** Keep the existing class-based theme and `unified-frontend-theme` storage key. Align the pre-React bootstrap script and React hook on a dark fallback, then add explicit dark variants at reusable monitor-view boundaries and page-specific shells; use one source-contract test to prevent default-theme and coverage regressions.

**Tech Stack:** React 19, TypeScript 5.9, Tailwind CSS class dark mode, Node test runner, Vite

---

### Task 1: Default to dark while preserving the user's choice

**Files:**
- Create: `unified_frontend/tests/dark-mode-coverage.test.mjs`
- Modify: `unified_frontend/index.html`
- Modify: `unified_frontend/src/hooks/use-theme.ts`

- [x] **Step 1: Write the failing default-theme contracts**

Create a Node test that reads both theme entry points and asserts the fallback is explicitly dark while the existing storage key and persistence remain:

```js
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')
const html = await read('index.html')
const hook = await read('src/hooks/use-theme.ts')

test('defaults first visits to dark before and after React mounts', () => {
  assert.match(html, /const theme = stored === 'light' \|\| stored === 'dark'[\s\S]*\? stored[\s\S]*: 'dark'/)
  assert.doesNotMatch(html, /prefers-color-scheme/)
  assert.match(hook, /if \(typeof window === 'undefined'\) return 'dark'/)
  assert.match(hook, /return 'dark'/)
  assert.doesNotMatch(hook, /prefers-color-scheme/)
})

test('continues to read and persist the existing manual theme choice', () => {
  assert.match(hook, /unified-frontend-theme/)
  assert.match(hook, /stored === 'light' \|\| stored === 'dark'/)
  assert.match(hook, /window\.localStorage\.setItem\(STORAGE_KEY, theme\)/)
  assert.match(hook, /prev === 'dark' \? 'light' : 'dark'/)
})
```

- [x] **Step 2: Run the test and verify RED**

Run:

```bash
cd unified_frontend
node tests/dark-mode-coverage.test.mjs
```

Expected: FAIL because both files currently fall back to the operating-system preference or light during SSR.

- [x] **Step 3: Implement the shared dark fallback**

Change the bootstrap expression in `index.html` to:

```js
const theme = stored === 'light' || stored === 'dark' ? stored : 'dark'
```

Change `readInitialTheme` in `use-theme.ts` to:

```ts
function readInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return 'dark'
}
```

Initialize the state with `dark` for the server fallback:

```ts
const [theme, setThemeState] = useState<Theme>(() => (typeof window === 'undefined' ? 'dark' : readInitialTheme()))
```

- [x] **Step 4: Re-run the focused test**

Run `node tests/dark-mode-coverage.test.mjs`.

Expected: both default-theme and persistence tests pass.

### Task 2: Complete the four reusable monitoring views

**Files:**
- Modify: `unified_frontend/src/components/guard_room/GuardMonitorUi.tsx`
- Modify: `unified_frontend/src/components/feature_dashboard/FeatureDashboardMonitorView.tsx`
- Modify: `unified_frontend/src/components/human_dwell/HumanDwellMonitorView.tsx`
- Modify: `unified_frontend/src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx`
- Modify: `unified_frontend/tests/dark-mode-coverage.test.mjs`

- [x] **Step 1: Add failing shared-view coverage contracts**

Read the four files and assert each has dark card, foreground, muted text, border, and input treatment:

```js
test('shared monitor views define their own dark surfaces and typography', async () => {
  for (const path of [
    'src/components/guard_room/GuardMonitorUi.tsx',
    'src/components/feature_dashboard/FeatureDashboardMonitorView.tsx',
    'src/components/human_dwell/HumanDwellMonitorView.tsx',
    'src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx',
  ]) {
    const source = await read(path)
    assert.match(source, /dark:bg-slate-900/)
    assert.match(source, /dark:border-slate-800/)
    assert.match(source, /dark:text-slate-100/)
    assert.match(source, /dark:text-slate-(300|400)/)
  }
})
```

- [x] **Step 2: Run the focused test and verify RED**

Run `node tests/dark-mode-coverage.test.mjs`.

Expected: FAIL because the shared views currently contain no explicit dark variants.

- [x] **Step 3: Add dark styles at reusable boundaries**

Update each reusable card constant or card root using this exact surface pattern:

```ts
const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'
```

Apply the following mappings throughout the four views without changing JSX structure or callbacks:

```text
text-slate-950 -> text-slate-950 dark:text-slate-100
text-slate-700 -> text-slate-700 dark:text-slate-300
text-slate-600 -> text-slate-600 dark:text-slate-300
text-slate-500/400 -> keep light class and add dark:text-slate-400
border-slate-100/200 -> keep light class and add dark:border-slate-800
bg-slate-50/60 or bg-slate-100 -> add dark:bg-slate-950/60 or dark:bg-slate-800
bg-[#EAF0FE] -> add dark:bg-blue-950/60
```

The video canvas remains `bg-slate-950`; do not change ROI, line, timestamp, status color, event data, or click handlers.

- [x] **Step 4: Re-run focused tests and build**

Run:

```bash
node tests/dark-mode-coverage.test.mjs
npm run build
```

Expected: tests and TypeScript/Vite production build pass.

### Task 3: Adapt all detection-page shells

**Files:**
- Modify: `unified_frontend/src/sections/GuardBehaviorSection.tsx`
- Modify: `unified_frontend/src/sections/IntrusionDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/FaceDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/PhoneDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/DoorDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/HumanDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonElectronicsElectricianDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonElectricalComponentsDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonPreciousMetalRecyclingDetectionSection.tsx`
- Modify: `unified_frontend/tests/dark-mode-coverage.test.mjs`

- [x] **Step 1: Add failing Section shell contracts**

```js
test('every detection Section has a dark page shell', async () => {
  const files = [
    'GuardBehaviorSection.tsx', 'IntrusionDetectionSection.tsx', 'FaceDetectionSection.tsx',
    'PhoneDetectionSection.tsx', 'DoorDetectionSection.tsx', 'HumanDetectionSection.tsx',
    'LogisticsSinglePersonDetectionSection.tsx',
    'LogisticsSinglePersonElectronicsElectricianDetectionSection.tsx',
    'LogisticsSinglePersonElectricalComponentsDetectionSection.tsx',
    'LogisticsSinglePersonPreciousMetalRecyclingDetectionSection.tsx',
  ]
  for (const file of files) {
    const source = await read(`src/sections/${file}`)
    assert.match(source, /dark:bg-slate-950/)
    assert.match(source, /dark:text-slate-100/)
  }
})
```

- [x] **Step 2: Run the focused test and verify RED**

Run `node tests/dark-mode-coverage.test.mjs`.

Expected: FAIL for Section files that still have only the light shell.

- [x] **Step 3: Apply the common Section theme contract**

For full dashboard shells, extend the root, heading, subtitle, and main tab list as follows:

```tsx
<div className="... bg-[#F3F5FA] ... dark:bg-slate-950">
<h1 className="... text-slate-950 dark:text-slate-100">
<p className="... text-slate-500 dark:text-slate-400">
<TabsList className="... border-slate-200/70 bg-white ... dark:border-slate-800 dark:bg-slate-900">
```

For the three thin logistics wrapper Sections, add a dark shell/title class at their existing top-level container instead of adding or moving modules. Preserve all nested configuration tabs, feature names, camera filtering, and handlers byte-for-byte apart from class strings.

- [x] **Step 4: Re-run focused tests**

Run `node tests/dark-mode-coverage.test.mjs`.

Expected: every detection Section shell contract passes.

### Task 4: Adapt guard configuration and security workflow dashboards

**Files:**
- Modify: `unified_frontend/src/sections/MonitorSection.tsx`
- Modify: `unified_frontend/src/sections/ConfigSection.tsx`
- Modify: `unified_frontend/src/sections/SecurityVlmSection.tsx`
- Modify: `unified_frontend/src/components/security-vlm/SecurityCameraBar.tsx`
- Modify: `unified_frontend/tests/dark-mode-coverage.test.mjs`

- [x] **Step 1: Add failing business-page contracts**

```js
test('guard and security workflow business cards support dark mode', async () => {
  for (const path of [
    'src/sections/MonitorSection.tsx',
    'src/sections/ConfigSection.tsx',
    'src/sections/SecurityVlmSection.tsx',
    'src/components/security-vlm/SecurityCameraBar.tsx',
  ]) {
    const source = await read(path)
    assert.match(source, /dark:bg-slate-900/)
    assert.match(source, /dark:border-slate-800/)
    assert.match(source, /dark:text-slate-100/)
  }
})
```

- [x] **Step 2: Run the focused test and verify RED**

Run `node tests/dark-mode-coverage.test.mjs`.

Expected: FAIL on the existing light-only business panels.

- [x] **Step 3: Theme the guard behavior internals**

In `MonitorSection.tsx` and `ConfigSection.tsx`, extend existing card and panel classes with:

```text
card/panel: dark:border-slate-800 dark:bg-slate-900
heading: dark:text-slate-100
body/input: dark:text-slate-300 dark:border-slate-700 dark:bg-slate-950/60
muted copy: dark:text-slate-400
```

Do not edit request effects, site selection, camera controls, buttons' event handlers, form values, or validation.

- [x] **Step 4: Theme the security workflow internals**

In `SecurityVlmSection.tsx` and `SecurityCameraBar.tsx`, apply the same surface mappings to the data summary, video-panel chrome, history table, camera cards, dialog content, and ROI toolbar. For `StatCard`, use:

```tsx
<div className="... border-slate-200/80 bg-slate-50/70 ... dark:border-slate-800 dark:bg-slate-900/80">
<div className="... bg-white ... dark:bg-slate-800">
<p className="... text-slate-900 dark:text-slate-100">{value}</p>
```

Keep runtime state, VLM controls, video URLs, ROI points, camera operations and configuration tabs unchanged.

- [x] **Step 5: Re-run focused tests and build**

Run:

```bash
node tests/dark-mode-coverage.test.mjs
npm run build
```

Expected: contracts and production build pass.

### Task 5: Audit remaining routed pages and reusable configuration components

**Files:**
- Modify: `unified_frontend/src/sections/AlarmsSection.tsx`
- Modify: `unified_frontend/src/sections/StatisticsSection.tsx`
- Modify: `unified_frontend/src/sections/UserManagementSection.tsx`
- Modify: `unified_frontend/src/sections/AiVisionSection.tsx`
- Modify: `unified_frontend/src/components/AiVisionMonitor.tsx`
- Modify: `unified_frontend/src/components/FeatureCameraManager.tsx`
- Modify: `unified_frontend/src/components/AiVisionRoiEditor.tsx`
- Modify: `unified_frontend/src/components/AiVisionModelConfig.tsx`
- Modify: `unified_frontend/src/components/AiVisionPresetActions.tsx`
- Modify: `unified_frontend/src/components/AlarmPushConfig.tsx`
- Modify: `unified_frontend/src/pages/LoginPage.css`
- Modify: `unified_frontend/src/index.css`
- Modify: `unified_frontend/tests/dark-mode-coverage.test.mjs`

- [x] **Step 1: Add failing remaining-route contracts**

```js
test('remaining routed pages and shared configuration surfaces support dark mode', async () => {
  const files = [
    'src/sections/AlarmsSection.tsx', 'src/sections/StatisticsSection.tsx',
    'src/sections/UserManagementSection.tsx', 'src/sections/AiVisionSection.tsx',
    'src/components/AiVisionMonitor.tsx', 'src/components/FeatureCameraManager.tsx',
    'src/components/AiVisionRoiEditor.tsx', 'src/components/AiVisionModelConfig.tsx',
    'src/components/AiVisionPresetActions.tsx', 'src/components/AlarmPushConfig.tsx',
  ]
  for (const path of files) {
    const source = await read(path)
    assert.match(source, /dark:/)
  }
  const loginCss = await read('src/pages/LoginPage.css')
  assert.match(loginCss, /\.dark \.login-page/)
  assert.match(loginCss, /\.dark \.login-card/)
  assert.match(loginCss, /\.dark \.login-input/)
})
```

- [x] **Step 2: Run the focused test and verify RED**

Run `node tests/dark-mode-coverage.test.mjs`.

Expected: FAIL for remaining light-only routes and reusable configuration components.

- [x] **Step 3: Add explicit dark surfaces without changing behavior**

Apply the established mapping to page roots, cards, tables, dialogs, form controls, empty states and chart containers:

```text
white card -> dark:bg-slate-900
slate-50 field/row -> dark:bg-slate-950/60
slate-200 border -> dark:border-slate-800
slate-900/950 title -> dark:text-slate-100
slate-600/700 body -> dark:text-slate-300
slate-400/500 metadata -> dark:text-slate-400
```

In `index.css`, extend only generic aliases still shared by audited components, including `bg-slate-50/60`, `bg-slate-50/70`, and fixed `#F3F5FA` page surfaces. Do not override `bg-black/*`, video canvases, ROI colors, status colors, or selected button states.

In `LoginPage.css`, add dark-scoped variables and surfaces so the default dark theme also covers the unauthenticated entry page:

```css
.dark .login-page {
  --login-page-bg: #060d1d;
  --login-ink: #f1f5f9;
}

.dark .login-card {
  border-color: rgba(71, 85, 105, 0.72);
  background: rgba(15, 23, 42, 0.86);
  box-shadow: 0 20px 56px rgba(2, 6, 23, 0.42);
}

.dark .login-input {
  border-color: #475569;
  color: #f1f5f9;
  background: rgba(15, 23, 42, 0.9);
}
```

Also scope the login subtitle, labels, placeholders, password toggle, hover/focus input backgrounds, and error panel to readable slate/rose dark colors. Keep authentication submission, validation and video behavior unchanged.

- [x] **Step 4: Re-run focused and existing contract tests**

Run:

```bash
node tests/dark-mode-coverage.test.mjs
node --test tests/*.test.mjs
```

Expected: all frontend test files pass.

### Task 6: Final scope review and verification

**Files:**
- Modify: `docs/superpowers/plans/2026-08-06-dark-mode-coverage.md` (checkboxes only)
- Review: all files listed above

- [x] **Step 1: Run complete frontend verification**

```bash
cd unified_frontend
node --test tests/*.test.mjs
npm run build
npm run lint
```

Expected: all tests and build pass; lint exits with zero errors and no new warnings in modified files. The four existing logistics `loadCameras` exhaustive-deps warnings may remain.

- [x] **Step 2: Verify scope and whitespace**

```bash
cd ..
git diff --check
git status --short
git diff --name-only
```

Expected: only the theme design/plan, frontend theme files, audited frontend pages/components, and frontend test are present. No backend path is listed.

- [x] **Step 3: Verify no preview process or artifact exists**

```bash
test ! -d /tmp/dark-mode-preview
! ss -ltn | rg ':5173|:4173'
```

Expected: no temporary preview directory and no frontend preview port created by this task.

- [x] **Step 4: Request independent review and fix valid findings**

Ask the reviewer to check first-visit dark fallback, stored-light persistence, all routed Section shells, reusable dashboard surfaces, readable contrast, preserved status colors, and absence of backend/data-flow changes. Re-run Step 1 after every valid Critical or Important fix.

- [x] **Step 5: Commit the approved implementation**

Stage only the plan and audited frontend files, then commit:

```bash
git commit -m "feat: complete frontend dark mode coverage"
```

Do not push or move `V4` unless the user explicitly requests it.
