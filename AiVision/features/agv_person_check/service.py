"""管理检测请求、采样窗口和多帧聚合，不处理 HTTP 协议。"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from uuid import uuid4

import numpy as np

from AiVision.core.logger import logger

from .schema import AgvPersonCheckValueSchema, PersonCheckResult

MAX_PENDING_REQUESTS = 32
POLL_INTERVAL_SECONDS = 0.05


class PersonCheckError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(eq=False)
class CheckRequest:
    camera_id: int
    camera_key: str
    config: AgvPersonCheckValueSchema
    runtime_config: dict
    request_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: float = field(default_factory=time.time)
    started_at: float = field(default_factory=time.monotonic)
    future: Future[PersonCheckResult] = field(default_factory=Future)
    error: PersonCheckError | None = None
    sample_count: int = 0
    next_sample_at: float = 0.0
    last_frame: np.ndarray | None = None

    @property
    def deadline(self) -> float:
        return self.started_at + self.config.request_timeout_seconds


class AgvPersonCheckService:
    """每台摄像头同时接收一个请求，在现有 Consumer 线程内轮询采样。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._requests: dict[int, CheckRequest] = {}

    def submit(self, camera_id: int, camera_key: str, cfg: dict) -> CheckRequest:
        with self._lock:
            if camera_id in self._requests:
                raise PersonCheckError("busy", "该摄像头已有检测请求尚未结束")
            if len(self._requests) >= MAX_PENDING_REQUESTS:
                raise PersonCheckError("busy", "AGV 检测请求已达到并发上限")
            config = AgvPersonCheckValueSchema.model_validate({
                name: cfg[name] for name in AgvPersonCheckValueSchema.model_fields
            })
            try:
                config.http.require_ready()
            except ValueError as exc:
                raise PersonCheckError("not_configured", str(exc)) from exc
            request = CheckRequest(camera_id, camera_key, config, cfg)
            self._requests[camera_id] = request
            self._wake.set()
            return request

    def release(self, request: CheckRequest):
        """响应或回调结束后释放容量，避免慢回调产生无界后台任务。"""
        with self._lock:
            if self._requests.get(request.camera_id) is request:
                self._requests.pop(request.camera_id)
            if not request.future.done():
                request.future.set_exception(PersonCheckError("cancelled", "检测请求已取消"))
            request.last_frame = None
            self._wake.set()

    def cancel_camera(self, camera_id: int):
        with self._lock:
            request = self._requests.get(camera_id)
            if request is not None:
                self._fail(request, PersonCheckError("cancelled", "摄像头配置或启用状态已变更，请重新检测"))

    def stop(self):
        with self._lock:
            for request in self._requests.values():
                self._fail(request, PersonCheckError("unavailable", "AGV 检测功能已停止"))
            self._requests.clear()
            self._wake.set()

    def _fail(self, request: CheckRequest, error: PersonCheckError):
        request.error = error
        if not request.future.done():
            request.future.set_exception(error)

    def run(self, sample: Callable, is_running: Callable[[], bool], on_result: Callable):
        while is_running():
            self._wake.clear()
            with self._lock:
                requests = list(self._requests.values())
            for request in requests:
                if not is_running():
                    return
                with self._lock:
                    if request.future.done():
                        continue
                    now = time.monotonic()
                    if now >= request.deadline:
                        self._fail(request, PersonCheckError("timeout", "检测超时，未获得足够有效帧"))
                        continue
                    if now < request.next_sample_at:
                        continue
                try:
                    sampled = sample(request)
                    with self._lock:
                        if request.future.done():
                            continue
                        now = time.monotonic()
                        if now >= request.deadline:
                            raise PersonCheckError("timeout", "检测超时，结果不再有效")
                        if sampled is None:
                            continue
                        frame, result = sampled
                        request.last_frame = frame
                        request.sample_count += 1
                        request.next_sample_at = now + request.config.cap_interval
                        # 一帧有人即可确认；无人必须完成整个采样窗口。
                        if result.person_present or request.sample_count >= request.config.sample_count:
                            request.future.set_result(result)
                        else:
                            continue
                    # 判定完成后停止采样；报警使用本次快照，且不持有请求锁执行外部操作。
                    on_result(request, result, frame)
                except PersonCheckError as exc:
                    with self._lock:
                        self._fail(request, exc)
                except Exception:  # noqa: BLE001 -- 单个请求异常必须结束 Future，不能中断整个 Consumer。
                    logger.exception(f"[agv_person_check] 检测异常 request_id={request.request_id}")
                    with self._lock:
                        self._fail(request, PersonCheckError("unavailable", "检测处理异常，请检查运行状态"))
            self._wake.wait(POLL_INTERVAL_SECONDS)
