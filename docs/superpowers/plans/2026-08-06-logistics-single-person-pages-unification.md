# Logistics Single-Person Pages Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the electronics-electrician, electrical-components, and precious-metal-recycling logistics single-person monitor pages use the approved General Electric frontend dashboard while preserving each page's existing feature, data, video, and configuration behavior.

**Architecture:** Parameterize the existing shared logistics monitor status request, alarm filtering, hook, and view by feature/title. Then opt the three existing sections into that shared presentation and align only their outer page shells with the General Electric section; their configuration implementations remain untouched.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, lucide-react, Node test runner, Vite

---

### Task 1: Lock the multi-feature frontend contract

**Files:**
- Modify: `unified_frontend/tests/logistics-single-person-monitor-contract.test.mjs`

- [ ] **Step 1: Add failing assertions for feature-aware reuse**

Extend the existing contract to read the three additional section files and assert:

```js
assert.match(api, /getAiVisionLogisticsSinglePersonStatus\(cameraKey: string, feature: string\)/)
assert.match(api, /features\/\$\{encodeURIComponent\(feature\)\}\/status/)
assert.match(hook, /feature: string/)
assert.match(hook, /getAlarms\(1000, \[feature\]\)/)
assert.match(state, /feature: string/)
assert.match(state, /alarm\.event_type === feature/)

for (const [source, feature, title] of variantPages) {
  assert.match(source, /presentation="logistics-single-person"/)
  assert.match(source, new RegExp(`feature="${feature}"`))
  assert.match(source, new RegExp(title))
}
```

- [ ] **Step 2: Run the focused contract and verify it fails**

Run:

```bash
cd unified_frontend
node --test tests/logistics-single-person-monitor-contract.test.mjs
```

Expected: FAIL because the shared status/hook/filter remain hardcoded and the three pages have not opted into the presentation.

### Task 2: Parameterize the shared logistics monitor frontend

**Files:**
- Modify: `unified_frontend/src/lib/aivision.ts`
- Modify: `unified_frontend/src/components/logistics_single_person/monitorState.ts`
- Modify: `unified_frontend/src/components/logistics_single_person/useLogisticsSinglePersonMonitor.ts`
- Modify: `unified_frontend/src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx`
- Modify: `unified_frontend/src/components/AiVisionMonitor.tsx`

- [ ] **Step 1: Make the existing frontend status request feature-aware**

Change the status response feature type from the one literal to `string`, and change the request to:

```ts
export async function getAiVisionLogisticsSinglePersonStatus(cameraKey: string, feature: string) {
  const response = await fetch(
    `/api/aivision/cameras/${encodeURIComponent(cameraKey)}/features/${encodeURIComponent(feature)}/status`,
    { credentials: 'include' },
  )
  // Preserve existing error handling and response parsing.
}
```

- [ ] **Step 2: Parameterize alarm filtering and polling**

Add `feature: string` to `filterTodayLogisticsAlarms` and `useLogisticsSinglePersonMonitor`. Use it in the existing calls:

```ts
const nextStatus = await getAiVisionLogisticsSinglePersonStatus(selectedCamera, feature)
const nextAlarms = await getAlarms(1000, [feature])
filterTodayLogisticsAlarms(alarms, feature, selectedCamera, selectedCameraName)
```

Include `feature` in the two effects and memo dependency lists so switching pages cannot retain another feature's state.

- [ ] **Step 3: Pass the existing monitor title and feature through the shared view**

Add `title: string` to `LogisticsSinglePersonMonitorViewProps`, render it in the video card header, and in `AiVisionMonitor` pass:

```tsx
const logisticsMonitor = useLogisticsSinglePersonMonitor({
  enabled: presentation === 'logistics-single-person',
  feature,
  selectedCamera,
  selectedCameraName: selectedCameraInfo?.name || '',
})

<LogisticsSinglePersonMonitorView
  title={title}
  {...existingProps}
/>
```

Do not modify the preview-frame fetch, image/object URL lifecycle, overlays, API response fields, or backend files.

- [ ] **Step 4: Run the focused contract**

Run `node --test tests/logistics-single-person-monitor-contract.test.mjs` from `unified_frontend`.

Expected: shared-component assertions pass; page assertions still fail until Task 3.

### Task 3: Align the three page shells and activate the shared presentation

**Files:**
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonElectronicsElectricianDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonElectricalComponentsDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonPreciousMetalRecyclingDetectionSection.tsx`

- [ ] **Step 1: Replace only each section's outer heading/tab shell**

For each page, use the General Electric section's `min-h`, title/subtitle layout, rounded segmented tabs, spacing, and dark-mode classes. Preserve the entire existing `TabsContent value="config"` subtree without changing its request functions, form state, handlers, feature keys, camera manager, or ROI editor.

Titles remain department-specific:

```tsx
<h1>物流通道单人检测（电子电工）监控与配置</h1>
<h1>物流通道单人检测（电气部件）监控与配置</h1>
<h1>物流通道单人检测（贵金属回收）监控与配置</h1>
```

- [ ] **Step 2: Opt each existing monitor into the shared dashboard**

Keep each feature unchanged and add the presentation prop:

```tsx
<AiVisionMonitor
  title="物流通道单人检测（业务名称）监控"
  feature="detect_logistics_single_person_existing_variant"
  presentation="logistics-single-person"
/>
```

- [ ] **Step 3: Run the focused contract and verify it passes**

Run:

```bash
cd unified_frontend
node --test tests/logistics-single-person-monitor-contract.test.mjs
```

Expected: all contract subtests pass.

### Task 4: Validate the complete frontend change

**Files:**
- Verify all files changed in Tasks 1–3

- [ ] **Step 1: Check the diff boundary**

Run `git diff --name-only` and `git diff --check`.

Expected: only the design/plan documents, listed frontend source files, and the frontend contract test are changed; no backend files appear and no whitespace errors are reported.

- [ ] **Step 2: Run frontend build**

Run `npm run build` from `unified_frontend`.

Expected: TypeScript and Vite build complete successfully.

- [ ] **Step 3: Run frontend lint**

Run `npm run lint` from `unified_frontend`.

Expected: no new lint errors. Existing unrelated warnings, if any, are reported separately.

- [ ] **Step 4: Commit the focused implementation**

Commit only the listed plan, test, and frontend files with:

```bash
git commit -m "feat: unify logistics single-person dashboards"
```

Do not push or move the V4 tag unless the user separately requests it.
