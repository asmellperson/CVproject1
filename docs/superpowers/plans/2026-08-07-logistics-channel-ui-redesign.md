# Logistics Channel UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the shared logistics-channel monitor and configuration pages from the approved existing UI references, remove colored in-frame banners, and make channel deletion update the UI immediately.

**Architecture:** Keep the four logistics modules as thin wrappers around the shared logistics components. Move deletion selection convergence into `useLogisticsChannels`, keep presentation changes inside the shared monitor/config views, and remove only the live-tile overlay from the backend compositor while retaining grid, letterbox, and offline placeholders.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Radix/shadcn UI, Node contract tests, Python 3, OpenCV, pytest.

---

### Task 1: Immediate channel deletion convergence

**Files:**
- Create: `unified_frontend/src/components/logistics_single_person/channelSelection.ts`
- Modify: `unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts`
- Modify: `unified_frontend/src/components/logistics_single_person/LogisticsChannelSection.tsx`
- Modify: `unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx`
- Create: `unified_frontend/tests/logistics-channel-deletion.test.mjs`

- [ ] **Step 1: Write the failing selection tests**

Add executable tests for a pure helper with these cases:

```ts
selectAfterChannelDeletion([a, b, c], b.id, b.id) === c.id
selectAfterChannelDeletion([a, b], b.id, b.id) === a.id
selectAfterChannelDeletion([a], a.id, a.id) === null
selectAfterChannelDeletion([a, b], a.id, b.id) === b.id
```

Also add a source contract proving the config view calls `onChannelDeleted(deletedId)` only after `deleteLogisticsChannel()` resolves.

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
cd unified_frontend
node --test tests/logistics-channel-deletion.test.mjs
```

Expected: FAIL because `channelSelection.ts` and `onChannelDeleted` do not exist.

- [ ] **Step 3: Implement the minimal local state transition**

Create a pure function that returns the selected ID after deletion, preferring the next list item and then the previous item. Add `removeChannelLocally(channelId)` to `useLogisticsChannels` that synchronously:

```ts
setChannels((current) => {
  const nextSelected = selectAfterChannelDeletion(current, channelId, currentSelectedChannelIdRef.current)
  setSelectedChannelId(nextSelected)
  return current.filter((channel) => channel.id !== channelId)
})
setSelectedChannelDetail(null)
```

Pass this callback through `LogisticsChannelSection`. In the config view, call it only after the delete API succeeds, then trigger normal invalidation for server reconciliation.

- [ ] **Step 4: Run deletion and existing polling tests**

Run:

```bash
cd unified_frontend
node --test tests/logistics-channel-deletion.test.mjs tests/logistics-channel-api-contract.test.mjs tests/serial-poll-runtime.test.mjs
```

Expected: all tests PASS; deleted channel name is removed before the network refresh completes.

- [ ] **Step 5: Commit**

```bash
git add unified_frontend/src/components/logistics_single_person/channelSelection.ts unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts unified_frontend/src/components/logistics_single_person/LogisticsChannelSection.tsx unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx unified_frontend/tests/logistics-channel-deletion.test.mjs
git commit -m "fix: clear deleted logistics channels immediately"
```

### Task 2: Remove colored banners from composed camera frames

**Files:**
- Modify: `AiVision/platform/logistics_channel/compositor.py`
- Modify: `AiVision/tests/test_logistics_channel_compositor.py`

- [ ] **Step 1: Write the failing clean-frame test**

Create a solid-color valid frame, compose it as an online tile with `normal`, `empty`, and `multiple` status, and assert the first rows remain the original pixel color. Keep separate tests proving offline and unusable frames still render placeholders containing non-empty pixels.

- [ ] **Step 2: Run the compositor test and verify RED**

Run:

```bash
MYSQL_DB_URL=127.0.0.1 MYSQL_DB_USER=test MYSQL_DB_PASSWORD=test MYSQL_DB_NAME=test DATA_PATH=/tmp/aivision-logistics-ui pytest -q AiVision/tests/test_logistics_channel_compositor.py
```

Expected: FAIL because `_draw_tile_overlay()` paints the top rows.

- [ ] **Step 3: Remove only live-tile overlay rendering**

Stop calling `_draw_tile_overlay()` from `_render_camera_tile()`. Remove `_visual_status`, `_draw_tile_overlay`, and status-color constants if no remaining caller exists. Keep `render_placeholder()`, Unicode placeholder text, `letterbox()`, layout selection, and output sizing unchanged.

- [ ] **Step 4: Run compositor and runtime regression tests**

Run:

```bash
MYSQL_DB_URL=127.0.0.1 MYSQL_DB_USER=test MYSQL_DB_PASSWORD=test MYSQL_DB_NAME=test DATA_PATH=/tmp/aivision-logistics-ui pytest -q AiVision/tests/test_logistics_channel_compositor.py AiVision/tests/test_logistics_channel_runtime.py
```

Expected: PASS; no status-colored banner is present on valid live frames.

- [ ] **Step 5: Commit**

```bash
git add AiVision/platform/logistics_channel/compositor.py AiVision/tests/test_logistics_channel_compositor.py
git commit -m "fix: remove logistics camera frame banners"
```

### Task 3: Rebuild the monitor page from the Human Dwell layout

**Files:**
- Modify: `unified_frontend/src/components/logistics_single_person/LogisticsChannelSection.tsx`
- Modify: `unified_frontend/src/components/logistics_single_person/LogisticsChannelMonitorView.tsx`
- Modify: `unified_frontend/tests/logistics-channel-ui-contract.test.mjs`
- Modify: `unified_frontend/tests/dark-mode-coverage.test.mjs`

- [ ] **Step 1: Write failing layout contract tests**

Assert the shared section uses the same rounded page shell and pill tabs as `GuardBehaviorSection`, and the monitor contains:

- four summary cards;
- a left column with `监控对象`, `判定说明`, and `实时事件`;
- a right `物流通道实时监控` card;
- no in-picture red/green status banner markup;
- the main tab label `配置管理`.

- [ ] **Step 2: Run the UI contract and verify RED**

Run:

```bash
cd unified_frontend
node --test tests/logistics-channel-ui-contract.test.mjs tests/dark-mode-coverage.test.mjs
```

Expected: FAIL because the current monitor uses a top selector card and right-side member list instead of the Human Dwell layout.

- [ ] **Step 3: Implement the approved monitor layout**

Reuse the `HumanDwellMonitorView` card classes and hierarchy:

```tsx
<section className="grid grid-cols-2 gap-4 lg:grid-cols-4">...</section>
<section className="grid gap-5 lg:grid-cols-3">
  <div className="space-y-5">监控对象 / 判定说明 / 实时事件</div>
  <Card className="overflow-hidden lg:col-span-2">拼接画面</Card>
</section>
```

Adapt content to channel semantics. Put status badges in card headers or the left column, not over the JPEG. Keep object URLs owned by the existing hook.

- [ ] **Step 4: Restyle the shared page shell and tabs**

Use the same `min-h`, rounded background shell, title/subtitle hierarchy, and pill-shaped `实时监控 / 配置管理` tabs as `GuardBehaviorSection`.

- [ ] **Step 5: Run contracts, build, and lint**

Run:

```bash
cd unified_frontend
node --test tests/*.test.mjs
npm run build
npm run lint
```

Expected: all tests PASS, build exits 0, lint exits 0.

- [ ] **Step 6: Commit**

```bash
git add unified_frontend/src/components/logistics_single_person/LogisticsChannelSection.tsx unified_frontend/src/components/logistics_single_person/LogisticsChannelMonitorView.tsx unified_frontend/tests/logistics-channel-ui-contract.test.mjs unified_frontend/tests/dark-mode-coverage.test.mjs
git commit -m "feat: restyle logistics channel monitoring"
```

### Task 4: Rebuild configuration management from the Guard Behavior layout

**Files:**
- Modify: `unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx`
- Modify: `unified_frontend/tests/logistics-channel-ui-contract.test.mjs`
- Modify: `unified_frontend/tests/logistics-channel-membership.test.mjs`

- [ ] **Step 1: Write failing configuration contracts**

Assert the page renders `配置管理`, has internal tabs `通道管理 / 摄像头成员 / 逐路 ROI / 通道规则`, uses `Dialog` for adding a channel, does not render the old inline `新增物流通道` card, preserves viewer read-only behavior, and keeps all existing membership/ROI/rule API calls.

- [ ] **Step 2: Run the contracts and verify RED**

Run:

```bash
cd unified_frontend
node --test tests/logistics-channel-ui-contract.test.mjs tests/logistics-channel-membership.test.mjs
```

Expected: FAIL because channel creation is currently an inline card and there is no `通道管理` inner tab.

- [ ] **Step 3: Implement the Guard Behavior configuration shell**

Add local `activeTab` and `channelDialogOpen` state. Render a header with `配置管理`, a right-aligned add button, and four internal tabs. The `通道管理` card follows the guard-room list style and shows channel state and camera counts.

Use:

```tsx
<Dialog open={channelDialogOpen} onOpenChange={setChannelDialogOpen}>
  <DialogTrigger asChild><Button>添加通道</Button></DialogTrigger>
  <DialogContent>名称输入、取消、确认添加</DialogContent>
</Dialog>
```

On success, close and clear the dialog; on failure, keep it open with the entered value and error message.

- [ ] **Step 4: Preserve existing configuration capabilities**

Move, without changing API semantics:

- member enable/disable, ordering, moving, binding and removal;
- per-camera ROI using `shm_name` through the secured member endpoint;
- channel schedule, grace periods, SQL/WeChat/horn settings;
- admin-only mutations and viewer read-only display.

- [ ] **Step 5: Run all frontend verification**

Run:

```bash
cd unified_frontend
node --test tests/*.test.mjs
npm run build
npm run lint
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx unified_frontend/tests/logistics-channel-ui-contract.test.mjs unified_frontend/tests/logistics-channel-membership.test.mjs
git commit -m "feat: restyle logistics channel configuration"
```

### Task 5: Full regression, visual evidence, and V4 release

**Files:**
- Modify only files required by verified regressions.

- [ ] **Step 1: Run backend full regression**

```bash
MYSQL_DB_URL=127.0.0.1 MYSQL_DB_USER=test MYSQL_DB_PASSWORD=test MYSQL_DB_NAME=test DATA_PATH=/tmp/aivision-logistics-ui-final PYTHONPATH=. pytest -q AiVision/tests
PYTHONPATH=.:unified_backend pytest -q unified_backend/tests
```

Expected: zero failures.

- [ ] **Step 2: Run frontend full regression**

```bash
cd unified_frontend
node --test tests/*.test.mjs
npm run build
npm run lint
```

Expected: zero failures; the existing PostCSS warning may remain but no new warning or error is accepted.

- [ ] **Step 3: Verify repository state**

```bash
git diff --check
git status --short
```

Expected: no output after final commits.

- [ ] **Step 4: Independently review the finished diff**

Review against the approved design, specifically checking that the monitor matches Human Dwell structure, configuration matches Guard Behavior structure, no colored tile banners remain, and channel deletion converges immediately.

- [ ] **Step 5: Update remote V4**

After all reviews pass:

```bash
git push --force origin HEAD:refs/tags/V4
git ls-remote --tags origin V4
```

Expected: remote `refs/tags/V4` equals the final verified `HEAD`.
