# auth.py
"""
认证与授权模块（轻量级自实现 JWT）。

设计决策：
  - 不依赖第三方 JWT 库，使用标准库 hmac + hashlib 手动实现 HS256 签名，
    减少供应链风险，同时便于审计完整签名流程。
  - Token 同时支持 Authorization: Bearer 请求头和 HttpOnly Cookie 两种携带方式，
    兼顾 API 客户端与浏览器两类场景。
  - 用户数据库为静态 JSON 文件（auth_users.json），适合小规模内网部署；
    如需对接 LDAP / 数据库，替换 load_auth_users() 即可，其余逻辑不变。

环境变量：
  AUTH_SECRET               Token 签名密钥（生产环境必须设置）
  AUTH_DEFAULT_PASSWORD     统一登录密码，默认 "Fuda@2026"
  AUTH_TOKEN_EXPIRE_HOURS   Token 有效期（小时），默认 12，最小 1
  AUTH_USERS_FILE           用户文件路径，默认 <repo_root>/config/auth_users.json
  AUTH_COOKIE_SECURE        强制 Cookie Secure 属性，默认根据请求协议自动判断
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

# Cookie 名称与算法常量集中定义，避免散落在代码各处形成魔法字符串
COOKIE_NAME = "aicv_auth_token"
JWT_ALGORITHM = "HS256"
DEV_AUTH_SECRET = "dev-aicv-auth-secret-change-me"  # 仅用于开发环境，生产必须覆盖

logger = logging.getLogger("guard_room.auth")


# ---------------------------------------------------------------------------
# Pydantic 请求模型
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    employee_id: str
    password: str


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class AuthError(Exception):
    """认证/授权失败的统一异常。

    内部函数抛出此异常；路由层负责将其转换为 HTTP 401/403 响应，
    从而将业务逻辑与 HTTP 层解耦。
    """


# ---------------------------------------------------------------------------
# Base64-URL 编解码辅助函数
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    """将字节序列编码为 URL-safe Base64（无填充符）。

    JWT 规范（RFC 7515）要求去除末尾 '=' 填充，以便直接拼入 URL 或 Header。
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    """将 URL-safe Base64 字符串（无或有填充符均可）解码为字节序列。

    补齐 '=' 填充后再解码，兼容 JWT 中去掉填充符的编码格式。
    """
    padding = "=" * (-len(data) % 4)   # 计算需要补齐的 '=' 数量（0~3 个）
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _json_b64(data: dict[str, Any]) -> str:
    """将字典序列化为紧凑 JSON 后进行 Base64-URL 编码，用于构造 JWT Header/Payload 段。

    使用 separators=(",", ":") 去除多余空格，确保签名输入的确定性。
    """
    return _b64url_encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


# ---------------------------------------------------------------------------
# 环境配置读取
# ---------------------------------------------------------------------------

def get_auth_secret() -> str:
    """读取 Token 签名密钥。

    优先从环境变量 AUTH_SECRET 读取；未设置时回落到开发默认值并记录警告。
    生产部署必须通过 AUTH_SECRET 注入强随机密钥（建议 32+ 字节）。
    """
    secret = os.getenv("AUTH_SECRET")
    if secret:
        return secret
    logger.warning("AUTH_SECRET is not set; using insecure development default secret.")
    return DEV_AUTH_SECRET


def get_default_password() -> str:
    """读取统一登录密码（环境变量 AUTH_DEFAULT_PASSWORD，默认 "Fuda@2026"）。

    当前实现所有用户共享同一密码；如需个人密码，替换 verify_login() 中的比对逻辑即可。
    """
    return os.getenv("AUTH_DEFAULT_PASSWORD", "Fuda@2026")


def get_token_expire_hours() -> int:
    """读取 Token 有效期（小时），来自环境变量 AUTH_TOKEN_EXPIRE_HOURS，默认 12。

    解析失败或小于 1 时回落到安全默认值并记录警告，避免配置错误导致 Token 永不过期。
    """
    raw = os.getenv("AUTH_TOKEN_EXPIRE_HOURS", "12")
    try:
        return max(1, int(raw))     # 强制最低 1 小时，防止配置 0 或负数
    except ValueError:
        logger.warning("Invalid AUTH_TOKEN_EXPIRE_HOURS=%r; using 12 hours.", raw)
        return 12


# ---------------------------------------------------------------------------
# 用户数据库（JSON 文件）
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """返回仓库根目录（本文件上两级），用于定位默认配置文件。"""
    return Path(__file__).resolve().parents[1]


def get_auth_users_path() -> Path:
    """返回用户数据库文件路径。

    优先读取环境变量 AUTH_USERS_FILE；未设置时使用默认路径
    ``<repo_root>/config/auth_users.json``。
    """
    raw = os.getenv("AUTH_USERS_FILE")
    if raw:
        return Path(raw)
    return _repo_root() / "config" / "auth_users.json"


def load_auth_users() -> list[dict[str, Any]]:
    """从 JSON 文件加载全量用户记录列表。

    文件格式示例：
        [{"employee_id": "001", "name": "张三", "role": "admin", "enabled": true}, ...]

    Raises:
        AuthError: 文件不存在或 JSON 格式非法时抛出，由调用方决定如何响应。
    """
    path = get_auth_users_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        logger.error("Auth users file not found: %s", path)
        raise AuthError("auth users file not found") from exc
    except json.JSONDecodeError as exc:
        logger.error("Auth users file is invalid JSON: %s", path)
        raise AuthError("auth users file is invalid") from exc


def find_enabled_user(employee_id: str) -> dict[str, Any] | None:
    """按工号查找已启用的用户，返回精简后的用户信息字典。

    对 employee_id 两端做 strip()，容错前端或文件中的多余空格。
    若用户不存在或 enabled=false，统一返回 None（不区分两种情况，防止枚举攻击）。

    Returns:
        包含 employee_id / name / role 的字典；用户不存在或已禁用时返回 None。
    """
    employee_id = str(employee_id).strip()
    for item in load_auth_users():
        if str(item.get("employee_id", "")).strip() != employee_id:
            continue
        if not item.get("enabled", False):
            return None     # 账号已禁用，不返回任何信息
        return {
            "employee_id": employee_id,
            "name": str(item.get("name", "")),
            "role": str(item.get("role", "viewer")),    # 未配置 role 时默认最低权限
            "department": item.get("department"),
        }
    return None


# ---------------------------------------------------------------------------
# JWT 签发与验证
# ---------------------------------------------------------------------------

def create_token(user: dict[str, Any]) -> str:
    """为已认证用户签发 HS256 JWT。

    Payload 标准字段：
        sub  —— 用户工号（Subject）
        name —— 显示名称
        role —— 角色（admin / viewer）
        iat  —— 签发时间（Unix 秒）
        exp  —— 过期时间（Unix 秒）

    Args:
        user: 由 find_enabled_user() 返回的用户信息字典。

    Returns:
        格式为 ``header.payload.signature`` 的 JWT 字符串。
    """
    now = int(time.time())
    payload = {
        "sub": user["employee_id"],
        "name": user.get("name", ""),
        "role": user.get("role", "viewer"),
        "department": user.get("department"),
        "iat": now,
        "exp": now + get_token_expire_hours() * 3600,
    }
    header = {"typ": "JWT", "alg": JWT_ALGORITHM}
    # signing_input = Base64URL(header) + "." + Base64URL(payload)，与 RFC 7515 一致
    signing_input = f"{_json_b64(header)}.{_json_b64(payload)}"
    signature = hmac.new(
        get_auth_secret().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_token(token: str) -> dict[str, Any]:
    """验证并解码 JWT，返回 Payload 字典。

    验证步骤（顺序不可颠倒）：
      1. 拆分三段结构，任何格式错误均抛出 AuthError；
      2. 重新计算签名并使用 compare_digest 常时比对，防止时序攻击；
      3. 校验 Header 中的算法字段，防止 alg=none 攻击；
      4. 检查 exp 字段，拒绝已过期 Token。

    Args:
        token: 原始 JWT 字符串。

    Returns:
        验证通过的 Payload 字典。

    Raises:
        AuthError: 签名无效、算法不匹配、格式非法或 Token 已过期。
    """
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)
        signing_input = f"{header_b64}.{payload_b64}"
        # 重新计算期望签名
        expected = hmac.new(
            get_auth_secret().encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual = _b64url_decode(signature_b64)
        # 常时比对：无论签名正确与否，比对时间恒定，避免泄漏签名信息
        if not hmac.compare_digest(expected, actual):
            raise AuthError("invalid token signature")
        header = json.loads(_b64url_decode(header_b64))
        # 明确拒绝非 HS256 算法，防止攻击者构造 alg=none 的伪造 Token
        if header.get("alg") != JWT_ALGORITHM:
            raise AuthError("unsupported token algorithm")
        payload = json.loads(_b64url_decode(payload_b64))
    except AuthError:
        raise                               # 已是语义明确的认证错误，直接上抛
    except Exception as exc:
        raise AuthError("invalid token") from exc   # 其余解析异常统一包装

    if int(payload.get("exp", 0)) < int(time.time()):
        raise AuthError("token expired")
    return payload


# ---------------------------------------------------------------------------
# Token 提取与用户鉴权
# ---------------------------------------------------------------------------

def token_from_request(request: Request) -> str | None:
    """从请求中提取 Token 字符串。

    提取优先级：Authorization: Bearer <token> 请求头 > HttpOnly Cookie。
    API 客户端通常使用 Header，浏览器通过 Cookie 自动携带。

    Returns:
        Token 字符串；未携带任何凭证时返回 None。
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()      # 截取 "Bearer " 前缀之后的内容
    return request.cookies.get(COOKIE_NAME)


def get_current_user_from_request(request: Request) -> dict[str, Any]:
    """从请求中解析并验证当前用户，返回用户信息字典。

    与 get_current_user() 的区别：抛出 AuthError 而非 HTTPException，
    适合在非路由层（如 WebSocket、后台任务）调用，由调用方决定错误处理方式。

    Raises:
        AuthError: 未携带 Token、Token 无效或用户已禁用。
    """
    token = token_from_request(request)
    if not token:
        raise AuthError("not authenticated")
    payload = decode_token(token)
    # 每次请求都从用户文件重新查询，确保禁用账号立即生效（无需等待 Token 过期）
    user = find_enabled_user(str(payload.get("sub", "")))
    if user is None:
        raise AuthError("user disabled or not allowed")
    return user


def get_current_user(request: Request) -> dict[str, Any]:
    """FastAPI 依赖项：获取当前已认证用户。

    认证失败时抛出 HTTP 401，由 FastAPI 统一处理为标准错误响应。
    在路由函数中通过 ``user: dict = Depends(get_current_user)`` 注入。
    """
    try:
        return get_current_user_from_request(request)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """FastAPI 依赖项：要求当前用户具有 admin 角色，否则返回 HTTP 403。

    使用示例：
        @router.delete("/users/{id}", dependencies=[Depends(require_admin)])
        async def delete_user(...): ...
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin permission required")
    return user


# ---------------------------------------------------------------------------
# 登录验证
# ---------------------------------------------------------------------------

def verify_login(employee_id: str, password: str) -> dict[str, Any] | None:
    """验证工号与密码，返回用户信息或 None。

    使用 hmac.compare_digest 进行密码比对，防止字符串比较的时序攻击。
    当前采用"全局统一密码"模型；如需个人密码，在此处替换比对逻辑。

    Returns:
        认证通过时返回用户信息字典；用户不存在或密码错误时返回 None
        （不区分两种失败原因，防止通过响应差异枚举有效工号）。
    """
    user = find_enabled_user(employee_id)
    if user is None:
        return None
    if not hmac.compare_digest(password, get_default_password()):
        return None
    return user


# ---------------------------------------------------------------------------
# Cookie 管理
# ---------------------------------------------------------------------------

def cookie_secure_for_request(request: Request) -> bool:
    """判断当前请求是否应设置 Cookie 的 Secure 属性。

    优先级：
      1. 环境变量 AUTH_COOKIE_SECURE 显式设置（"1"/"true"/"yes"/"on" → True）；
      2. 请求 scheme 或 X-Forwarded-Proto Header 为 HTTPS → True；
      3. 否则 False（HTTP 开发环境）。

    反向代理场景下依赖 X-Forwarded-Proto，需确保代理正确设置该 Header，
    防止攻击者伪造该 Header 绕过 Secure 检查。
    """
    raw = os.getenv("AUTH_COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or "https" in {p.strip() for p in forwarded_proto.split(",")}


def set_auth_cookie(response: Response, token: str, request: Request) -> None:
    """将 JWT 写入 HttpOnly Cookie，完成浏览器端的登录态持久化。

    Cookie 属性说明：
        httponly=True   —— 禁止 JavaScript 读取，防御 XSS 窃取 Token；
        secure=...      —— HTTPS 环境下禁止明文传输；
        samesite="lax"  —— 允许顶级导航携带，阻止跨站 POST 请求（CSRF 防护）；
        max_age=...     —— 与 Token exp 对齐，浏览器到期自动清除。
    """
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=cookie_secure_for_request(request),
        samesite="lax",
        path="/",
        max_age=get_token_expire_hours() * 3600,
    )


def clear_auth_cookie(response: Response, request: Request) -> None:
    """删除认证 Cookie，用于登出操作。

    delete_cookie 需传入与 set_cookie 相同的 path / secure / samesite，
    否则浏览器可能将其视为不同的 Cookie 而无法删除。
    """
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=cookie_secure_for_request(request),
        samesite="lax",
    )
