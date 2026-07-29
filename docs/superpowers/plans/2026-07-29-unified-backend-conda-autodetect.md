# Unified Backend Conda Autodetect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scripts/start.sh` automatically run the unified backend from the existing `unified_backend` Conda environment without target-server file edits.

**Architecture:** Extract the runtime precedence decision into a small sourceable Bash module. The main startup script supplies detected Conda and system-Python inputs, while a dependency-free Shell test verifies explicit Python, Conda, and fallback selection.

**Tech Stack:** Bash, Conda, tmux, existing Python/FastAPI test suite

---

### Task 1: Runtime selection regression test

**Files:**
- Create: `scripts/tests/test_unified_backend_runtime.sh`
- Create: `scripts/lib/unified_backend_runtime.sh`

- [ ] **Step 1: Write the failing test**

Add a plain Bash test that sources `scripts/lib/unified_backend_runtime.sh`
and asserts that `resolve_unified_backend_runtime` prefers:

```text
explicit Python > unified_backend Conda environment > system Python
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
bash scripts/tests/test_unified_backend_runtime.sh
```

Expected: fail because `scripts/lib/unified_backend_runtime.sh` does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement `resolve_unified_backend_runtime` so it prints one shell command
using only its explicit arguments and the existing `conda_env_exists`
callback.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
bash scripts/tests/test_unified_backend_runtime.sh
```

Expected: all runtime precedence assertions pass.

### Task 2: Integrate the startup script

**Files:**
- Modify: `scripts/start.sh`
- Modify: `scripts/start.env.example`
- Modify: `run_guide.txt`

- [ ] **Step 1: Source the runtime module**

Source `scripts/lib/unified_backend_runtime.sh` after `SCRIPT_DIR` is known.

- [ ] **Step 2: Configure runtime inputs**

Set `UNIFIED_BACKEND_ENV` to `unified_backend` by default, preserve an
explicit `UNIFIED_BACKEND_PYTHON`, and separately detect the system Python
fallback.

- [ ] **Step 3: Build the service command**

Call `resolve_unified_backend_runtime` and use its result in the
`unified_backend` service entry. Keep `__DEP_MISSING__` when no runtime is
available.

- [ ] **Step 4: Update operator documentation**

Document that the default environment is automatic and that
`UNIFIED_BACKEND_ENV` or `UNIFIED_BACKEND_PYTHON` remain optional overrides.

### Task 3: Verify and publish

**Files:**
- Verify all files from Tasks 1–2.

- [ ] **Step 1: Run verification**

```bash
bash -n scripts/start.sh scripts/lib/unified_backend_runtime.sh scripts/tests/test_unified_backend_runtime.sh
bash scripts/tests/test_unified_backend_runtime.sh
bash scripts/start.sh --help
python -m pytest unified_backend/tests -q
```

- [ ] **Step 2: Review scope and secrets**

Run `git status --short`, task-scoped diffs, `git diff --check`, and a
sensitive-value scan. Preserve unrelated user files.

- [ ] **Step 3: Commit and publish**

Commit only the task files, force-update only the `V4` tag, push that tag,
and verify local HEAD, local V4, and remote V4 resolve to the same SHA.

