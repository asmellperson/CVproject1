"""有界的部门／摄像头轮询队列；网络请求不占用检测线程。"""

from collections import OrderedDict, deque
from dataclasses import dataclass
import threading
import time

from AiVision.core.logger import logger
from .schema import VlmSettings
from .vlm import VlmClient


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

    def start(self, settings: VlmSettings):
        with self._condition:
            self._stopped = False
        self.configure(settings)

    def configure(self, settings: VlmSettings):
        with self._condition:
            self.settings = settings
            if not self._stopped:
                for index in range(settings.max_concurrent):
                    if index not in self._threads or not self._threads[index].is_alive():
                        thread = threading.Thread(
                            target=self._run, args=(index,), daemon=True, name=f"inspection-vlm-{index}"
                        )
                        self._threads[index] = thread
                        thread.start()
            self._condition.notify_all()

    def submit(self, task: InspectionTask):
        with self._condition:
            if self._stopped:
                error = "安检服务已停止"
            elif self._queued >= self.settings.queue_capacity:
                error = "安检判定队列已满"
            else:
                cameras = self._queues.setdefault(task.department, OrderedDict())
                cameras.setdefault(task.camera_id, deque()).append(task)
                self._queued += 1
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
            }

    def stop(self):
        with self._condition:
            self._stopped = True
            tasks = [task for cameras in self._queues.values() for queue in cameras.values() for task in queue]
            self._queues.clear()
            self._queued = 0
            self._condition.notify_all()
            threads = list(self._threads.values())
        for task in tasks:
            self._finish(task, None, "安检服务已停止", None)
        deadline = time.monotonic() + self.settings.api_timeout_sec + 6
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            logger.error("[security_inspection] 模型请求未在关闭期限内退出")

    def _run(self, index: int):
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._stopped or (index < self.settings.max_concurrent and self._queued > 0)
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
                settings = self.settings
            verdict, latency, error = None, None, None
            try:
                if time.monotonic() - task.queued_at > settings.queue_timeout_sec:
                    raise TimeoutError("安检任务排队超时")
                verdict, latency = self._client.judge(task.frames, settings)
            except Exception as exc:
                # 网络和模型响应错误必须成为可查询的判定失败，不得判为违规。
                error = f"{type(exc).__name__}: {exc}"
                logger.warning(f"[security_inspection] 判定失败 session={task.session_id}: {error}")
            error = self._finish(task, verdict, error, latency)
            with self._condition:
                self._active.pop(task.session_id, None)
                self._errors[task.department] = error

    def _finish(self, task, verdict, error, latency):
        try:
            self._complete(task, verdict, error, latency)
        except Exception:
            logger.exception(f"[security_inspection] 保存判定失败 session={task.session_id}")
            error = "判定结果保存失败，请检查服务日志"
            with self._condition:
                self._errors[task.department] = error
        return error
