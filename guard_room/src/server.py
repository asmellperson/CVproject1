# server.py
"""
FastAPI Web 服务模块。

将系统的核心功能（检测控制、状态查询、报警管理、视频流）
以 RESTful API 的形式暴露给前端，同时处理认证与跨域。

API 分组：
    /api/auth/*        —— 登录、登出、当前用户信息
    /api/control/*     —— 检测系统启动/停止/重启（需 admin）
    /api/config        —— 配置读取与更新（更新需 admin）
    /api/alarms/*      —— 报警列表、截图、视频
    /api/statistics    —— 统计信息
    /api/frame.jpg     —— 最新帧快照
    /api/stream.mjpg   —— MJPEG 推流

认证机制：
    HTTP 中间件拦截所有 /api/* 请求（公开路径除外），
    通过 auth.py 的 get_current_user_from_request() 验证 Token。
    公开路径：/ 、/api/health、/api/auth/login、/api/auth/logout。

CORS：
    允许的源由环境变量 AUTH_CORS_ORIGINS 控制（逗号分隔），
    默认包含本地开发地址和生产域名。
"""
from __future__ import annotations

import os
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

from .auth import (
    AuthError,
    ChangePasswordRequest,
    LoginRequest,
    change_own_password,
    clear_auth_cookie,
    create_token,
    get_current_user,
    get_current_user_from_request,
    require_admin,
    set_auth_cookie,
    verify_login,
)
from .config import AppConfig
from .runtime import GuardRoomRuntime
from .state import AppState
from .wechat_notifier import WeChatNotifier


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

class ConfigUpdateRequest(BaseModel):
    """配置更新请求体。

    各字段均为可选，前端只需传入需要修改的配置节，未传入的节保持不变。
    字段名与 AppConfig 子配置的节名称一一对应，便于按名索引更新。
    """
    video: Optional[dict] = None
    models: Optional[dict] = None
    room: Optional[dict] = None
    rules: Optional[dict] = None
    classes: Optional[dict] = None
    runtime: Optional[dict] = None
    wechat: Optional[dict] = None


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def _cors_origins() -> list[str]:
    """从环境变量 AUTH_CORS_ORIGINS 读取允许的 CORS 源列表。

    多个源用逗号分隔；未配置时回落到本地开发地址和生产域名。
    生产环境应通过环境变量明确指定，避免开发地址被保留在白名单中。
    """
    raw = os.getenv(
        "AUTH_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,https://aicv.fudar.com",
    )
    return [item.strip() for item in raw.split(",") if item.strip()]


def create_app(config_path: str = "config/config.yaml") -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    采用工厂函数模式（而非模块级全局对象），便于在测试中注入不同配置。
    所有路由均闭包引用此函数内的 runtime / state / cfg 对象，无全局状态。

    Args:
        config_path: YAML 配置文件路径，默认 "config/config.yaml"。

    Returns:
        配置完毕、已注册所有路由的 FastAPI 实例。
    """
    # ── 初始化核心对象 ────────────────────────────────────────────────────
    cfg = AppConfig.from_yaml(config_path)
    state = AppState(cfg, config_path=config_path)  # 全局共享状态，供运行时写入、API 读取

    wechat_notifier = None
    if cfg.wechat.enable:
        wechat_notifier = WeChatNotifier(
            corpid=cfg.wechat.corpid,
            corpsecret=cfg.wechat.corpsecret,
            agentid=cfg.wechat.agentid,
        )

    runtime = GuardRoomRuntime(
        config=cfg,
        state=state,
        wechat_notifier=wechat_notifier,
        alarm_user=cfg.wechat.alarm_user,
        alarm_camera_name=cfg.wechat.camera_name,
    )

    # ── 创建 FastAPI 实例并注册中间件 ──────────────────────────────────────
    app = FastAPI(title="Guard Room API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,     # 允许携带 Cookie，JWT 认证必须
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """HTTP 认证中间件：拦截所有 /api/* 请求，验证 Token。

        公开路径和 OPTIONS 预检请求直接放行，不做认证。
        认证通过后将用户信息写入 request.state.user，供路由函数读取。
        认证失败返回 401，不暴露具体错误细节。
        """
        path = request.url.path
        public_paths = {"/", "/api/health", "/api/auth/login", "/api/auth/logout"}
        if request.method == "OPTIONS" or path in public_paths:
            return await call_next(request)
        if path.startswith("/api/"):
            try:
                request.state.user = get_current_user_from_request(request)
            except AuthError as exc:
                return JSONResponse(status_code=401, content={"detail": str(exc)})
        return await call_next(request)

    # ── 认证路由 ─────────────────────────────────────────────────────────

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, request: Request, response: Response):
        """验证工号与密码，成功后签发 JWT 并写入 HttpOnly Cookie。

        Cookie 与响应体中均返回 Token，兼顾浏览器（Cookie）和 API 客户端（JSON）。
        认证失败统一返回 401，不区分"工号不存在"和"密码错误"，防止枚举攻击。
        """
        user = verify_login(payload.employee_id, payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid employee_id or password")
        token = create_token(user)
        set_auth_cookie(response, token, request)
        return {"success": True, "user": user}

    @app.get("/api/auth/me")
    def me(user: dict = Depends(get_current_user)):
        """返回当前已登录用户的信息，常用于前端刷新页面后恢复登录状态。"""
        return {"success": True, "user": user}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        """清除认证 Cookie，完成登出。Token 本身无法主动失效（无服务端存储），
        依赖 Cookie 删除使浏览器不再携带凭证。"""
        clear_auth_cookie(response, request)
        return {"success": True}

    @app.post("/api/auth/password")
    def change_password(payload: ChangePasswordRequest, user: dict = Depends(get_current_user)):
        """修改当前登录用户自己的密码。"""
        try:
            updated_user = change_own_password(
                user.get("employee_id", ""),
                payload.current_password,
                payload.new_password,
            )
        except AuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, "user": updated_user}

    # ── 基础路由 ─────────────────────────────────────────────────────────

    @app.get("/")
    def root():
        """根路径：返回服务基本信息，供反向代理健康探测或人工确认服务身份。"""
        return {
            "name": "guard-room-api",
            "ok": True,
            "frontend": "https://aicv.fudar.com",
            "health": "/api/health",
        }

    @app.get("/api/health")
    def health():
        """健康检查端点，无需认证。

        反映真实就绪状态供冷启动脚本与负载均衡器判定：
            ready  = 服务进程正常运行（runtime 启动/停止是管理员按需操作，不影响就绪判定）
            有 error 时返回 503
        """
        with state._lock:
            running = state.running
            error = state.error
        has_error = error is not None
        payload = {
            "status": "error" if has_error else "ok",
            "ready": not has_error,
            "running": bool(running),
            "error": error,
            "port": int(os.getenv("GUARD_ROOM_PORT", "5000")),
        }
        if has_error:
            return JSONResponse(payload, status_code=503)
        return payload

    @app.get("/api/status")
    def status():
        """返回系统运行状态快照（是否运行、FPS、当前帧计数、最新报警等）。"""
        return state.get_status()

    # ── 配置路由 ─────────────────────────────────────────────────────────

    @app.get("/api/config")
    def get_config():
        """返回当前完整配置字典（含所有子节），供前端配置页面回显。"""
        return state.get_config_dict()

    @app.post("/api/config")
    def update_config(payload: ConfigUpdateRequest, _user: dict = Depends(require_admin)):
        """更新配置并持久化到 YAML 文件（需 admin）。

        更新策略：局部合并（patch），只修改请求体中出现的字段，
        未传入的字段保持原值，避免误清空其他配置节。

        注意：runtime.cfg 在此处直接替换为新配置对象，
        但运行中的子模块（BehaviorEngine、共识引擎等）持有旧配置引用，
        修改大多数阈值参数需重启检测才能完全生效。
        """
        current = state.get_config_dict()

        for section_name in ["video", "models", "room", "rules", "classes", "runtime", "wechat"]:
            incoming = getattr(payload, section_name)   # 按节名取请求体对应字段
            if incoming:
                current[section_name].update(incoming) # 局部合并，不覆盖未传入的字段

        # 持久化到 YAML（覆写）
        import yaml
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(current, f, allow_unicode=True, sort_keys=False)

        # 重新加载配置并更新 state 和 runtime 的引用
        new_cfg = AppConfig.from_yaml(config_path)
        state.set_config(new_cfg, config_path=config_path)
        runtime.cfg = new_cfg

        return {"success": True, "config": state.get_config_dict()}

    # ── 检测控制路由 ──────────────────────────────────────────────────────

    @app.post("/api/control/start")
    def start_runtime(_user: dict = Depends(require_admin)):
        """启动检测系统（需 admin）。已运行时幂等，不重复启动。"""
        runtime.start()
        return {"success": True, "running": True}

    @app.post("/api/control/stop")
    def stop_runtime(_user: dict = Depends(require_admin)):
        """停止检测系统（需 admin），等待主循环线程退出后返回。"""
        runtime.stop()
        return {"success": True, "running": False}

    @app.post("/api/control/restart")
    def restart_runtime(_user: dict = Depends(require_admin)):
        """重启检测系统（需 admin）：先停止再启动，使新配置完全生效。"""
        runtime.stop()
        runtime.start()
        return {"success": True, "running": True}

    # ── 报警路由 ─────────────────────────────────────────────────────────

    @app.get("/api/alarms")
    def get_alarms(limit: int = 50):
        """返回最近 limit 条报警记录列表，按时间倒序排列。"""
        return {"items": state.get_alarms(limit=limit)}

    @app.get("/api/alarms/{alarm_id}/image")
    def get_alarm_image(alarm_id: str):
        """返回指定报警的 JPEG 快照文件。

        文件不存在时（已被清理或移动）返回 404，
        错误信息中包含原始路径，便于运维排查。
        """
        alarm = state.get_alarm(alarm_id)
        if not alarm:
            raise HTTPException(status_code=404, detail="报警不存在")

        image_path = alarm.get("image_path")
        if not image_path:
            raise HTTPException(status_code=404, detail="该报警无截图")

        path = Path(image_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"截图文件已被清理或移动: {image_path}")

        return FileResponse(str(path), media_type="image/jpeg")

    @app.get("/api/alarms/{alarm_id}/video")
    def get_alarm_video(alarm_id: str):
        """返回指定报警的 MP4 视频片段文件。

        视频在报警触发后由 AlarmClipRecorder 异步录制，
        录制未完成时 video_path 为空，返回 404。
        """
        alarm = state.get_alarm(alarm_id)
        if not alarm:
            raise HTTPException(status_code=404, detail="报警不存在")

        video_path = alarm.get("video_path")
        if not video_path:
            raise HTTPException(status_code=404, detail="该报警无视频（录制未完成或未启用）")

        path = Path(video_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"视频文件已被清理或移动: {video_path}")

        return FileResponse(str(path), media_type="video/mp4")

    # ── 统计与视频流路由 ──────────────────────────────────────────────────

    @app.get("/api/statistics")
    def get_statistics():
        """返回报警统计汇总信息（各类报警次数、时段分布等）。"""
        return state.get_statistics()

    @app.get("/api/frame.jpg")
    def frame_jpg():
        """返回当前最新帧的 JPEG 二进制数据，适合需要单帧快照的客户端。

        每次请求返回调用时刻的最新帧，不保证与上次请求不同。
        """
        return Response(content=state.get_latest_frame(), media_type="image/jpeg")

    @app.get("/api/stream.mjpg")
    def mjpeg_stream():
        """推送 MJPEG 视频流。

        MJPEG 原理：在同一 HTTP 连接上持续发送 JPEG 帧，
        每帧以 multipart boundary 分隔，浏览器逐帧渲染形成视频效果，
        无需 WebSocket 或 WebRTC，兼容性好但效率较低。

        帧率控制：通过 state.last_update_ts 检测新帧到来，
        有新帧才推送（避免重复推送相同帧），每次推送后休眠 50ms（约 20fps 上限）。
        """
        def gen():
            """MJPEG 帧生成器：有新帧时推送，否则等待。"""
            boundary = b"--frame\r\n"
            last_update_ts = object()   # 初始化为不等于任何时间戳的哨兵值

            while True:
                update_ts = state.last_update_ts
                if update_ts == last_update_ts:
                    time.sleep(0.05)    # 无新帧，等待后重试
                    continue

                last_update_ts = update_ts
                frame = state.get_latest_frame()    # 取最新帧的 JPEG 二进制数据

                # 标准 MJPEG 帧格式：boundary + Content-Type + 图片数据 + 换行
                yield boundary
                yield b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                time.sleep(0.05)    # 控制推流帧率上限约 20fps

        # StreamingResponse 持续读取生成器输出并写入响应体
        return StreamingResponse(
            gen(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            # boundary=frame 告知浏览器以 "--frame" 为分隔符区分各帧
        )

    return app
