# 文件说明：定义应用装配的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
api/app.py
FastAPI 实例、CORS、中间件和路由注册。
"""
from __future__ import annotations

import threading
import time
from contextlib import asynccontextmanager
from platform.visual_services import ManagedVisualServices

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.auth import AuthError, get_current_user_from_request
from api.alarms import public_router as public_alarms_router
from api.alarms import router as alarms_router
from api.cameras import router as cameras_router
from api.departments import router as departments_router
from api.exception_alerts import router as exception_alerts_router
from api.features import router as features_router
from api.logistics_channels import router as logistics_channels_router
from api.models import router as models_router
from api.runtime import router as runtime_router
from core.alarm.wechat import WeChatNotifier
from core.logger import logger
from core.settings import settings
from core.system_config import system_config_service

_api_exception_alerts: dict[tuple[str, str], float] = {}


# 功能：发送或分发 `_send_api_exception_alert` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（str）：目标路径
#   - `detail`（str）：`detail` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：`AiVision/api/app.py` 的 `create_app::unhandled_exception_handler` 调用本符号
#   - 内部调用：`system_config_service.get_exception_alert`、`alert.get`、`str(alert.get('wechat_user') or
#          '').strip`、`str`、`time.time`、`_api_exception_alerts.get`、`float`、`threading.Thread(target=_send, daemon=True,
#          name='api-exception-alert').start`、`threading.Thread`。
# 副作用/注意事项：可能发起网络请求或发送外部消息；可能启动、等待或停止线程/进程资源。
def _send_api_exception_alert(path: str, detail: str):
    if not settings.alarm.wechat_enable:
        return
    alert = system_config_service.get_exception_alert()
    if not alert.get("wechat_enable"):
        return
    recipients = str(alert.get("wechat_user") or "").strip()
    if not recipients:
        return

    key = (path, "API 未处理异常")
    now = time.time()
    last = _api_exception_alerts.get(key, 0.0)
    cooldown_seconds = float(alert["repeat_interval_minutes"]) * 60.0
    if now - last < cooldown_seconds:
        return
    _api_exception_alerts[key] = now

    # 功能：发送或分发 `_send` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`WeChatNotifier().send_text`、`WeChatNotifier`、`time.strftime`、`logger.warning`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；会向日志系统输出运行或异常信息。
    def _send():
        try:
            WeChatNotifier().send_text(
                content=(
                    "AiVision 系统异常\n"
                    f"**对象**: API\n"
                    f"**标识**: {path}\n"
                    f"**类型**: API 未处理异常\n"
                    f"**详情**: {detail}\n"
                    f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                ),
                recipients=recipients,
            )
        except Exception as exc:
            logger.warning(f"[API] 异常企微推送失败: {exc}")

    threading.Thread(target=_send, daemon=True, name="api-exception-alert").start()


# 功能：创建或构建 `create_app` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `managed_visual_services`（ManagedVisualServices | None）：`managed_visual_services` 对应的业务输入值；默认值为 `None`
# 返回：FastAPI；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ManagedVisualServices`、`FastAPI`、`app.add_middleware`、`app.include_router`、`app.mount`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def create_app(
    *,
    managed_visual_services: ManagedVisualServices | None = None,
) -> FastAPI:
    visual_services = managed_visual_services or ManagedVisualServices(
        guard_room_config_path=settings.visual_services.guard_room_config_path,
        security_vlm_config_path=settings.visual_services.security_vlm_config_path,
    )

    # 功能：实现 `lifespan` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `app`（FastAPI）：`app` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`visual_services.lifespan`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.managed_visual_services = visual_services
        async with visual_services.lifespan():
            yield

    app = FastAPI(
        title="AiVision Backend",
        version="2.0.0",
        description="AiVision features-first refactored backend.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 功能：实现 `auth_middleware` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `request`（Request）：当前 HTTP 请求及上下文
    #   - `call_next`（未显式标注）：`call_next` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`path.startswith`、`call_next`、`get_current_user_from_request`、`JSONResponse`、`str`、`app.middleware`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        public_paths = {"/api/runtime/health"}
        if request.method == "OPTIONS" or path in public_paths or path.startswith("/api/public/"):
            return await call_next(request)
        if path.startswith("/api/"):
            try:
                request.state.user = get_current_user_from_request(request)
            except AuthError as exc:
                return JSONResponse(status_code=401, content={"detail": str(exc)})
        return await call_next(request)

    # 功能：实现 `unhandled_exception_handler` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `request`（Request）：当前 HTTP 请求及上下文
    #   - `exc`（Exception）：`exc` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`logger.exception`、`_send_api_exception_alert`、`str`、`JSONResponse`、`app.exception_handler`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；会向日志系统输出运行或异常信息。
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(f"[API] 未处理异常: {request.method} {request.url.path}: {exc}")
        _send_api_exception_alert(request.url.path, str(exc))
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    # 功能：实现 `root` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/")
    def root():
        return {"name": "AiVision", "version": "2.0.0", "docs": "/docs"}

    app.include_router(runtime_router)
    app.include_router(exception_alerts_router)
    app.include_router(cameras_router)
    app.include_router(features_router)
    app.include_router(models_router)
    app.include_router(alarms_router)
    app.include_router(public_alarms_router)
    app.include_router(departments_router)
    app.include_router(logistics_channels_router)

    # 两套视觉服务直接运行在 AiVision 进程中。这里是 ASGI 子应用挂载，
    # 不发起 HTTP 请求，也不需要 Guard Room / Security VLM 独立端口。
    app.mount(
        "/api/integrations/guard-room",
        visual_services.guard_room,
        name="guard-room",
    )
    app.mount(
        "/api/integrations/security-vlm",
        visual_services.security_vlm,
        name="security-vlm",
    )

    return app


app = create_app()
