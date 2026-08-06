# Security VLM Configuration Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all Security VLM camera-management operations out of the live monitor and place them beside the existing ROI editor under a new two-page configuration area.

**Architecture:** Keep `SecurityVlmSection` as the owner of all existing API calls and state. Replace the primary `dashboard | roi` state with `dashboard | config`, add a nested `camera | roi` state, and move existing JSX blocks without changing their callbacks. Derive ROI video mode and ROI loading from both tab states so the original-frame endpoint is requested only while the nested ROI page is active.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, shadcn Tabs/Card/Button, Node test runner, Vite

---

### Task 1: Add a failing page-structure contract

**Files:**
- Create: `unified_frontend/tests/security-vlm-config-tabs-contract.test.mjs`

- [x] **Step 1: Write the failing contract test**

Create a source contract that reads `src/sections/SecurityVlmSection.tsx` and asserts:

```js
assert.match(section, /const \[activeTab, setActiveTab\] = useState\('dashboard'\)/)
assert.match(section, /const \[configTab, setConfigTab\] = useState\('camera'\)/)
assert.match(section, /<TabsTrigger value="dashboard"[^>]*>[\s\S]*实时监控/)
assert.match(section, /<TabsTrigger value="config"[^>]*>[\s\S]*配置管理/)
assert.match(section, /<Tabs value=\{configTab\} onValueChange=\{setConfigTab\}/)
assert.match(section, /<TabsTrigger value="camera"[^>]*>[\s\S]*摄像头管理/)
assert.match(section, /<TabsTrigger value="roi"[^>]*>[\s\S]*ROI 绘制/)
```

Use string indexes to prove `SecurityCameraBar` occurs after the nested `camera` content marker, and `工位 ROI 绘制` occurs after the nested `roi` content marker. Assert the primary tab no longer has `value="roi"`.

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd unified_frontend
node tests/security-vlm-config-tabs-contract.test.mjs
```

Expected: FAIL because `configTab` and the new primary/nested tab structure do not exist.

### Task 2: Reorganize the Security VLM tabs

**Files:**
- Modify: `unified_frontend/src/sections/SecurityVlmSection.tsx`
- Modify: `unified_frontend/tests/security-vlm-config-tabs-contract.test.mjs`

- [x] **Step 1: Add nested configuration state and update ROI activation**

Add:

```ts
const [configTab, setConfigTab] = useState('camera')
const roiActive = activeTab === 'config' && configTab === 'roi'
```

Use `roiActive` instead of `activeTab === 'roi'` when selecting the `original` video mode and when loading ROI data. Keep the existing dependencies, adding `configTab` or `roiActive` as required.

- [x] **Step 2: Replace the primary tabs**

Keep the controlled primary `Tabs`, but change its triggers to:

```tsx
<TabsTrigger value="dashboard">实时监控</TabsTrigger>
<TabsTrigger value="config">配置管理</TabsTrigger>
```

Keep the title and monitoring status. In the dashboard controls keep the runtime/VLM badges, single/dual-view button, and refresh button. Remove the all-start/all-stop buttons and `SecurityCameraBar` from the dashboard/global area.

- [x] **Step 3: Add the nested camera-management page**

Inside `<TabsContent value="config">`, render controlled nested tabs with `camera` and `roi` triggers. The camera content contains a card whose header has “摄像头管理”, all-start, all-stop, and refresh buttons. Its body renders the unchanged `SecurityCameraBar` props and callbacks:

```tsx
<SecurityCameraBar
  cameras={cameras}
  selectedId={selectedCameraId}
  isAdmin={isAdmin}
  busyId={busyCameraId}
  onSelect={setSelectedCameraId}
  onToggle={(camera) => void handleToggleCamera(camera)}
  onRestart={(camera) => void handleRestartCamera(camera)}
  onEdit={(camera) => void openCameraDialog(camera)}
  onAdd={() => void openCameraDialog(null)}
/>
```

Preserve all existing permission and disabled expressions.

- [x] **Step 4: Move the existing ROI card into the nested ROI page**

Move the full existing `工位 ROI 绘制` card, including the camera selector, add/delete/save actions, drawing stage, polygon rendering, draft rectangle, ROI list, messages, and empty states, under `<TabsContent value="roi">`. Do not modify coordinate conversion, pointer handlers, request functions, or button callbacks.

- [x] **Step 5: Preserve the camera dialog and validate handlers**

Leave `SecurityCameraDialog` outside both content panels so add/edit/delete behavior survives tab switches. Extend the contract to assert these existing symbols remain:

```js
for (const name of [
  'handleAllCameras', 'handleToggleCamera', 'handleRestartCamera',
  'openCameraDialog', 'saveCamera', 'deleteCamera',
  'getSecurityVlmCameraRois', 'saveSecurityVlmCameraRois',
]) assert.match(section, new RegExp(name))
```

- [x] **Step 6: Run focused verification and verify GREEN**

Run:

```bash
cd unified_frontend
node tests/security-vlm-config-tabs-contract.test.mjs
npm run build
```

Expected: the focused contract and TypeScript production build pass.

### Task 3: Regression verification and commit

**Files:**
- Modify: `docs/superpowers/plans/2026-08-06-security-vlm-config-tabs.md`
- Modify/Create: the files listed above

- [x] **Step 1: Run complete frontend verification**

```bash
cd unified_frontend
node --test tests/*.test.mjs
npm run build
npm run lint
cd ..
git diff --check
git status --short
```

Expected: all contract tests and the production build pass; lint has zero errors, allowing the four existing hook warnings.

- [x] **Step 2: Review protected behavior**

Confirm the diff retains every existing Security VLM request, camera callback, ROI pointer handler, video URL builder, dialog action, permission check, and department prop. Confirm only JSX placement, tab state, and ROI-active conditions changed.

- [x] **Step 3: Commit the implementation**

```bash
git add -- unified_frontend/src/sections/SecurityVlmSection.tsx unified_frontend/tests/security-vlm-config-tabs-contract.test.mjs docs/superpowers/plans/2026-08-06-security-vlm-config-tabs.md
git commit -m "feat: organize security VLM configuration tabs"
```
