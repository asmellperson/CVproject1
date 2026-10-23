"""在 HTTP 服务排空请求之前关闭 AGV 接收入口。"""
from collections.abc import Callable
from types import FrameType

import uvicorn


class GracefulServer(uvicorn.Server):
    """由 Uvicorn 等待响应和后台回调，业务资源在 Server 退出后清理。"""

    def __init__(self, config: uvicorn.Config, *, on_shutdown: Callable[[], None]):
        super().__init__(config)
        self._on_shutdown = on_shutdown
        self._shutdown_started = False

    def _begin_shutdown(self):
        if not self._shutdown_started:
            self._shutdown_started = True
            self._on_shutdown()

    def handle_exit(self, sig: int, frame: FrameType | None):
        # 信号回调只关闭入口，不能在事件循环线程等待尚未结束的 HTTP 回传。
        self._begin_shutdown()
        super().handle_exit(sig, frame)

    async def shutdown(self, sockets=None):
        # 同样覆盖直接设置 should_exit 的正常退出路径。
        self._begin_shutdown()
        await super().shutdown(sockets=sockets)
