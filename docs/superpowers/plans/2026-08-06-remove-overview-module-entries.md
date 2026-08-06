# Remove Overview Module Entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the clickable “进入功能” card area from the bottom of the platform overview while preserving status calculations, navigation, permissions, and feature pages.

**Architecture:** Keep `moduleEntries` and `visibleModuleEntries` as the data source for overview status metrics. Remove only the bottom card rendering and the administrator grouping/component code that becomes unreachable.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Node test runner, Vite

---

### Task 1: Remove bottom feature-entry cards

**Files:**
- Modify: `unified_frontend/tests/overview-layout-contract.test.mjs`
- Modify: `unified_frontend/src/sections/HomeSection.tsx`

- [x] **Step 1: Add a failing removal contract**

Append this focused test:

```js
test('removes the bottom feature entry cards from the overview', () => {
  assert.doesNotMatch(homeSection, /ModuleEntryCard/)
  assert.doesNotMatch(homeSection, /进入功能/)
  assert.match(homeSection, /const moduleEntries =/)
  assert.match(homeSection, /getVisibleStatusCards\(visibleModuleEntries\)/)
})
```

- [x] **Step 2: Run the test and verify RED**

Run:

```bash
cd unified_frontend
node tests/overview-layout-contract.test.mjs
```

Expected: the new test fails because `ModuleEntryCard` and “进入功能” are still present.

- [x] **Step 3: Remove the rendered card area and dead helpers**

In `HomeSection.tsx`:

- Delete the final administrator/non-administrator `<section>` block that maps entries to `ModuleEntryCard`.
- Delete `ModuleEntryCard`.
- Delete `DepartmentModuleGroup`, `getAdminDepartmentModuleGroups`, the department-group constant, and the `adminModuleGroups` memo that existed only for the removed area.
- Remove the now-unused `departmentPermissions` import.
- Keep `moduleEntries`, `ModuleStatusCard`, `visibleModuleEntries`, `visibleStatusCards`, and the remaining `ArrowRight` alarm navigation icon.

- [x] **Step 4: Run focused and regression verification**

Run:

```bash
cd unified_frontend
node tests/overview-layout-contract.test.mjs
node --test tests/*.test.mjs
npm run build
npm run lint
```

Expected: all tests and build pass; lint exits with zero errors, allowing the four pre-existing hooks warnings.

- [x] **Step 5: Verify scope and commit**

Run:

```bash
git diff --check
git status --short
```

Then commit only the plan, overview source, and overview contract test:

```bash
git add -- docs/superpowers/plans/2026-08-06-remove-overview-module-entries.md unified_frontend/src/sections/HomeSection.tsx unified_frontend/tests/overview-layout-contract.test.mjs
git commit -m "feat: remove overview feature entry cards"
```
