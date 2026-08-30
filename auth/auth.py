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
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from auth.user_store import (
    UserConflictError,
    UserNotFoundError,
    UserStore,
    UserStoreError,
    UserValidationError,
    default_database_path,
)

COOKIE_NAME = "aicv_auth_token"
JWT_ALGORITHM = "HS256"
DEV_AUTH_SECRET = "dev-aicv-auth-secret-change-me"
PERSISTENT_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365 * 20

logger = logging.getLogger("auth.auth")
_warned_default_auth_secret = False
_user_store_lock = threading.Lock()
_user_store_signature: tuple[Path, Path] | None = None
_user_store: UserStore | None = None


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
    """返回只用于首次迁移的旧共享用户文件路径。

    AUTH_USERS_FILE 优先级最高。迁移完成后不再读取该文件。
    """
    raw = os.getenv("AUTH_USERS_FILE")
    if raw:
        return Path(raw)
    return _repo_root() / "auth" / "auth_users.json"


def get_auth_users_database_path() -> Path:
    return default_database_path()


def get_user_store() -> UserStore:
    global _user_store
    global _user_store_signature
    signature = (
        get_auth_users_database_path(),
        get_auth_users_path(),
    )
    if _user_store is not None and _user_store_signature == signature:
        return _user_store
    with _user_store_lock:
        if _user_store is None or _user_store_signature != signature:
            _user_store = UserStore(
                database_path=signature[0],
                legacy_json_path=signature[1],
            )
            _user_store_signature = signature
        return _user_store


def load_auth_users() -> list[dict[str, Any]]:
    try:
        return get_user_store().list_users()
    except UserStoreError as exc:
        logger.error("Auth user database unavailable: %s", exc)
        raise AuthError(str(exc)) from exc


def _public_user(item: dict[str, Any]) -> dict[str, Any]:
    department = item.get("department")
    departments = item.get("departments")
    if not isinstance(departments, list) or not departments:
        departments = [department] if department else []
    return {
        "employee_id": str(item.get("employee_id", "")).strip(),
        "name": str(item.get("name", "")),
        "role": str(item.get("role", "viewer")),
        "department": department,
        "departments": departments,
        "auth_version": int(item.get("auth_version", 1) or 1),
    }


def _find_enabled_user_record(identifier: str) -> dict[str, Any] | None:
    identifier = str(identifier).strip()
    if not identifier:
        return None
    try:
        return get_user_store().find_enabled_user(identifier)
    except UserStoreError as exc:
        logger.error("Auth user database unavailable: %s", exc)
        raise AuthError(str(exc)) from exc


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
    try:
        item = get_user_store().get_user_record(employee_id)
        if not item.get("enabled", False):
            raise AuthError("user disabled or not allowed")
        if not _verify_password(current_password, item.get("password_hash")):
            raise AuthError("当前密码不正确")
        updated = get_user_store().update_password_hash(
            employee_id,
            _password_hash(new_password),
        )
        return _public_user(updated)
    except UserNotFoundError as exc:
        raise AuthError("user disabled or not allowed") from exc
    except UserStoreError as exc:
        raise AuthError(str(exc)) from exc


def create_token(user: dict[str, Any]) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user["employee_id"],
        "name": user.get("name", ""),
        "role": user.get("role", "viewer"),
        "department": user.get("department"),
        "departments": user.get("departments"),
        "auth_version": int(user.get("auth_version", 1) or 1),
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
    try:
        token_auth_version = int(payload.get("auth_version", 1) or 1)
    except (TypeError, ValueError) as exc:
        raise AuthError("invalid token") from exc
    if token_auth_version != int(user.get("auth_version", 1) or 1):
        raise AuthError("登录状态已失效，请重新登录")
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


def list_auth_users() -> list[dict[str, Any]]:
    return get_user_store().list_users()


def create_auth_user(
    *,
    employee_id: str,
    name: str,
    role: str,
    department: str | None,
    password: str,
    departments: list[str] | None = None,
) -> dict[str, Any]:
    if len(password) < 6:
        raise UserValidationError("初始密码至少需要 6 位")
    return get_user_store().create_user(
        employee_id=employee_id,
        name=name,
        role=role,
        department=department,
        password_hash=_password_hash(password),
        departments=departments,
    )


def update_auth_user(
    employee_id: str,
    *,
    actor_employee_id: str,
    name: str,
    role: str,
    department: str | None,
    enabled: bool,
    departments: list[str] | None = None,
) -> dict[str, Any]:
    return get_user_store().update_user(
        employee_id,
        actor_employee_id=actor_employee_id,
        name=name,
        role=role,
        department=department,
        enabled=enabled,
        departments=departments,
    )


def reset_auth_user_password(
    employee_id: str,
    *,
    new_password: str,
) -> dict[str, Any]:
    if len(new_password) < 6:
        raise UserValidationError("新密码至少需要 6 位")
    return get_user_store().update_password_hash(
        employee_id,
        _password_hash(new_password),
    )


def delete_auth_user(
    employee_id: str,
    *,
    actor_employee_id: str,
) -> None:
    get_user_store().delete_user(
        employee_id,
        actor_employee_id=actor_employee_id,
    )


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
    "create_auth_user",
    "create_token",
    "decode_token",
    "delete_auth_user",
    "find_enabled_user",
    "get_auth_cookie_max_age_seconds",
    "get_auth_secret",
    "get_auth_users_database_path",
    "get_auth_users_path",
    "get_current_user",
    "get_current_user_from_request",
    "get_default_password",
    "get_token_expire_hours",
    "get_user_store",
    "load_auth_users",
    "list_auth_users",
    "require_admin",
    "reset_auth_user_password",
    "set_auth_cookie",
    "token_from_request",
    "update_auth_user",
    "verify_login",
    "UserConflictError",
    "UserNotFoundError",
    "UserStoreError",
    "UserValidationError",
]
