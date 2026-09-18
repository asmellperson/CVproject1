"""有界的部门／摄像头轮询队列；网络请求不占用检测线程。"""

from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import threading
import time

from AiVision.core.logger import logger
from .schema import VlmHealth, VlmSettings
from .vlm import VlmClient

HEALTH_CHECK_INTERVAL_SEC = 30
FAILURE_THRESHOLD = 3
BACKOFF_INITIAL_SEC = 5
BACKOFF_MAX_SEC = 60


@dataclass(frozen=True)
class InspectionTask:
    session_id: str
    camera_id: int
    camera_name: str
    camera_key: str
    department: str
    roi_name: str
    start_ts: float
    end_ts: float
    generation: int
    frames: list[bytes]
    queued_at: float


class InspectionRuntime:
    def __init__(self, complete, client=None):
        self._complete = complete
        self._client = client or VlmClient()
        self._condition = threading.Condition()
        self._queues: OrderedDict[str, OrderedDict[int, deque]] = OrderedDict()
        self._threads: dict[int, threading.Thread] = {}
        self._active: dict[str, str] = {}
        self._queued = 0
        self._stopped = True
        self.settings = VlmSettings()
        self._errors: dict[str, str | None] = {}
        self._health = VlmHealth()
        self._health_thread: threading.Thread | None = None
        self._generation = 0
        self._next_check_at = 0.0
        self._backoff = BACKOFF_INITIAL_SEC
        self._half_open_session: str | None = None

    def start(self, settings: VlmSettings):
        with self._condition:
            self._stopped = False
        self.configure(settings)

    def configure(self, settings: VlmSettings):
        with self._condition:
            self.settings = settings
            self._generation += 1
            self._health = VlmHealth()
            self._next_check_at = time.monotonic()
            self._backoff = BACKOFF_INITIAL_SEC
            self._half_open_session = None
            tasks = self._drain_queue()
            stopped, generation = self._stopped, self._generation
            if not self._stopped:
                if self._health_thread is None or not self._health_thread.is_alive():
                    self._health_thread = threading.Thread(
                        target=self._check_loop, daemon=True, name="inspection-vlm-health"
                    )
                    self._health_thread.start()
                for index in range(settings.max_concurrent):
                    if index not in self._threads or not self._threads[index].is_alive():
                        thread = threading.Thread(
                            target=self._run, args=(index,), daemon=True, name=f"inspection-vlm-{index}"
                        )
                        self._threads[index] = thread
                        thread.start()
            self._condition.notify_all()
        for task in tasks:
            self._finish(task, None, "模型设置已变更，未执行旧判定任务", None)
        if stopped:
            self._check_health(settings, generation)

    def submit(self, task: InspectionTask):
        with self._condition:
            if self._stopped:
                error = "安检服务已停止"
            elif self._health.circuit_state == "open":
                error = "千问服务暂不可用，等待自动恢复检查"
            elif self._health.reachable is not True:
                error = "千问接口尚未通过健康检查，未提交判定"
            elif self._health.circuit_state == "half_open" and self._half_open_session is not None:
                error = "千问服务正在验证恢复，暂不接收其他判定"
            elif self._queued >= self.settings.queue_capacity:
                error = "安检判定队列已满"
            else:
                cameras = self._queues.setdefault(task.department, OrderedDict())
                cameras.setdefault(task.camera_id, deque()).append(task)
                self._queued += 1
                if self._health.circuit_state == "half_open":
                    self._half_open_session = task.session_id
                self._condition.notify_all()
                return
        self._finish(task, None, error, None)

    def cancel_camera(self, camera_id: int):
        cancelled = []
        with self._condition:
            for department, cameras in list(self._queues.items()):
                cancelled.extend(cameras.pop(camera_id, ()))
                if not cameras:
                    del self._queues[department]
            self._queued -= len(cancelled)
        for task in cancelled:
            self._finish(task, None, "摄像头配置已变更", None)

    def status(self, department: str) -> dict:
        with self._condition:
            return {
                "running": not self._stopped,
                "queue": sum(len(tasks) for tasks in self._queues.get(department, {}).values()),
                "active": sum(value == department for value in self._active.values()),
                "error": self._errors.get(department),
                "vlm": self.health_status().model_dump(),
            }

    def health_status(self) -> VlmHealth:
        with self._condition:
            return self._health.model_copy(
                update={
                    "retry_after_sec": max(0, math.ceil(self._next_check_at - time.monotonic()))
                    if self._health.circuit_state == "open"
                    else None,
                }
            )

    def stop(self):
        with self._condition:
            self._stopped = True
            self._generation += 1
            self._health.checking = False
            tasks = self._drain_queue()
            self._condition.notify_all()
            threads = list(self._threads.values())
            if self._health_thread is not None:
                threads.append(self._health_thread)
        for task in tasks:
            self._finish(task, None, "安检服务已停止", None)
        deadline = time.monotonic() + self.settings.api_timeout_sec + 6
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            logger.error("[security_inspection] 模型请求未在关闭期限内退出")

    def _drain_queue(self) -> list[InspectionTask]:
        """调用方持有 condition；结果回调必须在释放锁后执行。"""
        tasks = [task for cameras in self._queues.values() for queue in cameras.values() for task in queue]
        self._queues.clear()
        self._queued = 0
        return tasks

    def _record_failure(self, error: str, *, immediate: bool = False) -> list[InspectionTask]:
        self._health.last_error = error
        self._health.consecutive_failures += 1
        if (
            not immediate
            and self._health.circuit_state != "half_open"
            and self._health.consecutive_failures < FAILURE_THRESHOLD
        ):
            return []
        self._generation += 1
        self._health.reachable = False
        self._health.circuit_state = "open"
        self._health.checking = False
        self._half_open_session = None
        self._next_check_at = time.monotonic() + self._backoff
        self._backoff = min(self._backoff * 2, BACKOFF_MAX_SEC)
        self._condition.notify_all()
        return self._drain_queue()

    def _check_loop(self):
        while True:
            with self._condition:
                if self._stopped:
                    return
                delay = self._next_check_at - time.monotonic()
                if delay > 0:
                    self._condition.wait(delay)
                    continue
                settings, generation = self.settings, self._generation
            self._check_health(settings, generation)

    def _check_health(self, settings: VlmSettings, generation: int):
        with self._condition:
            if generation != self._generation:
                return
            self._health.checking = True
        probe = self._client.check_health(settings)
        tasks = []
        with self._condition:
            if generation != self._generation:
                return
            self._health.checking = False
            if not probe.reachable:
                tasks = self._record_failure(probe.last_error, immediate=True)
            else:
                self._health.reachable = True
                if self._health.circuit_state == "open":
                    # /models 可达只能证明接口恢复；须单次真实判定成功后恢复并发。
                    self._health.circuit_state = "half_open"
                self._next_check_at = time.monotonic() + HEALTH_CHECK_INTERVAL_SEC
            self._condition.notify_all()
        for task in tasks:
            self._finish(task, None, "千问服务不可用，已取消排队判定", None)

    def _run(self, index: int):
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: (
                        self._stopped
                        or (
                            index < self.settings.max_concurrent
                            and self._queued > 0
                            and self._health.reachable is True
                            and self._health.circuit_state != "open"
                        )
                    )
                )
                if self._stopped:
                    return
                department, cameras = self._queues.popitem(last=False)
                camera_id, tasks = cameras.popitem(last=False)
                task = tasks.popleft()
                if tasks:
                    cameras[camera_id] = tasks
                if cameras:
                    self._queues[department] = cameras
                self._queued -= 1
                self._active[task.session_id] = department
                settings, generation = self.settings, self._generation
            verdict, latency, error = None, None, None
            cancelled = []
            if time.monotonic() - task.queued_at > settings.queue_timeout_sec:
                error = "安检任务排队超时"
            else:
                try:
                    verdict, latency = self._client.judge(task.frames, settings)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    logger.warning(f"[security_inspection] 判定失败 session={task.session_id}: {error}")
                    with self._condition:
                        if not self._stopped and generation == self._generation:
                            # 模型响应可能含当前部门的图像描述，公共健康状态仅暴露错误类别。
                            cancelled = self._record_failure(f"千问判定请求失败（{type(exc).__name__}）")
                else:
                    with self._condition:
                        if not self._stopped and generation == self._generation:
                            self._health.reachable = True
                            self._health.last_success = datetime.now(timezone.utc)
                            self._health.last_error = None
                            self._health.consecutive_failures = 0
                            self._health.circuit_state = "closed"
                            self._backoff = BACKOFF_INITIAL_SEC
            with self._condition:
                if settings is not self.settings:
                    verdict, error = None, "模型设置已变更，已取消旧设置的判定结果"
            self._finish(task, verdict, error, latency)
            with self._condition:
                self._active.pop(task.session_id, None)
            for task in cancelled:
                self._finish(task, None, "千问服务连续失败，已取消排队判定", None)

    def _finish(self, task, verdict, error, latency):
        try:
            self._complete(task, verdict, error, latency)
        except Exception:
            logger.exception(f"[security_inspection] 保存判定失败 session={task.session_id}")
            error = "判定结果保存失败，请检查服务日志"
        with self._condition:
            self._errors[task.department] = error
            if self._half_open_session == task.session_id:
                self._half_open_session = None
