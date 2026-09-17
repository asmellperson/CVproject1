"""每个 Feature 的结果队列只由一个线程读取，按 request_id 唤醒请求方。"""
from __future__ import annotations

from dataclasses import dataclass, field
import queue
import threading
from typing import Callable

from AiVision.core.logger import logger
from .contracts import (
    INFERENCE_ERROR_INVALID_RESULT,
    INFERENCE_ERROR_ROUTER_FAILED,
    INFERENCE_ERROR_ROUTER_STOPPED,
    INFERENCE_ERROR_TIMEOUT,
    INFERENCE_STATUS_ERROR,
    INFERENCE_STATUS_TIMEOUT,
    INFERENCE_STATUS_UNAVAILABLE,
    build_inference_result,
)

_IDENTITY_FIELDS = ("request_id", "function_name", "camera_id", "roi_id", "model_name")
_READ_TIMEOUT_SECONDS = 0.1
_STOP_TIMEOUT_SECONDS = 2.0


@dataclass
class PendingInference:
    # 只保留身份，不持有任务中的图像。
    identity: dict
    event: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None


class InferenceResultRouter:
    def __init__(self, result_queue, feature_name: str, *, on_failure: Callable[[str], None] | None = None):
        self.result_queue = result_queue
        self.feature_name = feature_name
        self._on_failure = on_failure
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending: dict[str, PendingInference] = {}
        self._state = "stopped"
        self._last_error = ""
        self._orphan_count = 0
        self._invalid_count = 0

    def start(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                if self._thread is not None and self._thread.is_alive():
                    if self._state == "running":
                        return
                    raise RuntimeError("推理结果读取线程尚未退出，不能重复启动")
                self._stop_event.clear()
                self._last_error = ""
                self._state = "running"
                self._thread = threading.Thread(
                    target=self._read_loop, name=f"inference-results-{self.feature_name}", daemon=True,
                )
                try:
                    self._thread.start()
                except Exception as exc:
                    self._thread = None
                    self._state = "failed"
                    self._last_error = str(exc)
                    self._stop_event.set()
                    raise

    def stop(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                self._state = "stopped"
                self._stop_event.set()
                self._finish_pending_locked()
                thread = self._thread
            if thread is not None:
                thread.join(timeout=_STOP_TIMEOUT_SECONDS)
                if thread.is_alive():
                    raise RuntimeError("推理结果读取线程停止超时")
            self._thread = None

    def register(self, task: dict) -> PendingInference:
        identity = {key: task[key] for key in _IDENTITY_FIELDS}
        request_id = identity["request_id"]
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("推理请求必须提供非空 request_id")
        if identity["function_name"] != self.feature_name:
            raise ValueError("推理请求的 function_name 与结果路由器不一致")
        pending = PendingInference(identity)
        with self._lock:
            if self._state != "running":
                self._complete_locked(pending, self._unavailable_result(identity))
            elif request_id in self._pending:
                raise ValueError(f"重复注册推理请求: {request_id}")
            else:
                self._pending[request_id] = pending
        return pending

    def wait(self, pending: PendingInference, timeout: float) -> dict:
        pending.event.wait(timeout=max(0.0, timeout))
        # 超时与结果交付使用同一把锁，只有先完成的一方可以决定结果。
        with self._lock:
            if pending.result is None:
                self._complete_locked(pending, build_inference_result(
                    pending.identity, status=INFERENCE_STATUS_TIMEOUT,
                    error_code=INFERENCE_ERROR_TIMEOUT,
                    error_message=f"等待推理结果超时: {timeout:.3f}s",
                ))
                self._remove_locked(pending)
            return pending.result

    def unregister(self, pending: PendingInference) -> None:
        with self._lock:
            self._remove_locked(pending)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "pending_count": len(self._pending),
                "orphan_count": self._orphan_count,
                "invalid_count": self._invalid_count,
                "last_error": self._last_error,
            }

    def _remove_locked(self, pending: PendingInference) -> None:
        request_id = pending.identity["request_id"]
        if self._pending.get(request_id) is pending:
            del self._pending[request_id]

    @staticmethod
    def _complete_locked(pending: PendingInference, result: dict) -> None:
        if pending.result is None:
            pending.result = result
            pending.event.set()

    def _unavailable_result(self, identity: dict) -> dict:
        failed = self._state == "failed"
        return build_inference_result(
            identity, status=INFERENCE_STATUS_ERROR if failed else INFERENCE_STATUS_UNAVAILABLE,
            error_code=INFERENCE_ERROR_ROUTER_FAILED if failed else INFERENCE_ERROR_ROUTER_STOPPED,
            error_message=self._last_error if failed else "推理结果路由器尚未启动或已停止",
        )

    def _finish_pending_locked(self) -> None:
        for pending in self._pending.values():
            self._complete_locked(pending, self._unavailable_result(pending.identity))
        self._pending.clear()

    def _route(self, outcome) -> None:
        request_id = outcome.get("request_id") if isinstance(outcome, dict) else None
        with self._lock:
            pending = self._pending.get(request_id) if isinstance(request_id, str) else None
            if pending is None or pending.result is not None:
                # 不缓存迟到、重复或无法识别请求的结果。
                self._orphan_count += 1
                return
            mismatches = [key for key, expected in pending.identity.items()
                          if type(outcome.get(key)) is not type(expected) or outcome.get(key) != expected]
            if mismatches:
                self._invalid_count += 1
                message = f"推理结果身份不匹配: {', '.join(mismatches)}"
                logger.warning(f"[{self.feature_name}] {message}, request_id={request_id}")
                result = build_inference_result(
                    pending.identity, status=INFERENCE_STATUS_ERROR,
                    error_code=INFERENCE_ERROR_INVALID_RESULT, error_message=message,
                )
            else:
                result = dict(outcome)
            self._complete_locked(pending, result)

    def _read_loop(self) -> None:
        failure = "推理结果读取线程意外退出"
        try:
            while not self._stop_event.is_set():
                try:
                    outcome = self.result_queue.get(timeout=_READ_TIMEOUT_SECONDS)
                except queue.Empty:
                    continue
                self._route(outcome)
        except Exception as exc:
            failure = f"推理结果读取失败: {type(exc).__name__}: {exc}"
            logger.exception(f"[{self.feature_name}] {failure}")
        finally:
            with self._lock:
                failed = self._state == "running"
                if failed:
                    self._state = "failed"
                    self._last_error = failure
                    self._stop_event.set()
                    self._finish_pending_locked()
            # 先唤醒请求，再通知运行时；通知失败不能影响请求清理。
            if failed and self._on_failure is not None:
                try:
                    self._on_failure(failure)
                except Exception:
                    logger.exception(f"[{self.feature_name}] 推理结果路由异常通知失败")
