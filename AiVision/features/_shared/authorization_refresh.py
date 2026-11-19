"""后台读取授权快照，避免数据库等待阻塞检测线程。"""

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from threading import BoundedSemaphore, Lock, Thread
import time
from typing import Generic, TypeVar


Context = TypeVar("Context")
Value = TypeVar("Value")
_slots: dict[str, BoundedSemaphore] = {}
_slots_lock = Lock()


@dataclass(frozen=True)
class AuthorizationResult(Generic[Context, Value]):
    context: Context
    value: Value | None
    error: str | None
    completed_at: float


@dataclass
class _Lookup(Generic[Context, Value]):
    context: Context
    deadline: float
    future: Future[AuthorizationResult[Context, Value]]
    reported: bool = False


class AuthorizationRefresh(Generic[Context, Value]):
    """每个功能仅保留一个物理查询；调用方用自身状态锁串行操作。"""

    def __init__(self, name: str, *, timeout_seconds: float):
        self._name = name
        self._timeout_seconds = timeout_seconds
        self._lookup: _Lookup[Context, Value] | None = None
        with _slots_lock:
            self._slot = _slots.setdefault(name, BoundedSemaphore())

    @property
    def in_progress(self) -> bool:
        return self._lookup is not None

    def submit(self, context: Context, lookup: Callable[[], Value]) -> bool:
        """不等待数据库或已有任务，也不排队累积待查询请求。"""
        if self._lookup is not None or not self._slot.acquire(blocking=False):
            return False
        future: Future[AuthorizationResult[Context, Value]] = Future()
        self._lookup = _Lookup(context, time.monotonic() + self._timeout_seconds, future)

        def run():
            try:
                value = lookup()
                result = AuthorizationResult(context, value, None, time.monotonic())
            except Exception as exc:
                result = AuthorizationResult(context, None, type(exc).__name__, time.monotonic())
            finally:
                self._slot.release()
            future.set_result(result)

        thread = Thread(target=run, name=f"{self._name}-authorization", daemon=True)
        try:
            thread.start()
        except RuntimeError as exc:
            self._slot.release()
            future.set_result(AuthorizationResult(context, None, type(exc).__name__, time.monotonic()))
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
        now = time.monotonic() if result is None else result.completed_at
        if now >= lookup.deadline:
            lookup.reported = True
            return AuthorizationResult(lookup.context, None, "TimeoutError", now)
        return result

    def invalidate(self):
        """停启后不接收旧查询，仍等物理查询完成才释放名额。"""
        if self._lookup is not None:
            self._lookup.reported = True
