"""后台读取授权快照，避免数据库等待阻塞检测线程。"""

from collections.abc import Callable, Sized
from concurrent.futures import Future
from dataclasses import dataclass, field
from queue import Queue
from threading import BoundedSemaphore, Lock, Thread
import time
from typing import Generic, TypeVar

from AiVision.core.logger import logger


Context = TypeVar("Context", bound=Sized)
Value = TypeVar("Value")
# 查询期限包括工作线程调度、连接获取和 SQL 读取，不作为权限有效期。
AUTHORIZATION_QUERY_TIMEOUT_SECONDS = 8.0
AUTHORIZATION_FAILURE_RETRY_SECONDS = 1.0
_SLOW_REFRESH_SECONDS = 2.0


class _AuthorizationWorker:
    def __init__(self, name: str):
        self.slot = BoundedSemaphore()
        self.jobs: Queue[Callable[[], None]] = Queue(maxsize=1)
        Thread(target=self._run, name=f"{name}-authorization", daemon=True).start()

    def _run(self):
        while True:
            self.jobs.get()()


_workers: dict[str, _AuthorizationWorker] = {}
_workers_lock = Lock()


@dataclass(frozen=True)
class AuthorizationReadTiming:
    """记录数据库读取进度，结果取出后固定快照时间。"""

    connecting_at: float
    connected_at: float | None = None
    fetched_at: float | None = None
    parsed_at: float | None = None


@dataclass(frozen=True)
class AuthorizationResult(Generic[Context, Value]):
    context: Context
    value: Value | None
    error: str | None
    completed_at: float
    sampled_at: float | None


@dataclass
class _Lookup(Generic[Context, Value]):
    context: Context
    submitted_at: float
    deadline: float
    future: Future[AuthorizationResult[Context, Value]]
    timing_lock: Lock = field(default_factory=Lock)
    started_at: float | None = None
    sampled_at: float | None = None
    read_timing: AuthorizationReadTiming | None = None
    reported: bool = False


class AuthorizationRefresh(Generic[Context, Value]):
    """每个功能仅保留一个物理查询；调用方用自身状态锁串行操作。"""

    def __init__(self, name: str, *, snapshot_seconds: float,
                 timeout_seconds: float = AUTHORIZATION_QUERY_TIMEOUT_SECONDS):
        self._name = name
        self._snapshot_seconds = snapshot_seconds
        self._timeout_seconds = timeout_seconds
        self._lookup: _Lookup[Context, Value] | None = None
        with _workers_lock:
            worker = _workers.get(name)
            if worker is None:
                worker = _workers[name] = _AuthorizationWorker(name)
            self._worker = worker

    @property
    def in_progress(self) -> bool:
        return self._lookup is not None

    def submit(self, context: Context, lookup: Callable[[Callable[[AuthorizationReadTiming], None]], Value]) -> bool:
        """不等待数据库或已有任务，也不排队累积待查询请求。"""
        if self._lookup is not None or not self._worker.slot.acquire(blocking=False):
            return False
        future: Future[AuthorizationResult[Context, Value]] = Future()
        submitted_at = time.monotonic()
        job = self._lookup = _Lookup(context, submitted_at, submitted_at + self._timeout_seconds, future)

        def mark_sampled(timing: AuthorizationReadTiming | None = None):
            with job.timing_lock:
                job.read_timing = timing
                job.sampled_at = time.monotonic() if timing is None else timing.fetched_at

        def run():
            with job.timing_lock:
                job.started_at = time.monotonic()
            value, error = None, None
            try:
                if job.started_at >= job.deadline:
                    error = "TimeoutError"
                else:
                    value = lookup(mark_sampled)
                    if job.sampled_at is None:
                        value, error = None, "MissingSnapshotTimestamp"
            except Exception as exc:
                error = type(exc).__name__
            finally:
                self._worker.slot.release()
            future.set_result(AuthorizationResult(context, value, error, time.monotonic(), job.sampled_at))

        self._worker.jobs.put_nowait(run)
        return True

    def poll(self) -> AuthorizationResult[Context, Value] | None:
        """只交付一次结果；超时后继续限制并发，迟到授权一律丢弃。"""
        lookup = self._lookup
        if lookup is None:
            return None
        result = None
        if lookup.future.done():
            result = lookup.future.result()
            self._lookup = None
        if lookup.reported:
            return None
        with lookup.timing_lock:
            started_at, sampled_at, read_timing = lookup.started_at, lookup.sampled_at, lookup.read_timing
            now = time.monotonic()
        observed_until = now if result is None else result.completed_at
        if sampled_at is not None:
            observed_until = sampled_at
        if observed_until >= lookup.deadline:
            result = AuthorizationResult(lookup.context, None, "TimeoutError", now, sampled_at)
        elif sampled_at is not None and now >= sampled_at + self._snapshot_seconds:
            # 成功读取后如果长期未被领取，也不能在发布时重启授权有效期。
            result = AuthorizationResult(lookup.context, None, "ExpiredSnapshot", now, sampled_at)
        if result is not None:
            lookup.reported = True
            if result.error is not None or now - lookup.submitted_at >= _SLOW_REFRESH_SECONDS:
                self._log_result(lookup, result, now, started_at, read_timing)
        return result

    def _log_result(self, lookup, result, now: float, started_at: float | None,
                    read_timing: AuthorizationReadTiming | None):
        queue_elapsed = (now if started_at is None else started_at) - lookup.submitted_at
        read_end = result.sampled_at if result.sampled_at is not None else result.completed_at
        read_elapsed = 0.0 if started_at is None else read_end - started_at
        return_elapsed = 0.0 if result.sampled_at is None else now - result.sampled_at
        message = (
            f"[{self._name}] 授权刷新 status={result.error or 'ok'} scopes={len(lookup.context)} "
            f"queue_ms={queue_elapsed * 1000:.1f} read_ms={read_elapsed * 1000:.1f} "
            f"return_ms={return_elapsed * 1000:.1f}"
        )
        if read_timing is not None:
            finish = result.completed_at
            connected = read_timing.connected_at
            fetched = read_timing.fetched_at
            connection = (connected if connected is not None else finish) - read_timing.connecting_at
            execute_fetch = 0.0 if connected is None else (fetched if fetched is not None else finish) - connected
            parsed = read_timing.parsed_at
            parse = 0.0 if fetched is None else (parsed if parsed is not None else finish) - fetched
            message += (
                f" connection_ms={connection * 1000:.1f} execute_fetch_ms={execute_fetch * 1000:.1f}"
                f" parse_ms={parse * 1000:.1f}"
            )
        if result.error is not None:
            logger.warning(message)
        else:
            logger.info(message)

    def invalidate(self):
        """停启后不接收旧查询，仍等物理查询完成才释放名额。"""
        if self._lookup is not None:
            self._lookup.reported = True
