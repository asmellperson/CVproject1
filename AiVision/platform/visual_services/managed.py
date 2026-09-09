"""AiVision 进程内托管的 Guard Room 与 Security VLM 应用。"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from AiVision.core.logger import logger

VisualAppFactory = Callable[[Path], FastAPI]

# 一个子应用占位槽
class ManagedAppSlot:
    """可在父应用建路由后、启动生命周期中再绑定的 ASGI 应用槽。"""
    def __init__(self, name: str):
        self.name = name
        self._app: FastAPI | None = None               # 留好位置，还未接真正的app应用

    @property
    def app(self) -> FastAPI | None:
        return self._app

    def bind(self, app: FastAPI) -> None:
        """如果是空槽，放入真正的Guard_room FastAPI App"""
        if self._app is not None:
            raise RuntimeError(f"{self.name} 已经绑定到 AiVision")
        self._app = app

    def clear(self) -> None:
        """Aivision结束后与子应用解绑"""
        self._app = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """浏览器先请求到ManagedAppSlot，检查app=self._app,如果还没初始化，就HTTP503，如果已经绑定，就把请求原样交给真正的 Guard Room FastAPI App"""
        app = self._app
        if app is None:
            await JSONResponse(
                status_code=503,
                content={"detail": f"{self.name} 尚未由 AiVision 初始化"},
            )(scope, receive, send)
            return
        await app(scope, receive, send)

def _create_guard_room_app(config_path: Path) -> FastAPI:
    from AiVision.integrations.guard_room.src.server import create_app
    # 找到guard_room子系统自己的creat_app(),把 FastAPI App 创建出来
    return create_app(str(config_path))

def _create_security_vlm_app(config_path: Path) -> FastAPI:
    from AiVision.integrations.security_vlm.src.main import create_app

    return create_app(config_path)

class ManagedVisualServices:
    """创建并拥有两个视觉子应用及其完整生命周期。"""
    def __init__(
        self,
        *,
        guard_room_config_path: Path,
        security_vlm_config_path: Path,
        guard_room_factory: VisualAppFactory = _create_guard_room_app,
        security_vlm_factory: VisualAppFactory = _create_security_vlm_app,
    ):
        self.guard_room_config_path = Path(guard_room_config_path).resolve()
        self.security_vlm_config_path = Path(security_vlm_config_path).resolve()
        self.guard_room_factory = guard_room_factory
        self.security_vlm_factory = security_vlm_factory
        self.guard_room = ManagedAppSlot("guard_room")
        self.security_vlm = ManagedAppSlot("security_vlm")

    def _validate_config_paths(self) -> None:
        missing = [
            path
            for path in (
                self.guard_room_config_path,
                self.security_vlm_config_path,
            )
            if not path.is_file()
        ]
        if missing:
            paths = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(f"AiVision 托管视觉服务缺少配置文件: {paths}")

    @asynccontextmanager
    async def lifespan(self):
        """启动两个子应用；退出 AiVision 时按相反顺序完整关闭。"""
        self._validate_config_paths()
        guard_room_app = self.guard_room_factory(self.guard_room_config_path)
        security_vlm_app = self.security_vlm_factory(self.security_vlm_config_path)
        # 把子应用的App塞进Slot
        self.guard_room.bind(guard_room_app)
        self.security_vlm.bind(security_vlm_app)

        try:
            # AsyncExitStack()统一负责两个子应用的启动和关闭
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(
                    guard_room_app.router.lifespan_context(guard_room_app)
                )
                await stack.enter_async_context(
                    security_vlm_app.router.lifespan_context(security_vlm_app)
                )
                logger.info(
                    "[visual-services] Guard Room 与 Security VLM 已由 AiVision 进程内托管"
                )
                yield
        finally:
            self.security_vlm.clear()
            self.guard_room.clear()
