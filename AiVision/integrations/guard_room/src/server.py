# 文件说明：实现服务端相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# server.py
"""
FastAPI Web 服务模块。

将系统的核心功能（检测控制、状态查询、报警管理、视频流）
以 RESTful API 的形式暴露给前端，同时处理认证与跨域。

API 分组：
    /api/auth/*        —— 登录、登出、当前用户信息
    /api/sites/*       —— 事业部内站点的摄像头、配置、运行状态和报警

认证机制：
    HTTP 中间件拦截所有 /api/* 请求（公开路径除外），
    通过 auth.py 的 get_current_user_from_request() 验证 Token。
    公开路径：/ 、/api/health、/api/auth/login、/api/auth/logout。

CORS：
    允许的源由环境变量 AUTH_CORS_ORIGINS 控制（逗号分隔），
    默认包含本地开发地址和生产域名。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

from AiVision.departments.department_registry import DEPARTMENT_SPECS, require_department
from AiVision.core.video_encoding import VideoEncodingError, ensure_browser_compatible_mp4

from auth.auth import (
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
from .runtime_manager import GuardRoomRuntimeManager
from .service import GuardRoomService


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

# 功能：配置更新请求体；输入与输出详见下方说明
# 参数：
#   - `video`（Optional[dict]）：`video` 对应的业务输入值
#   - `models`（Optional[dict]）：`models` 对应的业务输入值
#   - `room`（Optional[dict]）：`room` 对应的业务输入值
#   - `rules`（Optional[dict]）：`rules` 对应的业务输入值
#   - `classes`（Optional[dict]）：`classes` 对应的业务输入值
#   - `runtime`（Optional[dict]）：`runtime` 对应的业务输入值
#   - `wechat`（Optional[dict]）：`wechat` 对应的业务输入值
# 返回：ConfigUpdateRequest；返回新建的 `ConfigUpdateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：新增保安室/监控区域请求体；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `department`（Optional[str]）：业务部门名称或标识
#   - `enabled`（bool）：是否启用相应能力
#   - `description`（Optional[str]）：`description` 对应的业务输入值
#   - `sort_order`（Optional[int]）：`sort_order` 对应的业务输入值
# 返回：SiteCreateRequest；返回新建的 `SiteCreateRequest` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_site_api.py` 的 `test_site_api_routes_create_site_and_camera`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的 `test_site_api_routes_scope_sites_by_department`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的 `test_site_api_routes_update_and_delete_camera` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class SiteCreateRequest(BaseModel):
    """新增保安室/监控区域请求体。"""

    name: str
    department: str
    enabled: bool = True
    description: Optional[str] = None
    sort_order: Optional[int] = None


# 功能：更新保安室/监控区域请求体；输入与输出详见下方说明
# 参数：
#   - `name`（Optional[str]）：业务对象名称
#   - `enabled`（Optional[bool]）：是否启用相应能力
#   - `description`（Optional[str]）：`description` 对应的业务输入值
#   - `sort_order`（Optional[int]）：`sort_order` 对应的业务输入值
# 返回：SiteUpdateRequest；返回新建的 `SiteUpdateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class SiteUpdateRequest(BaseModel):
    """更新保安室/监控区域请求体。"""

    name: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


# 功能：新增保安室摄像头请求体；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `rtsp_url`（str）：`rtsp_url` 对应的业务输入值
#   - `enabled`（bool）：是否启用相应能力
#   - `sort_order`（Optional[int]）：`sort_order` 对应的业务输入值
# 返回：CameraCreateRequest；返回新建的 `CameraCreateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraCreateRequest(BaseModel):
    """新增保安室摄像头请求体。"""

    name: str
    rtsp_url: str
    enabled: bool = True
    sort_order: Optional[int] = None


# 功能：更新保安室摄像头请求体；输入与输出详见下方说明
# 参数：
#   - `name`（Optional[str]）：业务对象名称
#   - `rtsp_url`（Optional[str]）：`rtsp_url` 对应的业务输入值
#   - `enabled`（Optional[bool]）：是否启用相应能力
#   - `sort_order`（Optional[int]）：`sort_order` 对应的业务输入值
# 返回：CameraUpdateRequest；返回新建的 `CameraUpdateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraUpdateRequest(BaseModel):
    """更新保安室摄像头请求体。"""

    name: Optional[str] = None
    rtsp_url: Optional[str] = None
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def _department_scope(requested_department: str | None, user: object) -> str:
    requested = None
    if requested_department is not None:
        try:
            requested = require_department(requested_department)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not isinstance(user, dict):
        raise HTTPException(status_code=403, detail="事业部权限不足")
    role = user.get("role")
    candidates = user.get("departments") or []
    if role == "admin":
        return requested or ""
    departments = [d for d in candidates if isinstance(d, str) and d in DEPARTMENT_SPECS]
    if role != "viewer" or not departments or (requested and requested not in departments):
        raise HTTPException(status_code=403, detail="无权访问该部门保安室")
    return requested or departments[0]


# 功能：实现 `_require_site_visible` 对应的服务端逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `site_service`（GuardRoomService）：`site_service` 对应的业务输入值
#   - `site_id`（int）：保安室站点唯一标识
#   - `department`（str）：业务部门名称或标识
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/server.py` 的 `create_app::get_site`
#         调用本符号；`AiVision/integrations/guard_room/src/server.py` 的 `create_app::get_site_config`
#         调用本符号；`AiVision/integrations/guard_room/src/server.py` 的 `create_app::get_site_status`
#         调用本符号；`AiVision/integrations/guard_room/src/server.py` 的 `create_app::site_frame_jpg` 调用本符号；另有 7 处静态调用
#   - 内部调用：`site_service.get_site`、`site.get`、`HTTPException`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _require_site_visible(site_service: GuardRoomService, site_id: int, department: str) -> None:
    if not department:
        return
    site = site_service.get_site(site_id, include_config=False)
    if site is None or site.get("department") != department:
        raise HTTPException(status_code=404, detail="保安室不存在")

# 功能：从环境变量 AUTH_CORS_ORIGINS 读取允许的 CORS 源列表；输入与输出详见下方说明
# 参数：无。
# 返回：list[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`os.getenv`、`item.strip`、`raw.split`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：创建并配置 FastAPI 应用实例；输入与输出详见下方说明
# 参数：
#   - `config_path`（str）：`config_path` 对应的业务输入值；默认值为 `'config/config.yaml'`
#   - `guard_room_service`（GuardRoomService | None）：`guard_room_service` 对应的业务输入值；默认值为 `None`
#   - `runtime_manager`（GuardRoomRuntimeManager | None）：`runtime_manager` 对应的业务输入值；默认值为 `None`
# 返回：FastAPI；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者；由解释器、ASGI 服务器、React 或框架生命周期直接触发
#   - 内部调用：`Path(__file__).resolve`、`Path`、`resolve_runtime_paths`、`AppConfig.from_yaml`、`AppState`、`WeChatNotifier`、`GuardRoomRuntime`、`GuardRoomService`、`site_service.ensure_schema`、`GuardRoomRuntimeManager`
#          等共 13 个调用。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
def create_app(
    config_path: str = "config/config.yaml",
    *,
    guard_room_service: GuardRoomService | None = None,
    runtime_manager: GuardRoomRuntimeManager | None = None,
) -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    采用工厂函数模式（而非模块级全局对象），便于在测试中注入不同配置。
    所有业务路由通过站点服务和运行时管理器访问明确归属的站点。

    Args:
        config_path: YAML 配置文件路径，默认 "config/config.yaml"。

    Returns:
        配置完毕、已注册所有路由的 FastAPI 实例。
    """
    # ── 初始化核心对象 ────────────────────────────────────────────────────
    project_root = Path(__file__).resolve().parents[1]
    site_service = guard_room_service or GuardRoomService(
        default_config_path=config_path,
        project_root=project_root,
    )
    site_service.ensure_schema()
    site_runtime_manager = runtime_manager or GuardRoomRuntimeManager(site_service)
    runtime_autostart_ready = False

    # 功能：配置变化后刷新已启用站点；失败不回滚已经提交的配置；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/server.py` 的 `create_app::create_site_camera`
    #         调用本符号；`AiVision/integrations/guard_room/src/server.py` 的 `create_app::update_site_camera`
    #         调用本符号；`AiVision/integrations/guard_room/src/server.py` 的 `create_app::delete_site_camera` 调用本符号
    #   - 内部调用：`site_service.get_site`、`site.get`、`getattr`、`callable`、`remove_runtime`、`site_runtime_manager.restart`、`logger.exception`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def restart_enabled_site(site_id: int) -> None:
        """配置变化后刷新已启用站点；失败不回滚已经提交的配置。"""
        if not runtime_autostart_ready:
            return
        site = site_service.get_site(site_id, include_config=False)
        if site is None or not site.get("enabled"):
            return
        if not site.get("enabled_camera_count"):
            remove_runtime = getattr(site_runtime_manager, "remove", None)
            if callable(remove_runtime):
                remove_runtime(site_id)
            return
        try:
            site_runtime_manager.restart(site_id)
        except Exception:
            logger.exception("刷新保安室运行时失败 site_id=%s", site_id)

    # 功能：实现 `lifespan` 对应的服务端逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `_app`（FastAPI）：`_app` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者；由解释器、ASGI 服务器、React 或框架生命周期直接触发
    #   - 内部调用：`site_service.list_sites`、`site.get`、`logger.info`、`site_runtime_manager.start`、`int`、`logger.exception`、`site_runtime_manager.stop_all`。
    # 副作用/注意事项：会修改全局或闭包状态；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        nonlocal runtime_autostart_ready
        for site in site_service.list_sites(include_cameras=False):
            if not site.get("enabled"):
                continue
            if not site.get("enabled_camera_count"):
                logger.info("保安室暂无启用摄像头，暂不启动 site_id=%s", site["id"])
                continue
            try:
                site_runtime_manager.start(int(site["id"]))
            except Exception:
                logger.exception("保安室默认启动失败 site_id=%s", site["id"])
        runtime_autostart_ready = True
        try:
            yield
        finally:
            runtime_autostart_ready = False
            try:
                site_runtime_manager.stop_all()
            except Exception:
                logger.exception("停止全部保安室运行时失败")

    # ── 创建 FastAPI 实例并注册中间件 ──────────────────────────────────────
    app = FastAPI(title="Guard Room API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,     # 允许携带 Cookie，JWT 认证必须
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 功能：HTTP 认证中间件：拦截所有 /api/* 请求，验证 Token；输入与输出详见下方说明
    # 参数：
    #   - `request`（Request）：当前 HTTP 请求及上下文
    #   - `call_next`（未显式标注）：`call_next` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`call_next`、`path.startswith`、`get_current_user_from_request`、`JSONResponse`、`str`、`app.middleware`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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

    # 功能：验证工号与密码，成功后签发 JWT 并写入 HttpOnly Cookie；输入与输出详见下方说明
    # 参数：
    #   - `payload`（LoginRequest）：接口或事件携带的业务数据
    #   - `request`（Request）：当前 HTTP 请求及上下文
    #   - `response`（Response）：待读取或更新的 HTTP 响应
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/auth/login')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`verify_login`、`HTTPException`、`create_token`、`set_auth_cookie`、`app.post`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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

    # 功能：返回当前已登录用户的信息，常用于前端刷新页面后恢复登录状态；输入与输出详见下方说明
    # 参数：
    #   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/auth/me')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/api/auth/me")
    def me(user: dict = Depends(get_current_user)):
        """返回当前已登录用户的信息，常用于前端刷新页面后恢复登录状态。"""
        return {"success": True, "user": user}

    # 功能：清除认证 Cookie，完成登出。Token 本身无法主动失效（无服务端存储），；输入与输出详见下方说明
    # 参数：
    #   - `request`（Request）：当前 HTTP 请求及上下文
    #   - `response`（Response）：待读取或更新的 HTTP 响应
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/auth/logout')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`clear_auth_cookie`、`app.post`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        """清除认证 Cookie，完成登出。Token 本身无法主动失效（无服务端存储），
        依赖 Cookie 删除使浏览器不再携带凭证。"""
        clear_auth_cookie(response, request)
        return {"success": True}

    # 功能：修改当前登录用户自己的密码；输入与输出详见下方说明
    # 参数：
    #   - `payload`（ChangePasswordRequest）：接口或事件携带的业务数据
    #   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/auth/password')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`change_own_password`、`user.get`、`HTTPException`、`str`、`app.post`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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

    # 功能：根路径：返回服务基本信息，供反向代理健康探测或人工确认服务身份；输入与输出详见下方说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/")
    def root():
        """根路径：返回服务基本信息，供反向代理健康探测或人工确认服务身份。"""
        return {
            "name": "guard-room-api",
            "ok": True,
            "frontend": "https://aicv.fudar.com",
            "health": "/api/health",
        }

    # 功能：健康检查端点，无需认证；输入与输出详见下方说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/health')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`bool`、`int`、`os.getenv`、`JSONResponse`、`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/api/health")
    def health():
        """健康检查端点，无需认证。

        反映真实就绪状态供冷启动脚本与负载均衡器判定：
            ready  = 服务进程正常运行（runtime 启动/停止是管理员按需操作，不影响就绪判定）
            有 error 时返回 503
        """
        return {"status": "ok", "ready": True, "port": int(os.getenv("API_PORT", "7862"))}

    # ── 保安室/摄像头路由 ────────────────────────────────────────────────

    # 功能：返回保安行为规范检测下的保安室/监控区域列表；输入与输出详见下方说明
    # 参数：
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`site_service.list_sites`、`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/api/sites")
    def list_sites(department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回保安行为规范检测下的保安室/监控区域列表。"""
        scope = _department_scope(department, _user)
        return {"items": site_service.list_sites(include_cameras=True, department=scope or None)}

    # 功能：新增保安室/监控区域（需 admin）；输入与输出详见下方说明
    # 参数：
    #   - `payload`（SiteCreateRequest）：接口或事件携带的业务数据
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/sites')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`site_service.create_site`、`HTTPException`、`str`、`app.post`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.post("/api/sites")
    def create_site(payload: SiteCreateRequest, _user: dict = Depends(require_admin)):
        """新增保安室/监控区域（需 admin）。

        新增保安室只需要名称，默认配置从当前 guard_room 配置模板复制；
        RTSP 地址在该保安室下继续通过摄像头接口添加。
        """
        try:
            return site_service.create_site(
                payload.name,
                department=require_department(payload.department),
                enabled=payload.enabled,
                description=payload.description,
                sort_order=payload.sort_order,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 功能：返回单个保安室详情，包含该保安室下的摄像头列表和配置；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`site_service.get_site`、`HTTPException`、`app.get`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}")
    def get_site(site_id: int, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回单个保安室详情，包含该保安室下的摄像头列表和配置。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        site = site_service.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="保安室不存在")
        return site

    # 功能：更新保安室基础信息（需 admin）；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `payload`（SiteUpdateRequest）：接口或事件携带的业务数据
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.put('/api/sites/{site_id}')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`payload.model_dump`、`site_service.update_site`、`HTTPException`、`str`、`site.get`、`site_runtime_manager.start`、`site_runtime_manager.stop`、`app.put`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
    @app.put("/api/sites/{site_id}")
    def update_site(site_id: int, payload: SiteUpdateRequest, _user: dict = Depends(require_admin)):
        """更新保安室基础信息（需 admin）。"""
        values = payload.model_dump(exclude_unset=True)
        try:
            site = site_service.update_site(site_id, values)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if site is None:
            raise HTTPException(status_code=404, detail="保安室不存在")
        if "enabled" in values:
            try:
                if values["enabled"]:
                    if site.get("enabled_camera_count"):
                        site_runtime_manager.start(site_id)
                else:
                    site_runtime_manager.stop(site_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return site

    # 功能：删除保安室及其摄像头/配置（需 admin）；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.delete('/api/sites/{site_id}')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`getattr`、`callable`、`remove_runtime`、`site_service.delete_site`、`HTTPException`、`app.delete`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.delete("/api/sites/{site_id}")
    def delete_site(site_id: int, _user: dict = Depends(require_admin)):
        """删除保安室及其摄像头/配置（需 admin）。"""
        remove_runtime = getattr(site_runtime_manager, "remove", None)
        if callable(remove_runtime):
            remove_runtime(site_id)
        if not site_service.delete_site(site_id):
            raise HTTPException(status_code=404, detail="保安室不存在")
        return {"success": True}

    # 功能：返回保安室独立配置；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}/config')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`site_service.get_site_config`、`HTTPException`、`app.get`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}/config")
    def get_site_config(site_id: int, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回保安室独立配置。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        cfg_payload = site_service.get_site_config(site_id)
        if cfg_payload is None:
            raise HTTPException(status_code=404, detail="保安室配置不存在")
        return cfg_payload

    # 功能：局部更新保安室独立配置（需 admin）；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `payload`（ConfigUpdateRequest）：接口或事件携带的业务数据
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/sites/{site_id}/config')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`payload.model_dump`、`site_service.update_site_config`、`HTTPException`、`app.post`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.post("/api/sites/{site_id}/config")
    def update_site_config(site_id: int, payload: ConfigUpdateRequest, _user: dict = Depends(require_admin)):
        """局部更新保安室独立配置（需 admin）。"""
        patch = payload.model_dump(exclude_unset=True)
        cfg_payload = site_service.update_site_config(site_id, patch)
        if cfg_payload is None:
            raise HTTPException(status_code=404, detail="保安室不存在")
        return {"success": True, "config": cfg_payload}

    # 功能：返回指定保安室的独立运行状态；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}/status')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`site_runtime_manager.get_status`、`HTTPException`、`str`、`app.get`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}/status")
    def get_site_status(site_id: int, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回指定保安室的独立运行状态。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        try:
            return site_runtime_manager.get_status(site_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # 功能：启动指定保安室的检测运行时（需 admin）；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/sites/{site_id}/control/start')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`site_runtime_manager.start`、`HTTPException`、`str`、`app.post`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
    @app.post("/api/sites/{site_id}/control/start")
    def start_site_runtime(site_id: int, _user: dict = Depends(require_admin)):
        """启动指定保安室的检测运行时（需 admin）。"""
        try:
            return site_runtime_manager.start(site_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 功能：停止指定保安室的检测运行时（需 admin）；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/sites/{site_id}/control/stop')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`site_runtime_manager.stop`、`HTTPException`、`str`、`app.post`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.post("/api/sites/{site_id}/control/stop")
    def stop_site_runtime(site_id: int, _user: dict = Depends(require_admin)):
        """停止指定保安室的检测运行时（需 admin）。"""
        try:
            return site_runtime_manager.stop(site_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # 功能：重启指定保安室的检测运行时（需 admin）；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/sites/{site_id}/control/restart')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`site_runtime_manager.restart`、`HTTPException`、`str`、`app.post`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.post("/api/sites/{site_id}/control/restart")
    def restart_site_runtime(site_id: int, _user: dict = Depends(require_admin)):
        """重启指定保安室的检测运行时（需 admin）。"""
        try:
            return site_runtime_manager.restart(site_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 功能：返回指定保安室拼接后的最新 JPEG 帧；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}/frame.jpg')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`Response`、`site_runtime_manager.get_latest_frame`、`HTTPException`、`str`、`app.get`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}/frame.jpg")
    def site_frame_jpg(site_id: int, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回指定保安室拼接后的最新 JPEG 帧。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        try:
            return Response(content=site_runtime_manager.get_latest_frame(site_id), media_type="image/jpeg")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # 功能：返回指定保安室下单路摄像头的最新 JPEG 帧，用于按摄像头绘制 ROI；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `camera_id`（str）：摄像头唯一标识
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}/cameras/{camera_id}/frame.jpg')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`Response`、`site_runtime_manager.get_camera_frame`、`HTTPException`、`str`、`app.get`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}/cameras/{camera_id}/frame.jpg")
    def site_camera_frame_jpg(site_id: int, camera_id: str, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回指定保安室下单路摄像头的最新 JPEG 帧，用于按摄像头绘制 ROI。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        try:
            return Response(
                content=site_runtime_manager.get_camera_frame(site_id, camera_id),
                media_type="image/jpeg",
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # 功能：返回指定保安室的 MJPEG 拼接视频流；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}/stream.mjpg')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`site_runtime_manager.get_state`、`HTTPException`、`str`、`StreamingResponse`、`gen`、`app.get`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}/stream.mjpg")
    def site_mjpeg_stream(site_id: int, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回指定保安室的 MJPEG 拼接视频流。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        try:
            state_for_site = site_runtime_manager.get_state(site_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        # 功能：实现 `gen` 对应的服务端逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`object`、`time.sleep`、`state_for_site.get_latest_frame`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def gen():
            boundary = b"--frame\r\n"
            last_update_ts = object()

            while True:
                update_ts = state_for_site.last_update_ts
                if update_ts == last_update_ts:
                    time.sleep(0.05)
                    continue

                last_update_ts = update_ts
                frame = state_for_site.get_latest_frame()
                yield boundary
                yield b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                time.sleep(0.05)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    # 功能：返回指定保安室最近报警；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `limit`（int）：返回或处理的最大记录数；默认值为 `50`
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}/alarms')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`site_runtime_manager.get_alarms`、`HTTPException`、`str`、`app.get`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}/alarms")
    def get_site_alarms(site_id: int, limit: int = 50, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回指定保安室最近报警。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        try:
            return {"items": site_runtime_manager.get_alarms(site_id, limit=limit)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # 功能：返回指定保安室报警快照；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `alarm_id`（str）：`alarm_id` 对应业务对象的唯一标识
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}/alarms/{alarm_id}/image')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`site_runtime_manager.get_alarm`、`HTTPException`、`str`、`alarm.get`、`Path`、`path.exists`、`FileResponse`
    #          等共 11 个调用。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}/alarms/{alarm_id}/image")
    def get_site_alarm_image(site_id: int, alarm_id: str, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回指定保安室报警快照。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        try:
            alarm = site_runtime_manager.get_alarm(site_id, alarm_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not alarm:
            raise HTTPException(status_code=404, detail="报警不存在")
        image_path = alarm.get("image_path")
        if not image_path:
            raise HTTPException(status_code=404, detail="该报警无截图")
        path = Path(image_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"截图文件已被清理或移动: {image_path}")
        return FileResponse(str(path), media_type="image/jpeg")

    # 功能：返回指定保安室报警视频；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `alarm_id`（str）：`alarm_id` 对应业务对象的唯一标识
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}/alarms/{alarm_id}/video')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`site_runtime_manager.get_alarm`、`HTTPException`、`str`、`alarm.get`、`Path`、`path.exists`、`ensure_browser_compatible_mp4`
    #          等共 13 个调用。
    # 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}/alarms/{alarm_id}/video")
    def get_site_alarm_video(site_id: int, alarm_id: str, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回指定保安室报警视频。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        try:
            alarm = site_runtime_manager.get_alarm(site_id, alarm_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not alarm:
            raise HTTPException(status_code=404, detail="报警不存在")
        video_path = alarm.get("video_path")
        if not video_path:
            raise HTTPException(status_code=404, detail="该报警无视频（录制未完成或未启用）")
        path = Path(video_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"视频文件已被清理或移动: {video_path}")
        try:
            compatible_path = ensure_browser_compatible_mp4(path)
        except VideoEncodingError as exc:
            logger.warning("报警视频浏览器兼容转换失败 site_id=%s alarm_id=%s: %s", site_id, alarm_id, exc)
            raise HTTPException(status_code=500, detail="报警视频暂时无法播放") from exc
        return FileResponse(str(compatible_path), media_type="video/mp4")

    # 功能：返回指定保安室报警统计；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}/statistics')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`site_runtime_manager.get_statistics`、`HTTPException`、`str`、`app.get`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}/statistics")
    def get_site_statistics(site_id: int, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回指定保安室报警统计。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        try:
            return site_runtime_manager.get_statistics(site_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # 功能：返回指定保安室下的摄像头列表；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/sites/{site_id}/cameras')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_department_scope`、`_require_site_visible`、`site_service.get_site`、`HTTPException`、`site_service.list_cameras`、`app.get`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.get("/api/sites/{site_id}/cameras")
    def list_site_cameras(site_id: int, department: Optional[str] = None, _user: dict = Depends(get_current_user)):
        """返回指定保安室下的摄像头列表。"""
        scope = _department_scope(department, _user)
        _require_site_visible(site_service, site_id, scope)
        if site_service.get_site(site_id, include_config=False) is None:
            raise HTTPException(status_code=404, detail="保安室不存在")
        return {"items": site_service.list_cameras(site_id)}

    # 功能：在指定保安室下新增摄像头（需 admin），每个保安室最多 9 路；输入与输出详见下方说明
    # 参数：
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `payload`（CameraCreateRequest）：接口或事件携带的业务数据
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/sites/{site_id}/cameras')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`site_service.create_camera`、`restart_enabled_site`、`str`、`HTTPException`、`app.post`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.post("/api/sites/{site_id}/cameras")
    def create_site_camera(site_id: int, payload: CameraCreateRequest, _user: dict = Depends(require_admin)):
        """在指定保安室下新增摄像头（需 admin），每个保安室最多 9 路。"""
        try:
            camera = site_service.create_camera(
                site_id,
                name=payload.name,
                rtsp_url=payload.rtsp_url,
                enabled=payload.enabled,
                sort_order=payload.sort_order,
            )
            restart_enabled_site(site_id)
            return camera
        except ValueError as exc:
            message = str(exc)
            status_code = 404 if "保安室不存在" in message else 400
            raise HTTPException(status_code=status_code, detail=message) from exc

    # 功能：更新保安室摄像头（需 admin）；输入与输出详见下方说明
    # 参数：
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `payload`（CameraUpdateRequest）：接口或事件携带的业务数据
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.put('/api/cameras/{camera_id}')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`site_service.update_camera`、`payload.model_dump`、`HTTPException`、`str`、`restart_enabled_site`、`int`、`app.put`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.put("/api/cameras/{camera_id}")
    def update_site_camera(camera_id: int, payload: CameraUpdateRequest, _user: dict = Depends(require_admin)):
        """更新保安室摄像头（需 admin）。"""
        try:
            camera = site_service.update_camera(camera_id, payload.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if camera is None:
            raise HTTPException(status_code=404, detail="摄像头不存在")
        restart_enabled_site(int(camera["site_id"]))
        return camera

    # 功能：删除保安室摄像头（需 admin）；输入与输出详见下方说明
    # 参数：
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.delete('/api/cameras/{camera_id}')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`site_service.get_camera`、`HTTPException`、`site_service.delete_camera`、`restart_enabled_site`、`int`、`app.delete`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.delete("/api/cameras/{camera_id}")
    def delete_site_camera(camera_id: int, _user: dict = Depends(require_admin)):
        """删除保安室摄像头（需 admin）。"""
        camera = site_service.get_camera(camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="摄像头不存在")
        if not site_service.delete_camera(camera_id):
            raise HTTPException(status_code=404, detail="摄像头不存在")
        restart_enabled_site(int(camera["site_id"]))
        return {"success": True}

    return app
