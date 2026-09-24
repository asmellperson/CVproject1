"""账号认证、JWT、Cookie 和权限校验。"""

from __future__ import annotations


import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status


from auth.user_store import (
    UserConflictError,
    UserNotFoundError,
    UserStore,
    UserStoreError,
    UserValidationError,
    hash_password,
)

COOKIE_NAME = "aicv_auth_token"
JWT_ALGORITHM = "HS256"

PERSISTENT_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365 * 20

_user_store = UserStore()


class AuthError(Exception):
    """认证或授权失败。"""


def _b64url_encode(data: bytes) -> str:
    """把bytes编码成适合放进URL/JWT的Base64字符串(编码不是加密)"""

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    """解码：
    JWT字符串->补回=->交bytes->Base64URL解码，得到原始的bytes
    """
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _json_b64(data: dict[str, Any]) -> str:
    """把一个Python字典转换成JWT可以使用的Base64URL字符串"""

    return _b64url_encode(
        json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def get_auth_secret() -> str:
    secret = os.getenv("AUTH_SECRET")
    if not secret or len(secret) < 32:
        raise RuntimeError("必须配置至少 32 个字符的 AUTH_SECRET")
    return secret


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
    except ValueError as exc:
        raise ValueError(
            "AUTH_TOKEN_EXPIRE_HOURS 必须是正整数，或 0/never/permanent/forever"
            f"，当前值为 {raw!r}"
        ) from exc
    if hours < 0:
        raise ValueError(f"AUTH_TOKEN_EXPIRE_HOURS 不能为负数，当前值为 {raw!r}")
    if hours == 0:
        return None
    return hours


def get_auth_cookie_max_age_seconds() -> int:
    """觉得浏览器Cookie最长保存多久，与JWT过期时间保存一致"""
    expire_hours = get_token_expire_hours()
    if expire_hours is None:
        return PERSISTENT_COOKIE_MAX_AGE_SECONDS
    return expire_hours * 3600


def get_user_store() -> UserStore:
    return _user_store


def _public_user(item: dict[str, Any]) -> dict[str, Any]:
    from AiVision.departments.service import department_service

    user = {
        key: item[key]
        for key in ("employee_id", "name", "role", "departments", "auth_version")
    }
    assignments = department_service.feature_access()
    user["feature_access"] = {
        department: features for department, features in assignments.items()
        if user["role"] == "admin" or department in user["departments"]
    }
    return user


def _verify_password(password: str, stored_hash: str | None) -> bool:
    """
    判断用户输入的密码是不是正确
    思路：
        输入密码
        用相同salt和算法重新hash
        比较结果
    """
    if not isinstance(stored_hash, str) or not stored_hash:
        return False
    try:
        algorithm, iterations_raw, salt, digest = stored_hash.split("$", 3)

        if algorithm != "pbkdf2_sha256":
            return False

        expected = hash_password(
            password,
            salt=salt,
            iterations=int(iterations_raw),
        ).rsplit("$", 1)[-1]
    except (TypeError, ValueError, OverflowError):
        return False

    return hmac.compare_digest(expected, digest)


def change_own_password(
    employee_id: str, current_password: str, new_password: str
) -> dict[str, Any]:
    """
    用户自己修改代码
    流程：
        用户输入旧密码+新密码
        找到用户
        确认账号enabled
        验证旧密码
        校验新密码长度
        生成新的password_hash
        写数据库
        返回最新用户信息
    """
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
            hash_password(new_password),
        )

        return _public_user(updated)
    except UserNotFoundError as exc:
        raise AuthError("user disabled or not allowed") from exc
    except UserStoreError as exc:
        raise AuthError(str(exc)) from exc


def create_token(user: dict[str, Any]) -> str:
    """登录成功以后，根据当前用户生成一张JWT身份认证"""
    now = int(time.time())

    payload: dict[str, Any] = {
        "sub": user["employee_id"],
        "name": user["name"],
        "role": user["role"],
        "departments": user["departments"],
        "auth_version": user["auth_version"],
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
    """检查一个JWT是不是服务器自己签发的、有没有被修改、有没有过期、然后返回Payload"""
    secret = get_auth_secret()
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)

        signing_input = f"{header_b64}.{payload_b64}"

        expected = hmac.new(
            secret.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()

        actual = _b64url_decode(signature_b64)

        if not hmac.compare_digest(expected, actual):
            raise AuthError("invalid token signature")

        header = json.loads(_b64url_decode(header_b64))

        if not isinstance(header, dict) or header.get("alg") != JWT_ALGORITHM:
            raise AuthError("unsupported token algorithm")

        payload = json.loads(_b64url_decode(payload_b64))
    except AuthError:
        raise
    except (ValueError, TypeError, UnicodeError) as exc:
        raise AuthError("invalid token") from exc

    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("sub"), str)
        or not payload["sub"].strip()
        or type(payload.get("auth_version")) is not int
        or payload["auth_version"] < 1
    ):
        raise AuthError("invalid token claims")
    exp = payload.get("exp")
    if exp is not None:
        try:
            if int(exp) < int(time.time()):
                raise AuthError("token expired")
        except (TypeError, ValueError) as exc:
            raise AuthError("invalid token") from exc
    return payload


def token_from_request(request: Request) -> str | None:
    """从当前HTTP请求中找到JWT"""

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    return request.cookies.get(COOKIE_NAME)


def get_current_user_from_request(request: Request) -> dict[str, Any]:
    token = token_from_request(request)
    if not token:
        raise AuthError("not authenticated")
    payload = decode_token(token)
    try:
        record = get_user_store().get_user_record(payload["sub"])
    except UserNotFoundError as exc:
        raise AuthError("user disabled or not allowed") from exc
    if not record["enabled"]:
        raise AuthError("user disabled or not allowed")
    if payload["auth_version"] != record["auth_version"]:
        raise AuthError("登录状态已失效，请重新登录")
    return _public_user(record)


def get_current_user(request: Request) -> dict[str, Any]:
    if hasattr(request.state, "user"):
        return request.state.user
    try:
        return get_current_user_from_request(request)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """依赖get_current_user完成认证"""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin permission required"
        )
    return user


def verify_login(employee_id: str, password: str) -> dict[str, Any] | None:
    """登录时根据工号和密码判断这个用户能不能登录"""

    user_record = get_user_store().find_enabled_user(employee_id)
    if user_record is None:
        return None

    if not _verify_password(password, user_record.get("password_hash")):
        return None

    return _public_user(user_record)


def list_auth_users() -> list[dict[str, Any]]:
    """管理员查询所有认证用户"""
    return get_user_store().list_users()


def create_auth_user(
    *,
    employee_id: str,
    name: str,
    role: str,
    password: str,
    departments: list[str] | None,
) -> dict[str, Any]:
    """管理员创建新的用户"""
    if len(password) < 6:
        raise UserValidationError("初始密码至少需要 6 位")
    return get_user_store().create_user(
        employee_id=employee_id,
        name=name,
        role=role,
        password_hash=hash_password(password),
        departments=departments,
    )


def update_auth_user(
    employee_id: str,
    *,
    actor_employee_id: str,
    name: str,
    role: str,
    enabled: bool,
    departments: list[str] | None,
) -> dict[str, Any]:
    """管理员修改某个用户的基本信息、角色、部门和启用状态"""
    return get_user_store().update_user(
        employee_id,
        actor_employee_id=actor_employee_id,
        name=name,
        role=role,
        enabled=enabled,
        departments=departments,
    )


def reset_auth_user_password(
    employee_id: str,
    *,
    new_password: str,
) -> dict[str, Any]:
    """管理员重置某个用户密码，与change_own_password用户自己改密码不同，管理员重置不需要旧密码"""
    if len(new_password) < 6:
        raise UserValidationError("新密码至少需要 6 位")
    return get_user_store().update_password_hash(
        employee_id,
        hash_password(new_password),
    )


def delete_auth_user(
    employee_id: str,
    *,
    actor_employee_id: str,
) -> None:
    """管理员删除用户"""

    get_user_store().delete_user(
        employee_id,
        actor_employee_id=actor_employee_id,
    )


def cookie_secure_for_request(request: Request) -> bool:
    """判读Cookie要不要设置Secure属性（Secure Cookie：浏览器只允许通过HTTPS发送这个Cookie）"""
    raw = os.getenv("AUTH_COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or "https" in {
        p.strip() for p in forwarded_proto.split(",")
    }


def set_auth_cookie(response: Response, token: str, request: Request) -> None:
    """登录成功以后，把JWT写入浏览器Cookie"""
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
    """删除浏览器里的认证Cookie"""

    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=cookie_secure_for_request(request),
        samesite="lax",
    )


__all__ = [
    "AuthError",
    "COOKIE_NAME",
    "JWT_ALGORITHM",
    "change_own_password",
    "clear_auth_cookie",
    "cookie_secure_for_request",
    "create_auth_user",
    "create_token",
    "decode_token",
    "delete_auth_user",
    "get_auth_cookie_max_age_seconds",
    "get_auth_secret",
    "get_current_user",
    "get_current_user_from_request",
    "get_token_expire_hours",
    "get_user_store",
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
