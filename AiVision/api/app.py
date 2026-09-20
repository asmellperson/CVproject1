from __future__ import annotations

import threading
import time                                                        # 获取当前时间戳，用来判断异常报警是否还在冷却期

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware                 # 跨域访问控制
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse                         # 手工构造JSON HTTP响应

from auth.api import router as auth_router
from auth.auth import AuthError, get_current_user_from_request     # 认证模块

# 拿取每个API文件里的路由，最后统一注册到FastAPI
from AiVision.api.routes.alarms import public_router as public_alarms_router
from AiVision.api.routes.alarms import router as alarms_router              # 正常需要认证的报警
from AiVision.api.routes.cameras import router as cameras_router            # 对外公开、不要求普通认证的报警资源
from AiVision.api.routes.departments import router as departments_router
from AiVision.api.routes.exception_alerts import router as exception_alerts_router
from AiVision.api.routes.features import router as features_router
from AiVision.api.routes.face_recognition import router as face_recognition_router
from AiVision.api.routes.logistics_channels import router as logistics_channels_router
from AiVision.api.routes.guard_behavior import router as guard_behavior_router
from AiVision.api.routes.security_inspection import router as security_inspection_router
from AiVision.api.routes.models import router as models_router
from AiVision.api.routes.horns import router as horns_router
from AiVision.api.routes.runtime import router as runtime_router
from AiVision.api.routes.overview import router as overview_router
from AiVision.api.routes.alarm_dispositions import router as alarm_dispositions_router

from AiVision.alarms.notifications.wechat import WeChatNotifier               # 调用企业微信发送报警信息
from AiVision.core.logger import logger                             # 项目统一日志对象
from AiVision.core.settings import settings                         # 全局settings（.env、默认值、运行参数）
from AiVision.core.system_config import system_config_service       # 系统业务配置（管理页面可以修改的运行期间业务配置）

# API 报警冷却记录表
_api_exception_alerts: dict[tuple[str, str], float] = {}


def _send_api_exception_alert(path: str, detail: str):
    """
    当某个API出现未处理异常时，判断要不要发企业微信报警，如果要发，就异步开线程发送
    参数：
        path:哪个API出错
        detail: 具体异常信息
    """
    # 检查企业微信报警功能有没有打开
    if not settings.alarm.wechat_enable:
        return
    # 获取异常报警的配置
    alert = system_config_service.get_exception_alert()
    # 检查异常报警自己的开关
    if not alert.get("wechat_enable"):
        return
    # 获取接收人（所以走三层验证，一层是微信报警的总开关，一层是异常报警自己的开关，最后是接收人有没有）
    recipients = str(alert.get("wechat_user") or "").strip()
    if not recipients:
        return
    # 构造异常唯一标识
    key = (path, "API 未处理异常")
    # 获取当前时间
    now = time.time()
    # 查询上一次报警时间
    last = _api_exception_alerts.get(key, 0.0)
    # 重复报警的冷却时间
    cooldown_seconds = float(alert["repeat_interval_minutes"]) * 60.0
    # 判断是否再冷却期
    if now - last < cooldown_seconds:
        return
    _api_exception_alerts[key] = now                  # 在真正发送企业微信之前，就先记录当前时间

    def _send():
        """
        负责真正发送企业微信消息
        """
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
    # 创建后台线程去发送企业微信
    threading.Thread(target=_send, daemon=True, name="api-exception-alert").start()


def create_app() -> FastAPI:
    """组装 AiVision 原生 API；检测生命周期由 Orchestrator 管理。"""
    # 创建FastAPI
    app = FastAPI(
        title="AiVision Backend",                                 # 主要用于Swagger文档
        version="2.0.0",
        description="AiVision features-first refactored backend.",
    )

    # 给整个AiVision HTTP服务增加跨域访问规则
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,        # 假设settings.api.cors_origins = ["http://localhost:xxxx"]，那么前端可以通过localhost:xxxx访问它              
        allow_credentials=True,                         # 表示允许跨域请求携带Cookie认证信息
        allow_methods=["*"],                            # 表示允许所有GET、POST、PUT、PATCH等等所有HTTP方法
        allow_headers=["*"],                            # 允许前端携带各种Header
    )

    # 定义认证中间件,所有HTTP请求都会先经过它
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """
        参数：
            request:当前这一次的HTTP请求
            call_next:继续往后走
        """
        path = request.url.path
        # 先列出公共接口
        public_paths = {"/api/runtime/health", "/api/auth/login", "/api/auth/logout"}
        # 服务探针不读取业务数据，无需登录；业务接口仍按原认证流程处理。
        if request.method == "OPTIONS" or path in public_paths or path.startswith("/api/public/"):
            return await call_next(request)
        if path.startswith("/api/"):
            try:
                # 解析用户，将用户保存到这一次的Request的状态里，而各api下的各函数下的get_current_user负责从request.state.user里面把用户提供给具体函数
                request.state.user = await run_in_threadpool(get_current_user_from_request, request)
            # 认证失败
            except AuthError as exc:
                return JSONResponse(status_code=401, content={"detail": str(exc)})
        return await call_next(request)

    # 定义全局异常处理器，捕获没有被其他代码处理掉的异常
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(f"[API] 未处理异常: {request.method} {request.url.path}: {exc}")
        # 调用_send_api_exception_alert()
        _send_api_exception_alert(request.url.path, str(exc))
        # 返回HTTP 500
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    # 根路径接口，告诉访问者这个服务是什么
    @app.get("/")
    def root():
        return {"name": "AiVision", "version": "2.0.0", "docs": "/docs"}

    # 注册所有普通API
    app.include_router(auth_router)
    app.include_router(runtime_router)
    app.include_router(exception_alerts_router)
    app.include_router(cameras_router)
    app.include_router(features_router)
    app.include_router(face_recognition_router)
    app.include_router(models_router)
    app.include_router(horns_router)
    app.include_router(alarms_router)
    app.include_router(alarm_dispositions_router)
    app.include_router(overview_router)
    app.include_router(public_alarms_router)
    app.include_router(departments_router)
    app.include_router(logistics_channels_router)
    app.include_router(guard_behavior_router)

    app.include_router(security_inspection_router)

    return app


app = create_app()
