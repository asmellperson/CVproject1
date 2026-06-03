"""后端服务共享的认证与授权模块。

这里集中维护 Guard Room 和 AiVision 共用的 JWT、Cookie、用户文件、
登录校验和角色检查逻辑。各服务自己的 auth.py 只作为兼容入口，从这里重新导出。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

COOKIE_NAME = "aicv_auth_token"
JWT_ALGORITHM = "HS256"
DEV_AUTH_SECRET = "dev-aicv-auth-secret-change-me"
PERSISTENT_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365 * 20

logger = logging.getLogger("auth.auth")
_warned_default_auth_secret = False


class LoginRequest(BaseModel):
    employee_id: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AuthError(Exception):
    """认证或授权失败。"""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _json_b64(data: dict[str, Any]) -> str:
    return _b64url_encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def get_auth_secret() -> str:
    """读取 JWT 签名密钥，未配置时回退到开发默认值。"""
    global _warned_default_auth_secret
    secret = os.getenv("AUTH_SECRET")
    if secret:
        return secret
    if not _warned_default_auth_secret:
        logger.warning("AUTH_SECRET is not set; using insecure development default secret.")
        _warned_default_auth_secret = True
    return DEV_AUTH_SECRET


def get_default_password() -> str:
    """读取共享登录密码。"""
    return os.getenv("AUTH_DEFAULT_PASSWORD", "Fuda@2026")


def get_token_expire_hours() -> int | None:
    """读取 Token 有效期小时数。

    空值、0、never、permanent 或 forever 表示 Token 不主动过期。
    账号禁用后仍会被拒绝，因为每次请求都会重新读取用户记录。
    """
    raw = os.getenv("AUTH_TOKEN_EXPIRE_HOURS", "").strip()
    if not raw or raw.lower() in {"0", "never", "permanent", "forever"}:
        return None
    try:
        hours = int(raw)
    except ValueError:
        logger.warning("Invalid AUTH_TOKEN_EXPIRE_HOURS=%r; using persistent login.", raw)
        return None
    if hours < 1:
        return None
    return hours


def get_auth_cookie_max_age_seconds() -> int:
    expire_hours = get_token_expire_hours()
    if expire_hours is None:
        return PERSISTENT_COOKIE_MAX_AGE_SECONDS
    return expire_hours * 3600


def get_auth_users_path() -> Path:
    """返回共享用户文件路径。

    AUTH_USERS_FILE 优先级最高。默认读取根目录 auth/auth_users.json。
    """
    raw = os.getenv("AUTH_USERS_FILE")
    if raw:
        return Path(raw)
    return _repo_root() / "auth" / "auth_users.json"


def _write_auth_users(users: list[dict[str, Any]]) -> None:
    path = get_auth_users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_auth_users() -> list[dict[str, Any]]:
    path = get_auth_users_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        logger.error("Auth users file not found: %s", path)
        raise AuthError("auth users file not found") from exc
    except json.JSONDecodeError as exc:
        logger.error("Auth users file is invalid JSON: %s", path)
        raise AuthError("auth users file is invalid") from exc
    if not isinstance(data, list):
        logger.error("Auth users file must contain a JSON array: %s", path)
        raise AuthError("auth users file is invalid")
    return data


def _public_user(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "employee_id": str(item.get("employee_id", "")).strip(),
        "name": str(item.get("name", "")),
        "role": str(item.get("role", "viewer")),
        "department": item.get("department"),
    }


def _find_enabled_user_record(identifier: str) -> dict[str, Any] | None:
    identifier = str(identifier).strip()
    if not identifier:
        return None
    for item in load_auth_users():
        employee_id = str(item.get("employee_id", "")).strip()
        name = str(item.get("name", "")).strip()
        if identifier != employee_id and identifier != name:
            continue
        if not item.get("enabled", False):
            return None
        return item
    return None


def find_enabled_user(identifier: str) -> dict[str, Any] | None:
    item = _find_enabled_user_record(identifier)
    if item is None:
        return None
    return _public_user(item)


def _password_hash(password: str, salt: str | None = None, iterations: int = 260_000) -> str:
    salt = salt or secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${_b64url_encode(digest)}"


def _verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return hmac.compare_digest(password, get_default_password())
    try:
        algorithm, iterations_raw, salt, digest = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = _password_hash(password, salt=salt, iterations=int(iterations_raw)).rsplit("$", 1)[-1]
    except Exception:
        return False
    return hmac.compare_digest(expected, digest)


def change_own_password(employee_id: str, current_password: str, new_password: str) -> dict[str, Any]:
    employee_id = str(employee_id).strip()
    if len(new_password) < 6:
        raise AuthError("新密码至少需要 6 位")
    users = load_auth_users()
    for item in users:
        if str(item.get("employee_id", "")).strip() != employee_id:
            continue
        if not item.get("enabled", False):
            raise AuthError("user disabled or not allowed")
        if not _verify_password(current_password, item.get("password_hash")):
            raise AuthError("当前密码不正确")
        item["password_hash"] = _password_hash(new_password)
        _write_auth_users(users)
        return _public_user(item)
    raise AuthError("user disabled or not allowed")


def create_token(user: dict[str, Any]) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user["employee_id"],
        "name": user.get("name", ""),
        "role": user.get("role", "viewer"),
        "department": user.get("department"),
        "iat": now,
    }
    expire_hours = get_token_expire_hours()
    if expire_hours is not None:
        payload["exp"] = now + expire_hours * 3600

    header = {"typ": "JWT", "alg": JWT_ALGORITHM}
    signing_input = f"{_json_b64(header)}.{_json_b64(payload)}"
    signature = hmac.new(
        get_auth_secret().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_token(token: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(
            get_auth_secret().encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected, actual):
            raise AuthError("invalid token signature")
        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != JWT_ALGORITHM:
            raise AuthError("unsupported token algorithm")
        payload = json.loads(_b64url_decode(payload_b64))
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError("invalid token") from exc

    exp = payload.get("exp")
    if exp is not None:
        try:
            if int(exp) < int(time.time()):
                raise AuthError("token expired")
        except (TypeError, ValueError) as exc:
            raise AuthError("invalid token") from exc
    return payload


def token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def get_current_user_from_request(request: Request) -> dict[str, Any]:
    token = token_from_request(request)
    if not token:
        raise AuthError("not authenticated")
    payload = decode_token(token)
    user = find_enabled_user(str(payload.get("sub", "")))
    if user is None:
        raise AuthError("user disabled or not allowed")
    return user


def get_current_user(request: Request) -> dict[str, Any]:
    try:
        return get_current_user_from_request(request)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin permission required")
    return user


def verify_login(employee_id: str, password: str) -> dict[str, Any] | None:
    user_record = _find_enabled_user_record(employee_id)
    if user_record is None:
        return None
    if not _verify_password(password, user_record.get("password_hash")):
        return None
    return _public_user(user_record)


def cookie_secure_for_request(request: Request) -> bool:
    raw = os.getenv("AUTH_COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or "https" in {p.strip() for p in forwarded_proto.split(",")}


def set_auth_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=cookie_secure_for_request(request),
        samesite="lax",
        path="/",
        max_age=get_auth_cookie_max_age_seconds(),
    )


def clear_auth_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=cookie_secure_for_request(request),
        samesite="lax",
    )


__all__ = [
    "AuthError",
    "ChangePasswordRequest",
    "COOKIE_NAME",
    "DEV_AUTH_SECRET",
    "JWT_ALGORITHM",
    "LoginRequest",
    "change_own_password",
    "clear_auth_cookie",
    "cookie_secure_for_request",
    "create_token",
    "decode_token",
    "find_enabled_user",
    "get_auth_cookie_max_age_seconds",
    "get_auth_secret",
    "get_auth_users_path",
    "get_current_user",
    "get_current_user_from_request",
    "get_default_password",
    "get_token_expire_hours",
    "load_auth_users",
    "require_admin",
    "set_auth_cookie",
    "token_from_request",
    "verify_login",
]
