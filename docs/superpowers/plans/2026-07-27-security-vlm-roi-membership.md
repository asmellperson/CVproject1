# Security VLM ROI Membership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use stable person-box/ROI overlap membership for security sessions and visually distinguish ROI members from outside full-frame tracks.

**Architecture:** Add a small shared ROI geometry module. Session creation uses a 30% enter threshold, active sessions use a 10% hold threshold plus the existing fingerprint-loss timeout, and MJPEG rendering colors tracks according to the same enter predicate.

**Tech Stack:** Python 3.10, NumPy, OpenCV, unittest/pytest, existing Security VLM workers.

---

### Task 1: Shared ROI membership geometry

**Files:**
- Create: `security_vlm/src/roi_geometry.py`
- Create: `security_vlm/tests/test_roi_membership.py`

- [ ] Write tests for normalized intersection area divided by person-box area.
- [ ] Verify the tests fail because `roi_geometry` does not exist.
- [ ] Implement `bbox_roi_overlap_ratio()` and `bbox_belongs_to_roi()`.
- [ ] Verify center inclusion, 30% entry, 10% hold, reversed coordinates, and
      invalid boxes pass.

Run:

```bash
python -m pytest security_vlm/tests/test_roi_membership.py -q
```

### Task 2: Session enter/hold thresholds

**Files:**
- Modify: `security_vlm/src/session_worker.py`
- Modify: `security_vlm/tests/test_roi_membership.py`
- Modify: `security_vlm/configs/config.example.yaml`

- [ ] Add a failing test showing an inactive ROI uses the enter threshold while
      an active ROI uses the hold threshold.
- [ ] Read `roi_enter_overlap_ratio` and `roi_hold_overlap_ratio` from session
      configuration and validate `hold <= enter`.
- [ ] Replace the center-only filtering in `PairSessionManager.step()`.
- [ ] Use the shared enter predicate for `persons_in_roi`.
- [ ] Verify the focused tests pass.

### Task 3: Rule-video membership colors

**Files:**
- Modify: `security_vlm/src/main.py`
- Modify: `security_vlm/tests/test_roi_membership.py`

- [ ] Add a failing overlay test with one ROI member and one outside track.
- [ ] Color ROI members green and outside full-frame tracks gray.
- [ ] Verify the focused overlay test passes.

### Task 4: Regression verification

**Files:**
- Verify all modified production and test files.

- [ ] Run focused tests.
- [ ] Run `python -m pytest security_vlm/tests -q`.
- [ ] Compile all modified Python modules with `py_compile`.
- [ ] Run `git diff --check`.
- [ ] Inspect the final diff and confirm capture, frontend, detector inference,
      VLM, and `max_side` behavior are unchanged.
