# server.py
"""
使用FastAPI搭建网页接口服务器。接受前端请求，调用runtime和state
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
    LoginRequest,
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


class ConfigUpdateRequest(BaseModel):
    video: Optional[dict] = None
    models: Optional[dict] = None
    room: Optional[dict] = None
    rules: Optional[dict] = None
    classes: Optional[dict] = None
    runtime: Optional[dict] = None
    wechat: Optional[dict] = None


def _cors_origins() -> list[str]:
    raw = os.getenv(
        "AUTH_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,https://aicv.fudar.com",
    )
    return [item.strip() for item in raw.split(",") if item.strip()]


def create_app(config_path: str = "config/config.yaml") -> FastAPI:
    """
    根据配置文件，创建并返回一个FastAPI对象
    """
    # ======================准备对象=============================================

    cfg = AppConfig.from_yaml(config_path)
    state = AppState(cfg, config_path=config_path)   # 创建应用状态对象（全局共享对应仓库）
    wechat_notifier = None

    # 创建企业微信通知器对象
    if cfg.wechat.enable:
        wechat_notifier = WeChatNotifier(
            corpid=cfg.wechat.corpid,
            corpsecret=cfg.wechat.corpsecret,
            agentid=cfg.wechat.agentid,
        )         

    # 创建后端总运行对象，负责开始和停止检测,读取视频，跑模型，更新状态，发出告警，录制视频
    runtime = GuardRoomRuntime(
        config=cfg,
        state=state,                        #共享状态对象
        wechat_notifier=wechat_notifier,    # 微信通知器
        alarm_user=cfg.wechat.alarm_user,   # 报警发送的用户
        alarm_camera_name=cfg.wechat.camera_name,   # 报警发送的摄像头名称
    )
    
    # 创建FastAPI对象
    app = FastAPI(title="Guard Room API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
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

    # ===============================注册接口=================================
    # 当前端访问这个网址时，就执行下面的各个函数，get:读取数据不改东西，post:执行动作或修改数据

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, request: Request, response: Response):
        user = verify_login(payload.employee_id, payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid employee_id or password")
        token = create_token(user)
        set_auth_cookie(response, token, request)
        return {"success": True, "user": user}

    @app.get("/api/auth/me")
    def me(user: dict = Depends(get_current_user)):
        return {"success": True, "user": user}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        clear_auth_cookie(response, request)
        return {"success": True}

    @app.get("/api/recording/status")
    def recording_status():
        """
        查看当前录制器状态
        """
        return runtime.recorder.status()

    @app.post("/api/recording/start")
    def start_recording(_user: dict = Depends(require_admin)):
        """
        启动录制
        """
        return runtime.recorder.start()

    @app.post("/api/recording/stop")
    def stop_recording(_user: dict = Depends(require_admin)):
        return runtime.recorder.stop()

    @app.get("/")
    def root():
        """
        获取根目录信息
        """
        return {
            "name": "guard-room-api",
            "ok": True,
            "frontend": "https://aicv.fudar.com",
            "health": "/api/health",
        }

    @app.get("/api/health")
    def health():
        """
        健康检查，服务器还活着
        前端想检查后端是否在线时，会调用这个接口
        """
        return {"status": "ok", "port": 5000}

    @app.get("/api/status")
    def status():
        """
        获取当前状态
        """
        return state.get_status()

    @app.get("/api/config")
    def get_config():
        """
        获取当前配置
        """
        return state.get_config_dict()

    @app.post("/api/config")
    def update_config(payload: ConfigUpdateRequest, _user: dict = Depends(require_admin)):
        """
        更新配置
        参数：
            payload：前端发来的请求体
        """
        current = state.get_config_dict()

        for section_name in ["video", "models", "room", "rules", "classes", "runtime","wechat"]:
            incoming = getattr(payload, section_name)   # 按名字取请求体的值，当 section_name 是 "video" 时，就等于取 payload.video
            # 如果前端传了section_name这一部分的配置，就更新当前配置的对应部分
            if incoming:  
                current[section_name].update(incoming)

        # 写到yaml文件中
        import yaml
        with open(config_path, "w", encoding="utf-8") as f:
            # 把 Python 字典写成 yaml 格式。
            yaml.safe_dump(current, f, allow_unicode=True, sort_keys=False) #sort_keys：是否按字母排序

        # 读取新配置，更新 state 里的配置
        new_cfg = AppConfig.from_yaml(config_path)
        state.set_config(new_cfg, config_path=config_path)         # 注意：state.set_config(...)内部如果没有联动机制（运行中的 runtime 是否立刻使用新配置），可能需要重启才能使配置生效 
        runtime.cfg = new_cfg
        
        return {"success": True, "config": state.get_config_dict()}

    @app.post("/api/control/start")
    def start_runtime(_user: dict = Depends(require_admin)):
        """
        启动整个检测系统
        """
        runtime.start()
        return {"success": True, "running": True}

    @app.post("/api/control/stop")
    def stop_runtime(_user: dict = Depends(require_admin)):
        """
        停止整个系统的检测
        """
        runtime.stop()
        return {"success": True, "running": False}

    @app.post("/api/control/restart")
    def restart_runtime(_user: dict = Depends(require_admin)):
        """
        重启
        """
        runtime.stop()
        runtime.start()
        return {"success": True, "running": True}

    @app.get("/api/alarms")
    def get_alarms(limit: int = 50):
        """
        获取告警列表
        """
        return {"items": state.get_alarms(limit=limit)}
    @app.get("/api/alarms/{alarm_id}/image")
    def get_alarm_image(alarm_id: str):
        """返回报警截图"""
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
        """返回报警视频"""
        alarm = state.get_alarm(alarm_id)
        if not alarm:
            raise HTTPException(status_code=404, detail="报警不存在")
        
        video_path = alarm.get("video_path")
        if not video_path:
            raise HTTPException(status_code=404, detail="该报警无视频")
        
        path = Path(video_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"视频文件已被清理或移动: {video_path}")
        
        return FileResponse(str(path), media_type="video/mp4")

    @app.get("/api/statistics")
    def get_statistics():
        """
        获取统计信息
        """
        return state.get_statistics()

    @app.get("/api/frame.jpg")
    def frame_jpg():
        """
        获取最新帧
        """
        return Response(content=state.get_latest_frame(), media_type="image/jpeg")

    @app.get("/api/stream.mjpg")
    def mjpeg_stream():
        """
        获取 MJPEG 视频流,就是把很多张jpg图片一张接一张的不断发给浏览器看，看起来就像视频
        """
        def gen():
            """
            生成器函数
            """
            boundary = b"--frame\r\n"
            last_update_ts = object()
            while True:
                update_ts = state.last_update_ts
                if update_ts == last_update_ts:
                    time.sleep(0.05)
                    continue

                last_update_ts = update_ts
                frame = state.get_latest_frame()  # 从状态对象里取最新帧的jpg二进制数据
                yield boundary
                # 标准的 MJPEG 帧格式：内容类型是jpeg，后面跟着图片二进制数据，末尾换行
                yield b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                time.sleep(0.05)

        # 将生成器函数给StreamingResponse类，streamingResponse会不断读取gen()产出的数据，持续发送到前端
        return StreamingResponse(
            gen(),
            media_type="multipart/x-mixed-replace; boundary=frame", # 这是多段连续内容，每一段都是一帧，用 boundary=frame 来分隔。
        )

    return app
