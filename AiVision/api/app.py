"""
api/app.py
FastAPI 实例、CORS、中间件和路由注册。
"""
from __future__ import annotations

import threading
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.auth import AuthError, get_current_user_from_request
from core.alarm.wechat import WeChatNotifier
from core.logger import logger
from core.settings import settings
from core.system_config import system_config_service
from api.v2.cameras import router as cameras_router
from api.v2.features import router as features_router
from api.v2.models import router as models_router
from api.v2.runtime import router as runtime_router
from api.v2.alarms import router as alarms_router
from api.compat import router as compat_router


_api_exception_alerts: dict[tuple[str, str], float] = {}
_API_EXCEPTION_ALERT_COOLDOWN = 300.0


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
    if now - last < _API_EXCEPTION_ALERT_COOLDOWN:
        return
    _api_exception_alerts[key] = now

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


def create_app() -> FastAPI:
    app = FastAPI(
        title="AiVision Backend",
        version="2.0.0",
        description="AiVision features-first refactored backend with API v2 and legacy compatibility routes.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        public_paths = {"/api/v2/runtime/health"}
        if request.method == "OPTIONS" or path in public_paths:
            return await call_next(request)
        if path.startswith("/api/"):
            try:
                request.state.user = get_current_user_from_request(request)
            except AuthError as exc:
                return JSONResponse(status_code=401, content={"detail": str(exc)})
        return await call_next(request)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(f"[API] 未处理异常: {request.method} {request.url.path}: {exc}")
        _send_api_exception_alert(request.url.path, str(exc))
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    @app.get("/")
    def root():
        return {"name": "AiVision", "version": "2.0.0", "docs": "/docs"}

    app.include_router(runtime_router)
    app.include_router(cameras_router)
    app.include_router(features_router)
    app.include_router(models_router)
    app.include_router(compat_router)
    app.include_router(alarms_router)

    return app


app = create_app()
