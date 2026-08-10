# WeChat News Card SQL Toggle Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep AiVision enterprise-WeChat alarms as a single news card when WeChat is enabled and SQL is disabled.

**Architecture:** Preserve the independent SQL toggle, but treat synchronous alarm persistence as an internal prerequisite whenever the WeChat news-card path is active. Add one focused regression for the exact `sql=false`, `wechat=true` combination before changing the dispatcher condition.

**Tech Stack:** Python, pytest, Git

---

### Task 1: Reproduce and fix the missing card record

**Files:**
- Modify: `AiVision/tests/test_wechat_news_card.py`
- Modify: `AiVision/core/alarm/dispatcher.py`

- [ ] **Step 1: Add the failing regression test**

Append this test beside the existing dispatcher card tests:

```python
def test_dispatcher_persists_card_record_when_sql_is_disabled():
    dispatcher = AlarmDispatcher()
    writer = FakeViolationWriter()
    dispatcher.horn_dict = {}
    dispatcher.wechat = FakeWeChat()
    dispatcher.violation_writer = writer
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    dispatcher._execute(
        AlarmRequest(
            feature_name="detect_human",
            camera_id=7,
            camera_name="后大门",
            frame=frame,
            violation_type=5,
            alarm_config={
                "sql": {"enable": False, "parm": {}},
                "wechat": {"enable": True, "parm": {"user": "zhangsan"}},
            },
            camera_key="gate_7",
        )
    )

    _request, user, record = dispatcher._wechat_queue.get_nowait()
    assert writer.saved == [(5, "gate_7", (8, 8, 3))]
    assert writer.enqueued == []
    assert user == "zhangsan"
    assert record.id == 42
    assert dispatcher._alarm_card_urls(record.id) == (
        "https://aicv.fudar.com/api/public/aivision/alarms/42/image",
        "https://aicv.fudar.com/?page=alarms&alarmId=aivision%3A42",
    )
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd AiVision && pytest -q tests/test_wechat_news_card.py::test_dispatcher_persists_card_record_when_sql_is_disabled`

Expected: FAIL because `record` is `None` and `writer.saved` is empty.

- [ ] **Step 3: Implement the minimal persistence-condition fix**

In `AlarmDispatcher._execute`, define the combined internal persistence requirement and use it for the existing writer block:

```python
should_persist_violation = should_write_sql or should_send_wechat
```

```python
if should_persist_violation and self.violation_writer is not None:
```

Update the nearby comment to state that WeChat card persistence is required even when the standalone SQL channel is disabled. Do not change `_alarm_card_urls`, `WeChatNotifier.send`, configuration schemas, or fallback behavior.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `cd AiVision && pytest -q tests/test_wechat_news_card.py::test_dispatcher_persists_card_record_when_sql_is_disabled`

Expected: PASS.

### Task 2: Verify, commit, and publish V4

**Files:**
- Test: `AiVision/tests/test_wechat_news_card.py`
- Test: `AiVision/tests/test_alarm_config_hot_update.py`
- Test: `AiVision/tests/test_alarm_api.py`

- [ ] **Step 1: Run related tests**

Run: `cd AiVision && pytest -q tests/test_wechat_news_card.py tests/test_alarm_config_hot_update.py tests/test_alarm_api.py`

Expected: all tests PASS.

- [ ] **Step 2: Run syntax and diff checks**

Run: `python -m py_compile AiVision/core/alarm/dispatcher.py AiVision/tests/test_wechat_news_card.py`

Expected: exit code 0.

Run: `git diff --check`

Expected: exit code 0.

- [ ] **Step 3: Inspect and commit only implementation files**

Run: `git diff -- AiVision/core/alarm/dispatcher.py AiVision/tests/test_wechat_news_card.py`

Expected: one condition/comment change and one focused regression test.

```bash
git add -- AiVision/core/alarm/dispatcher.py AiVision/tests/test_wechat_news_card.py
git commit -m "fix: keep AiVision WeChat alarms as news cards"
```

- [ ] **Step 4: Publish and verify remote V4**

```bash
git tag -f V4 HEAD
git push --force origin HEAD:refs/tags/V4
git rev-parse HEAD
git ls-remote --tags origin refs/tags/V4
```

Expected: the local `HEAD` hash and remote `refs/tags/V4` hash are identical.
