"""为登录后的实时状态返回计算有效期前已消耗的单调时长。"""
import time
from collections.abc import Callable

from fastapi import Request, Response


STATUS_ELAPSED_HEADER = "X-AiVision-Status-Elapsed-Ms"


def status_sample_marker(request: Request, response: Response) -> Callable[[], None]:
    """在读取 TTL 的时钟之前标记时长，仅扣除已确定经过的后端时间。"""
    response.headers["Cache-Control"] = "no-store"
    started_at = getattr(request.state, "status_request_started_ns", None)

    def mark() -> None:
        if started_at is not None:
            elapsed_ns = time.monotonic_ns() - started_at
            if elapsed_ns >= 0:
                response.headers[STATUS_ELAPSED_HEADER] = str(elapsed_ns // 1_000_000)

    return mark
