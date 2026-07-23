# Security VLM Queue Stall Fix Design

## Goal

Prevent the VLM queue from permanently losing consumers after processing a variable number of sessions, and ensure the configured DashScope request timeout is actually applied.

## Confirmed causes

1. `atomic_write_json` uses one fixed `*.json.tmp` path per destination. The VLM main thread and three worker threads concurrently write the same status files, so one thread can replace the temporary file before another thread does. The losing thread raises `FileNotFoundError`.
2. `worker_loop` does not catch exceptions escaping `process_one`. A status-write failure therefore terminates that worker permanently. After all workers have encountered the race, queued tasks have no consumers.
3. DashScope 1.25.16 expects `request_timeout`, while the current call passes `timeout`. The configured 45-second timeout is therefore not used as the HTTP transport timeout.

## Design

### Concurrent atomic JSON writes

Keep the existing write-then-replace contract, but allocate a unique temporary file in the destination directory for every call. Flush and close the temporary file before calling `os.replace`. Remove the unique temporary file in `finally` if replacement did not complete.

Using the destination directory preserves same-filesystem atomic replacement. Unique names remove both same-thread and cross-process collisions without introducing a global lock.

### Worker fault containment

Wrap each `process_one` invocation in `try/except/finally` inside `worker_loop`:

- log the task path and full traceback for an unexpected exception;
- keep the worker loop alive for the next task;
- call `task_q.task_done()` exactly once for every successful `get()`.

Known task errors handled by `process_one` retain their existing result behavior. This boundary is only a last-resort guard against an individual task killing a long-lived worker.

### DashScope timeout

Pass `request_timeout=self.api_timeout` to `MultiModalConversation.call`. Remove the `TypeError` fallback that retries without a timeout because the supported project environment accepts arbitrary keyword arguments and DashScope 1.25.16 explicitly consumes `request_timeout`.

### Scope

The change will not alter queue expiration, concurrency count, budget behavior, session generation, history retention, result schemas, or frontend behavior.

## Tests

Add focused pytest coverage under `security_vlm/tests`:

1. Repeated concurrent writes to the same JSON destination complete without exceptions and leave valid JSON.
2. A worker survives an exception from one task and processes the following task; both queue items are marked done.
3. `VLMJudge.judge` passes the configured value as `request_timeout` to DashScope.

The worker-loop test will exercise a small extracted task-consumption helper rather than starting the infinite production loop. The helper will contain the same exception boundary used by `worker_loop`.

## Success criteria

- The concurrent-write regression test reports zero failures.
- One failing task does not prevent the next queued task from running.
- DashScope receives `request_timeout=45` for the current configuration.
- All new security_vlm tests pass and Python compilation succeeds for modified modules.

## Risks

- A process crash between temporary-file creation and replacement can leave a uniquely named temporary file. The `finally` cleanup covers Python-level failures; abrupt process termination may still leave a small orphan file.
- Catching unexpected task exceptions keeps capacity available but does not create a result JSON for the failed task. The traceback provides the evidence needed for a later task-specific fix.
