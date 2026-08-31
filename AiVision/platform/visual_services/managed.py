# 文件说明：实现`managed` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""AiVision 进程内托管的 Guard Room 与 Security VLM 应用。"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from core.logger import logger

VisualAppFactory = Callable[[Path], FastAPI]


# 功能：可在父应用建路由后、启动生命周期中再绑定的 ASGI 应用槽；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
# 返回：ManagedAppSlot；返回新建的 `ManagedAppSlot` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/visual_services/managed.py` 的 `ManagedVisualServices::__init__` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ManagedAppSlot:
    """可在父应用建路由后、启动生命周期中再绑定的 ASGI 应用槽。"""

    # 功能：初始化或配置 `__init__` 对应的`managed` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `name`（str）：业务对象名称
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, name: str):
        self.name = name
        self._app: FastAPI | None = None

    # 功能：实现 `app` 对应的`managed` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：FastAPI | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/visual_services/managed.py` 的 `ManagedAppSlot::__call__` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def app(self) -> FastAPI | None:
        return self._app

    # 功能：实现 `bind` 对应的`managed` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `app`（FastAPI）：`app` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/visual_services/managed.py` 的 `ManagedVisualServices::lifespan` 调用本符号
    #   - 内部调用：`RuntimeError`。
    # 副作用/注意事项：会更新当前实例的运行状态；校验或执行失败时会主动抛出异常。
    def bind(self, app: FastAPI) -> None:
        if self._app is not None:
            raise RuntimeError(f"{self.name} 已经绑定到 AiVision")
        self._app = app

    # 功能：删除或清理 `clear` 对应的`managed` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/visual_services/managed.py` 的 `ManagedVisualServices::lifespan`
    #         调用本符号；`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::start`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::start`
    #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_clear_all_state_locked` 调用本符号；另有
    #         25 处静态调用
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def clear(self) -> None:
        self._app = None

    # 功能：实现 `__call__` 对应的`managed` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `scope`（Scope）：`scope` 对应的业务输入值
    #   - `receive`（Receive）：`receive` 对应的业务输入值
    #   - `send`（Send）：`send` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`JSONResponse(status_code=503, content={'detail': f'{self.name} 尚未由 AiVision 初始化'})`、`JSONResponse`、`app`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        app = self._app
        if app is None:
            await JSONResponse(
                status_code=503,
                content={"detail": f"{self.name} 尚未由 AiVision 初始化"},
            )(scope, receive, send)
            return
        await app(scope, receive, send)


# 功能：创建或构建 `_create_guard_room_app` 对应的`managed` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `config_path`（Path）：`config_path` 对应的业务输入值
# 返回：FastAPI；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`create_app`、`str`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _create_guard_room_app(config_path: Path) -> FastAPI:
    from integrations.guard_room.src.server import create_app

    return create_app(str(config_path))


# 功能：创建或构建 `_create_security_vlm_app` 对应的`managed` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `config_path`（Path）：`config_path` 对应的业务输入值
# 返回：FastAPI；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`create_app`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _create_security_vlm_app(config_path: Path) -> FastAPI:
    from integrations.security_vlm.src.main import create_app

    return create_app(config_path)


# 功能：创建并拥有两个视觉子应用及其完整生命周期；输入与输出详见下方说明
# 参数：
#   - `guard_room_config_path`（Path）：`guard_room_config_path` 对应的业务输入值
#   - `security_vlm_config_path`（Path）：`security_vlm_config_path` 对应的业务输入值
#   - `guard_room_factory`（VisualAppFactory）：`guard_room_factory` 对应的业务输入值；默认值为 `_create_guard_room_app`
#   - `security_vlm_factory`（VisualAppFactory）：`security_vlm_factory` 对应的业务输入值；默认值为 `_create_security_vlm_app`
# 返回：ManagedVisualServices；返回新建的 `ManagedVisualServices` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_managed_visual_services.py` 的 `_manager` 实例化本符号；`AiVision/tests/test_managed_visual_services.py` 的
#         `test_missing_child_config_fails_parent_startup` 实例化本符号；`AiVision/api/app.py` 的 `create_app` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ManagedVisualServices:
    """创建并拥有两个视觉子应用及其完整生命周期。"""

    # 功能：初始化或配置 `__init__` 对应的`managed` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `guard_room_config_path`（Path）：`guard_room_config_path` 对应的业务输入值
    #   - `security_vlm_config_path`（Path）：`security_vlm_config_path` 对应的业务输入值
    #   - `guard_room_factory`（VisualAppFactory）：`guard_room_factory` 对应的业务输入值；默认值为 `_create_guard_room_app`
    #   - `security_vlm_factory`（VisualAppFactory）：`security_vlm_factory` 对应的业务输入值；默认值为 `_create_security_vlm_app`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path(guard_room_config_path).resolve`、`Path`、`Path(security_vlm_config_path).resolve`、`ManagedAppSlot`。
    # 副作用/注意事项：会更新当前实例的运行状态。
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

    # 功能：检查或判断 `_validate_config_paths` 对应的`managed` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/visual_services/managed.py` 的 `ManagedVisualServices::lifespan` 调用本符号
    #   - 内部调用：`path.is_file`、`', '.join`、`str`、`FileNotFoundError`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
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

    # 功能：启动两个子应用；退出 AiVision 时按相反顺序完整关闭；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._validate_config_paths`、`self.guard_room_factory`、`self.security_vlm_factory`、`self.guard_room.bind`、`self.security_vlm.bind`、`AsyncExitStack`、`stack.enter_async_context`、`guard_room_app.router.lifespan_context`、`security_vlm_app.router.lifespan_context`、`logger.info`
    #          等共 12 个调用。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    @asynccontextmanager
    async def lifespan(self):
        """启动两个子应用；退出 AiVision 时按相反顺序完整关闭。"""
        self._validate_config_paths()
        guard_room_app = self.guard_room_factory(self.guard_room_config_path)
        security_vlm_app = self.security_vlm_factory(self.security_vlm_config_path)
        self.guard_room.bind(guard_room_app)
        self.security_vlm.bind(security_vlm_app)

        try:
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
