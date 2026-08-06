# User Identity Avatar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one reusable text-avatar user identity component to the platform top bar and sidebar footer without changing authentication APIs or account actions.

**Architecture:** A focused `UserIdentity` presentational component receives the existing `AuthUser` object and owns avatar/name/role/employee styling. `Topbar` and `Sidebar` continue reading `user` from `useAuth()` and only compose this component into their existing layouts.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Node test runner, Vite

---

### Task 1: Define the shared user identity contract

**Files:**
- Create: `unified_frontend/tests/user-identity-contract.test.mjs`
- Create: `unified_frontend/src/components/UserIdentity.tsx`
- Modify: `unified_frontend/src/components/Topbar.tsx`
- Modify: `unified_frontend/src/components/Sidebar.tsx`

- [x] **Step 1: Write the failing contract test**

Create a Node contract test that reads the three component sources and asserts:

```js
assert.match(identity, /user\.name\.slice\(-1\)/)
assert.match(identity, /h-9 w-9/)
assert.match(identity, /rounded-full/)
assert.match(identity, /bg-gradient-to-br/)
assert.match(identity, /from-cyan-500/)
assert.match(identity, /to-indigo-600/)
assert.match(identity, /text-white/)
assert.match(identity, /user\.name/)
assert.match(identity, /user\.role/)
assert.match(identity, /user\.employee_id/)
assert.match(topbar, /<UserIdentity user=\{user\}/)
assert.match(sidebar, /<UserIdentity user=\{user\}/)
```

- [x] **Step 2: Run the contract test and verify RED**

Run:

```bash
cd unified_frontend
node --test tests/user-identity-contract.test.mjs
```

Expected: FAIL because `src/components/UserIdentity.tsx` does not exist.

- [x] **Step 3: Implement the reusable component**

Create `UserIdentity.tsx` with a typed `user: AuthUser` prop and optional `className` / `detailsClassName` styling hooks. Render a `h-9 w-9` gradient circle containing `{user.name.slice(-1)}`, then render the current name, uppercase role badge, and employee number from the same object. Use `cn` for layout composition and no image element.

- [x] **Step 4: Integrate the top bar**

In `Topbar.tsx`, render:

```tsx
{user && (
  <UserIdentity
    user={user}
    className="hidden sm:flex"
    detailsClassName="hidden xl:flex"
  />
)}
```

Place it before the theme toggle so it does not change that button's behavior. The responsive detail class keeps title space available.

- [x] **Step 5: Integrate the sidebar footer**

Replace the duplicated footer name/role/employee markup with:

```tsx
{user && (
  <div className="border-b border-slate-200 px-1 pb-3 dark:border-slate-800">
    <UserIdentity user={user} />
  </div>
)}
```

Keep password and logout buttons unchanged.

- [x] **Step 6: Run focused and regression tests and verify GREEN**

Run:

```bash
cd unified_frontend
node --test tests/user-identity-contract.test.mjs
node --test tests/*.test.mjs
npm run build
```

Expected: all contract tests pass and the TypeScript/Vite build exits successfully.

- [x] **Step 7: Check formatting and scope**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only the plan, new shared component/test, `Topbar.tsx`, and `Sidebar.tsx` are changed after the already-committed design document.

- [x] **Step 8: Commit the implementation**

```bash
git add -- docs/superpowers/plans/2026-08-06-user-identity-avatar.md unified_frontend/tests/user-identity-contract.test.mjs unified_frontend/src/components/UserIdentity.tsx unified_frontend/src/components/Topbar.tsx unified_frontend/src/components/Sidebar.tsx
git commit -m "feat: add reusable user text avatar"
```
