"""每台摄像头保留当前请求与最近一次结果，查询不接触图像、模型或通信凭据。"""
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
import time
from typing import TYPE_CHECKING

from .schema import AgvRequestStatus, PersonCheckResult

if TYPE_CHECKING:
    from .service import CheckRequest, PersonCheckError


class AgvRequestMonitor:
    """用独立短锁发布状态，避免监控轮询等待采样或 HTTP 回调。"""

    def __init__(self):
        self._lock = Lock()
        self._active: dict[int, AgvRequestStatus] = {}
        self._latest: dict[int, AgvRequestStatus] = {}
        self._started_at: dict[int, float] = {}

    def accept(self, request: "CheckRequest"):
        value = AgvRequestStatus(
            request_id=request.request_id, camera_key=request.camera_key, mode=request.config.http.mode,
            started_at=datetime.fromtimestamp(request.created_at, timezone.utc),
            sample_target=request.config.sample_count,
        )
        with self._lock:
            self._active[request.camera_id] = value
            self._started_at[request.camera_id] = request.started_at

    def progress(self, request: "CheckRequest"):
        with self._lock:
            value = self._active.get(request.camera_id)
            if value is not None and value.request_id == request.request_id and value.state == "detecting":
                self._active[request.camera_id] = value.model_copy(update={"sample_count": request.sample_count})

    def _finish(self, request: "CheckRequest", **changes):
        with self._lock:
            value = self._active.get(request.camera_id)
            if value is None or value.request_id != request.request_id:
                return
            value = value.model_copy(update={
                "finished_at": value.finished_at or datetime.fromtimestamp(time.time(), timezone.utc),
                "duration_seconds": value.duration_seconds if value.finished_at else max(0.0, time.monotonic() - request.started_at),
                "sample_count": request.sample_count, **changes,
            })
            self._active[request.camera_id] = value
            self._latest[request.camera_id] = value

    def complete(self, request: "CheckRequest", result: PersonCheckResult):
        self._finish(request, state="completed", person_present=result.person_present)

    def fail(self, request: "CheckRequest", error: "PersonCheckError"):
        self._finish(request, state="cancelled" if error.code == "cancelled" else "error",
                     person_present=None, error_code=error.code, error=str(error), delivery_state="not_sent")

    def delivery(self, request: "CheckRequest", *, state: str, body=None, status_code: int | None = None,
                 error: str | None = None):
        changes = {"delivery_state": state, "delivery_status_code": status_code, "delivery_error": error}
        if body is not None:
            changes["response_body"] = deepcopy(body)
        with self._lock:
            # 按请求 ID 更新，晚到的旧回调不能覆盖新请求的结果。
            for values in (self._active, self._latest):
                value = values.get(request.camera_id)
                if value is not None and value.request_id == request.request_id:
                    values[request.camera_id] = value.model_copy(update=changes)

    def release(self, request: "CheckRequest"):
        with self._lock:
            value = self._active.get(request.camera_id)
            if value is not None and value.request_id == request.request_id:
                self._active.pop(request.camera_id)
                self._started_at.pop(request.camera_id, None)

    def status(self, camera_id: int) -> tuple[AgvRequestStatus | None, AgvRequestStatus | None]:
        with self._lock:
            active = self._active.get(camera_id)
            if active is not None and active.state == "detecting":
                active = active.model_copy(update={
                    "duration_seconds": max(0.0, time.monotonic() - self._started_at[camera_id]),
                })
            latest = self._latest.get(camera_id)
            return (active.model_copy(deep=True) if active is not None else None,
                    latest.model_copy(deep=True) if latest is not None else None)

    def clear_camera(self, camera_id: int):
        with self._lock:
            self._active.pop(camera_id, None)
            self._latest.pop(camera_id, None)
            self._started_at.pop(camera_id, None)

    def clear(self):
        with self._lock:
            self._active.clear()
            self._latest.clear()
            self._started_at.clear()
