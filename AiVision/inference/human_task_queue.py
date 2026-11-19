"""共享人体模型的普通与非法闯闸任务入口。"""
from multiprocessing import Queue
from queue import Empty


HUMAN_MODEL_NAME = "yolo_human"
INFERENCE_INPUT_CAPACITY = 10
TAILGATING_CAPACITY = 4
DEFAULT_ORDINARY_CAPACITY = 16
_DRAIN_POLL_SECONDS = 0.05


class HumanTaskQueue:
    """闯闸任务与普通任务分别限额，共用人体模型结果契约。"""

    def __init__(
        self,
        queue_factory=Queue,
        *,
        ordinary_capacity: int = DEFAULT_ORDINARY_CAPACITY,
        tailgating_capacity: int = TAILGATING_CAPACITY,
    ):
        if ordinary_capacity < 1 or tailgating_capacity < 1:
            raise ValueError("人体任务队列容量必须大于 0")
        self._ordinary_capacity = ordinary_capacity
        self._tailgating_capacity = tailgating_capacity
        self._ordinary = queue_factory(maxsize=ordinary_capacity)
        self._tailgating = queue_factory(maxsize=tailgating_capacity)

    def put(self, task: dict, block: bool = True, timeout: float | None = None) -> None:
        target = self._tailgating if task.get("function_name") == "tailgating" else self._ordinary
        target.put(task, block=block, timeout=timeout)

    def get_ordinary_nowait(self) -> dict:
        return self._ordinary.get_nowait()

    def get_tailgating_nowait(self) -> dict:
        return self._tailgating.get_nowait()

    def discard_pending(self) -> int:
        """停止 Worker 后清两路；给进程队列发送线程留短暂收尾时间。"""
        discarded = 0
        for tasks, capacity in ((self._ordinary, self._ordinary_capacity), (self._tailgating, self._tailgating_capacity)):
            # 重载时仍可收到新任务，清理范围不随生产者补队而延长。
            for _ in range(capacity):
                try:
                    tasks.get(timeout=_DRAIN_POLL_SECONDS)
                except Empty:
                    break
                discarded += 1
        return discarded
