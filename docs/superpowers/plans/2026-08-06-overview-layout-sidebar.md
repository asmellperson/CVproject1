# Platform Overview Layout and Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorder the platform overview cards, rename and dark-theme the supervision summary, simplify the sidebar brand, move account actions into the sidebar footer, and remove decorative top ribbons.

**Architecture:** Keep all existing data loading and camera handlers inside `HomeSection`; only move the existing JSX blocks so no business behavior is duplicated. Move the password dialog and its local state from `Topbar` into `Sidebar`, where the existing auth context remains the single source of account operations.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Node test runner, Vite

---

### Task 1: Add layout and navigation contract tests

**Files:**
- Create: `unified_frontend/tests/overview-layout-contract.test.mjs`
- Test: `unified_frontend/tests/overview-layout-contract.test.mjs`

- [x] **Step 1: Write the failing test**

Create source-level contract tests that read `HomeSection.tsx`, `Sidebar.tsx`, and `Topbar.tsx` and assert:

```js
assert.match(homeSection, /监管概况/)
assert.doesNotMatch(homeSection, /统一监管总览/)
assert.match(homeSection, /dark:text-blue-300/)
assert.doesNotMatch(sidebar, /src="\/mascot\.png"/)
assert.doesNotMatch(sidebar, /部分异常|模块在线/)
assert.match(sidebar, /修改密码/)
assert.match(sidebar, /退出/)
assert.doesNotMatch(topbar, /修改密码|退出|employee_id/)
```

Split the `HomeSection` return source around the two section grid declarations and assert that `平台汇总` occurs before `监管概况`. Assert the removed ribbon snippets no longer exist (`h-1.5 bg-gradient-to-r` and ``h-1.5 ${entry.accent}``).

- [x] **Step 2: Run the test to verify it fails**

Run: `node --test tests/overview-layout-contract.test.mjs`

Expected: FAIL because the old title, avatar, topbar account actions, status footer, and colored ribbons still exist.

- [x] **Step 3: Commit the failing contract test with the implementation batch**

Do not commit the intentionally failing test alone; proceed to Tasks 2–4, then commit the complete verified change.

### Task 2: Reorder and restyle the platform overview

**Files:**
- Modify: `unified_frontend/src/sections/HomeSection.tsx`
- Test: `unified_frontend/tests/overview-layout-contract.test.mjs`

- [x] **Step 1: Move the existing platform summary block**

Move the complete `平台汇总` card, including `MiniStatusMetric`, camera list, and all admin camera buttons, into the first grid’s wide left column. Do not copy or rename any camera handlers.

- [x] **Step 2: Move and rename the supervision summary**

Move the existing four-metric overview card into the second grid’s right column and change:

```tsx
<h3>统一监管总览</h3>
```

to:

```tsx
<h3>监管概况</h3>
```

- [x] **Step 3: Complete dark styles for metric tiles**

Extend each `MetricTile` tone entry with explicit dark variants, for example:

```ts
shell: '... dark:border-blue-900/60 dark:bg-[linear-gradient(180deg,rgba(30,64,175,0.24)_0%,rgba(15,23,42,0.72)_100%)]'
value: 'text-blue-700 dark:text-blue-300'
```

Apply equivalent cyan, amber, and emerald variants so the light gradient never wins in dark mode.

- [x] **Step 4: Remove decorative ribbons**

Delete the standalone top ribbon elements from the summary, recent alarm, status board, and `ModuleEntryCard`. Preserve semantic status colors in badges, icons, and alarm content.

- [x] **Step 5: Run the focused test**

Run: `node --test tests/overview-layout-contract.test.mjs`

Expected: sidebar/topbar assertions may still fail, while overview order, title, dark styles, and ribbon assertions pass.

### Task 3: Move account controls to the sidebar

**Files:**
- Modify: `unified_frontend/src/components/Sidebar.tsx`
- Modify: `unified_frontend/src/components/Topbar.tsx`
- Test: `unified_frontend/tests/overview-layout-contract.test.mjs`

- [x] **Step 1: Remove the sidebar avatar and global status**

Delete the `/mascot.png` image wrapper and all `platformStatus`-derived label/tone calculations. Keep the Chinese and English brand text. Remove now-unused `Activity`, `AlertTriangle`, and `PlatformStatus` imports and remove the `platformStatus` prop.

- [x] **Step 2: Add the sidebar account footer**

Use the existing `useAuth()` values in `Sidebar`:

```tsx
const { user, isAdmin, logout, changePassword } = useAuth()
```

Add password form state and the existing validation/submit flow. In the footer, show employee ID, name, and role when expanded; provide `KeyRound` and `LogOut` buttons. In compact mode, render icon-only buttons with `aria-label` values. Keep the existing expand-sidebar control available.

- [x] **Step 3: Move the password dialog**

Move the existing Radix `Dialog`, input fields, validation message, and submit controls from `Topbar` to `Sidebar` unchanged except for their owning component.

- [x] **Step 4: Simplify Topbar**

Remove auth imports, password state and handlers, user badge, password button, logout button, and password dialog. Keep only menu, page title, and theme toggle behavior.

- [x] **Step 5: Update the app call site**

Remove `platformStatus={platformStatus}` from the `Sidebar` call in `unified_frontend/src/App.tsx` after removing the prop from `SidebarProps`.

- [x] **Step 6: Run the focused test**

Run: `node --test tests/overview-layout-contract.test.mjs`

Expected: PASS with zero failed tests.

### Task 4: Verify the complete frontend change

**Files:**
- Verify: `unified_frontend/src/sections/HomeSection.tsx`
- Verify: `unified_frontend/src/components/Sidebar.tsx`
- Verify: `unified_frontend/src/components/Topbar.tsx`
- Verify: `unified_frontend/src/App.tsx`
- Verify: `unified_frontend/tests/overview-layout-contract.test.mjs`

- [x] **Step 1: Run all frontend contract tests**

Run: `node --test tests/*.test.mjs`

Expected: all tests pass with zero failures.

- [x] **Step 2: Run lint**

Run: `npm run lint`

Expected: exit code 0 with no lint errors.

- [x] **Step 3: Build the production frontend**

Run: `npm run build`

Expected: TypeScript and Vite complete with exit code 0.

- [x] **Step 4: Review the exact diff**

Run: `git diff --check && git diff --stat && git status --short`

Expected: no whitespace errors and only the planned frontend files, test, and plan document are changed.

- [x] **Step 5: Commit the implementation**

```bash
git add -- unified_frontend/src/App.tsx unified_frontend/src/components/Sidebar.tsx unified_frontend/src/components/Topbar.tsx unified_frontend/src/sections/HomeSection.tsx unified_frontend/tests/overview-layout-contract.test.mjs docs/superpowers/plans/2026-08-06-overview-layout-sidebar.md
git commit -m "feat: refine overview layout and account navigation"
```
