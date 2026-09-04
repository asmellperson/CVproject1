# 文件说明：实现认证授权相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""后端服务共享的认证与授权模块。

这里集中维护 Guard Room 和 AiVision 共用的 JWT、Cookie、用户数据库、
登录校验和角色检查逻辑。各服务自己的 auth.py 只作为兼容入口，从这里重新导出。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
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
    hash_password,
)

COOKIE_NAME = "aicv_auth_token"
JWT_ALGORITHM = "HS256"
DEV_AUTH_SECRET = "dev-aicv-auth-secret-change-me"
PERSISTENT_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365 * 20

logger = logging.getLogger("auth.auth")
_warned_default_auth_secret = False
_user_store_lock = threading.Lock()
_user_store_signature: Path | None = None
_user_store: UserStore | None = None


# 功能：定义 `LoginRequest` 类，封装认证授权相关的状态、约束与操作
# 参数：
#   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
#   - `password`（str）：`password` 对应的业务输入值
# 返回：LoginRequest；返回新建的 `LoginRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LoginRequest(BaseModel):
    employee_id: str
    password: str


# 功能：定义 `ChangePasswordRequest` 类，封装认证授权相关的状态、约束与操作
# 参数：
#   - `current_password`（str）：`current_password` 对应的业务输入值
#   - `new_password`（str）：`new_password` 对应的业务输入值
# 返回：ChangePasswordRequest；返回新建的 `ChangePasswordRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# 功能：认证或授权失败；输入与输出详见下方说明
# 参数：无。
# 返回：AuthError；返回新建的 `AuthError` 实例。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `load_auth_users` 实例化本符号；`auth/auth.py` 的 `_find_enabled_user_record` 实例化本符号；`auth/auth.py` 的
#         `change_own_password` 实例化本符号；`auth/auth.py` 的 `decode_token` 实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AuthError(Exception):
    """认证或授权失败。"""


# 功能：实现 `_b64url_encode` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `data`（bytes）：待处理的数据
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `_json_b64` 调用本符号；`auth/auth.py` 的 `create_token` 调用本符号
#   - 内部调用：`base64.urlsafe_b64encode(data).rstrip(b'=').decode`、`base64.urlsafe_b64encode(data).rstrip`、`base64.urlsafe_b64encode`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# 功能：实现 `_b64url_decode` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `data`（str）：待处理的数据
# 返回：bytes；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `decode_token` 调用本符号
#   - 内部调用：`len`、`base64.urlsafe_b64decode`、`(data + padding).encode`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


# 功能：实现 `_json_b64` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `data`（dict[str, Any]）：待处理的数据
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `create_token` 调用本符号
#   - 内部调用：`_b64url_encode`、`json.dumps(data, separators=(',', ':'), ensure_ascii=False).encode`、`json.dumps`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _json_b64(data: dict[str, Any]) -> str:
    return _b64url_encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


# 功能：读取 JWT 签名密钥，未配置时回退到开发默认值；输入与输出详见下方说明
# 参数：无。
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `create_token` 调用本符号；`auth/auth.py` 的 `decode_token` 调用本符号
#   - 内部调用：`os.getenv`、`logger.warning`。
# 副作用/注意事项：会修改全局或闭包状态；会向日志系统输出运行或异常信息。
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


# 功能：读取 Token 有效期小时数；输入与输出详见下方说明
# 参数：无。
# 返回：int | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `get_auth_cookie_max_age_seconds` 调用本符号；`auth/auth.py` 的 `create_token` 调用本符号
#   - 内部调用：`os.getenv('AUTH_TOKEN_EXPIRE_HOURS', '').strip`、`os.getenv`、`raw.lower`、`int`。
# 副作用/注意事项：配置非法时抛出明确异常。
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
        raise ValueError(
            "AUTH_TOKEN_EXPIRE_HOURS 不能为负数"
            f"，当前值为 {raw!r}"
        )
    if hours == 0:
        return None
    return hours


# 功能：读取或查询 `get_auth_cookie_max_age_seconds` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `set_auth_cookie` 调用本符号
#   - 内部调用：`get_token_expire_hours`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_auth_cookie_max_age_seconds() -> int:
    expire_hours = get_token_expire_hours()
    if expire_hours is None:
        return PERSISTENT_COOKIE_MAX_AGE_SECONDS
    return expire_hours * 3600


# 功能：读取或查询 `get_auth_users_database_path` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `get_user_store` 调用本符号
#   - 内部调用：`default_database_path`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_auth_users_database_path() -> Path:
    return default_database_path()


# 功能：读取或查询 `get_user_store` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：UserStore；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `load_auth_users` 调用本符号；`auth/auth.py` 的 `_find_enabled_user_record` 调用本符号；`auth/auth.py` 的
#         `change_own_password` 调用本符号；`auth/auth.py` 的 `list_auth_users` 调用本符号；另有 5 处静态调用
#   - 内部调用：`get_auth_users_database_path`、`get_auth_users_path`、`UserStore`。
# 副作用/注意事项：会修改全局或闭包状态。
def get_user_store() -> UserStore:
    global _user_store
    global _user_store_signature
    signature = get_auth_users_database_path()
    if _user_store is not None and _user_store_signature == signature:
        return _user_store
    with _user_store_lock:
        if _user_store is None or _user_store_signature != signature:
            _user_store = UserStore(database_path=signature)
            _user_store_signature = signature
        return _user_store


# 功能：读取或查询 `load_auth_users` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`get_user_store().list_users`、`get_user_store`、`logger.error`、`AuthError`、`str`。
# 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
def load_auth_users() -> list[dict[str, Any]]:
    try:
        return get_user_store().list_users()
    except UserStoreError as exc:
        logger.error("Auth user database unavailable: %s", exc)
        raise AuthError(str(exc)) from exc


# 功能：实现 `_public_user` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `item`（dict[str, Any]）：`item` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`item.get`、`isinstance`、`str(item.get('employee_id', '')).strip`、`str`、`int`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _public_user(item: dict[str, Any]) -> dict[str, Any]:
    departments = item.get("departments")
    if not isinstance(departments, list):
        departments = []
    return {
        "employee_id": str(item.get("employee_id", "")).strip(),
        "name": str(item.get("name", "")),
        "role": str(item.get("role", "viewer")),
        "departments": departments,
        "auth_version": int(item.get("auth_version", 1) or 1),
    }


# 功能：读取或查询 `_find_enabled_user_record` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `identifier`（str）：`identifier` 对应的业务输入值
# 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `find_enabled_user` 调用本符号；`auth/auth.py` 的 `verify_login` 调用本符号
#   - 内部调用：`str(identifier).strip`、`str`、`get_user_store().find_enabled_user`、`get_user_store`、`logger.error`、`AuthError`。
# 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
def _find_enabled_user_record(identifier: str) -> dict[str, Any] | None:
    identifier = str(identifier).strip()
    if not identifier:
        return None
    try:
        return get_user_store().find_enabled_user(identifier)
    except UserStoreError as exc:
        logger.error("Auth user database unavailable: %s", exc)
        raise AuthError(str(exc)) from exc


# 功能：读取或查询 `find_enabled_user` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `identifier`（str）：`identifier` 对应的业务输入值
# 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_find_enabled_user_record`、`_public_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def find_enabled_user(identifier: str) -> dict[str, Any] | None:
    item = _find_enabled_user_record(identifier)
    if item is None:
        return None
    return _public_user(item)


# 功能：实现 `_verify_password` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `password`（str）：`password` 对应的业务输入值
#   - `stored_hash`（str | None）：`stored_hash` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `change_own_password` 调用本符号；`auth/auth.py` 的 `verify_login` 调用本符号
#   - 内部调用：`hmac.compare_digest`、`stored_hash.split`、`hash_password`、`int`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _verify_password(password: str, stored_hash: str | None) -> bool:
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


# 功能：实现 `change_own_password` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
#   - `current_password`（str）：`current_password` 对应的业务输入值
#   - `new_password`（str）：`new_password` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_auth_database.py` 的 `test_migrated_default_password_user_login_and_token_version`
#         调用本符号；`unified_backend/app.py` 的 `create_app::change_password` 调用本符号
#   - 内部调用：`str(employee_id).strip`、`str`、`len`、`AuthError`、`get_user_store().get_user_record`、`get_user_store`、`item.get`、`_verify_password`、`get_user_store().update_password_hash`、`hash_password`
#          等共 11 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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
            hash_password(new_password),
        )
        return _public_user(updated)
    except UserNotFoundError as exc:
        raise AuthError("user disabled or not allowed") from exc
    except UserStoreError as exc:
        raise AuthError(str(exc)) from exc


# 功能：创建或构建 `create_token` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_auth_database.py` 的 `test_migrated_default_password_user_login_and_token_version`
#         调用本符号；`unified_backend/tests/test_auth_database.py` 的 `test_version_one_token_without_auth_version_remains_compatible`
#         调用本符号；`unified_backend/app.py` 的 `create_app::login` 调用本符号
#   - 内部调用：`int`、`time.time`、`user.get`、`get_token_expire_hours`、`_json_b64`、`hmac.new(get_auth_secret().encode('utf-8'),
#          signing_input.encode('ascii'),
#          hashlib.sha256).digest`、`hmac.new`、`get_auth_secret().encode`、`get_auth_secret`、`signing_input.encode` 等共 11 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def create_token(user: dict[str, Any]) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user["employee_id"],
        "name": user.get("name", ""),
        "role": user.get("role", "viewer"),
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


# 功能：实现 `decode_token` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `token`（str）：用于认证或续接请求的令牌
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `get_current_user_from_request` 调用本符号
#   - 内部调用：`token.split`、`hmac.new(get_auth_secret().encode('utf-8'), signing_input.encode('ascii'),
#          hashlib.sha256).digest`、`hmac.new`、`get_auth_secret().encode`、`get_auth_secret`、`signing_input.encode`、`_b64url_decode`、`hmac.compare_digest`、`AuthError`、`json.loads`
#          等共 14 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：实现 `token_from_request` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `request`（Request）：当前 HTTP 请求及上下文
# 返回：str | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `get_current_user_from_request` 调用本符号
#   - 内部调用：`request.headers.get`、`auth_header.lower().startswith`、`auth_header.lower`、`auth_header[7:].strip`、`request.cookies.get`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.cookies.get(COOKIE_NAME)


# 功能：读取或查询 `get_current_user_from_request` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `request`（Request）：当前 HTTP 请求及上下文
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `get_current_user` 调用本符号；`unified_backend/tests/test_auth_database.py` 的
#         `test_migrated_default_password_user_login_and_token_version` 调用本符号；`unified_backend/tests/test_auth_database.py` 的
#         `test_version_one_token_without_auth_version_remains_compatible` 调用本符号；`unified_backend/app.py` 的
#         `create_app::auth_middleware` 调用本符号；另有 1 处静态调用
#   - 内部调用：`token_from_request`、`AuthError`、`decode_token`、`find_enabled_user`、`str`、`payload.get`、`int`、`user.get`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：读取或查询 `get_current_user` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `request`（Request）：当前 HTTP 请求及上下文
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`get_current_user_from_request`、`HTTPException`、`str`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def get_current_user(request: Request) -> dict[str, Any]:
    try:
        return get_current_user_from_request(request)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


# 功能：实现 `require_admin` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_admin_users_api.py` 的 `test_viewer_is_rejected_by_admin_dependency` 调用本符号
#   - 内部调用：`Depends`、`user.get`、`HTTPException`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin permission required")
    return user


# 功能：实现 `verify_login` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
#   - `password`（str）：`password` 对应的业务输入值
# 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_auth_database.py` 的 `test_migrated_default_password_user_login_and_token_version`
#         调用本符号；`unified_backend/tests/test_auth_database.py` 的 `test_version_one_token_without_auth_version_remains_compatible`
#         调用本符号；`unified_backend/app.py` 的 `create_app::login` 调用本符号
#   - 内部调用：`_find_enabled_user_record`、`_verify_password`、`user_record.get`、`_public_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def verify_login(employee_id: str, password: str) -> dict[str, Any] | None:
    user_record = _find_enabled_user_record(employee_id)
    if user_record is None:
        return None
    if not _verify_password(password, user_record.get("password_hash")):
        return None
    return _public_user(user_record)


# 功能：读取或查询 `list_auth_users` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::admin_list_users` 调用本符号
#   - 内部调用：`get_user_store().list_users`、`get_user_store`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def list_auth_users() -> list[dict[str, Any]]:
    return get_user_store().list_users()


# 功能：创建或构建 `create_auth_user` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
#   - `name`（str）：业务对象名称
#   - `role`（str）：`role` 对应的业务输入值
#   - `password`（str）：`password` 对应的业务输入值
#   - `departments`（list[str] | None）：用户的事业部列表
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::admin_create_user` 调用本符号
#   - 内部调用：`len`、`UserValidationError`、`get_user_store().create_user`、`get_user_store`、`hash_password`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def create_auth_user(
    *,
    employee_id: str,
    name: str,
    role: str,
    password: str,
    departments: list[str] | None,
) -> dict[str, Any]:
    if len(password) < 6:
        raise UserValidationError("初始密码至少需要 6 位")
    return get_user_store().create_user(
        employee_id=employee_id,
        name=name,
        role=role,
        password_hash=hash_password(password),
        departments=departments,
    )


# 功能：更新或保存 `update_auth_user` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
#   - `actor_employee_id`（str）：`actor_employee_id` 对应业务对象的唯一标识
#   - `name`（str）：业务对象名称
#   - `role`（str）：`role` 对应的业务输入值
#   - `enabled`（bool）：是否启用相应能力
#   - `departments`（list[str] | None）：用户的事业部列表
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::admin_update_user` 调用本符号
#   - 内部调用：`get_user_store().update_user`、`get_user_store`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def update_auth_user(
    employee_id: str,
    *,
    actor_employee_id: str,
    name: str,
    role: str,
    enabled: bool,
    departments: list[str] | None,
) -> dict[str, Any]:
    return get_user_store().update_user(
        employee_id,
        actor_employee_id=actor_employee_id,
        name=name,
        role=role,
        enabled=enabled,
        departments=departments,
    )


# 功能：实现 `reset_auth_user_password` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
#   - `new_password`（str）：`new_password` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::admin_reset_user_password` 调用本符号
#   - 内部调用：`len`、`UserValidationError`、`get_user_store().update_password_hash`、`get_user_store`、`hash_password`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def reset_auth_user_password(
    employee_id: str,
    *,
    new_password: str,
) -> dict[str, Any]:
    if len(new_password) < 6:
        raise UserValidationError("新密码至少需要 6 位")
    return get_user_store().update_password_hash(
        employee_id,
        hash_password(new_password),
    )


# 功能：删除或清理 `delete_auth_user` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
#   - `actor_employee_id`（str）：`actor_employee_id` 对应业务对象的唯一标识
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::admin_delete_user` 调用本符号
#   - 内部调用：`get_user_store().delete_user`、`get_user_store`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def delete_auth_user(
    employee_id: str,
    *,
    actor_employee_id: str,
) -> None:
    get_user_store().delete_user(
        employee_id,
        actor_employee_id=actor_employee_id,
    )


# 功能：实现 `cookie_secure_for_request` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `request`（Request）：当前 HTTP 请求及上下文
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`auth/auth.py` 的 `set_auth_cookie` 调用本符号；`auth/auth.py` 的 `clear_auth_cookie` 调用本符号
#   - 内部调用：`os.getenv`、`raw.strip().lower`、`raw.strip`、`request.headers.get`、`p.strip`、`forwarded_proto.split`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def cookie_secure_for_request(request: Request) -> bool:
    raw = os.getenv("AUTH_COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or "https" in {p.strip() for p in forwarded_proto.split(",")}


# 功能：更新或保存 `set_auth_cookie` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `response`（Response）：待读取或更新的 HTTP 响应
#   - `token`（str）：用于认证或续接请求的令牌
#   - `request`（Request）：当前 HTTP 请求及上下文
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::login` 调用本符号
#   - 内部调用：`response.set_cookie`、`cookie_secure_for_request`、`get_auth_cookie_max_age_seconds`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：删除或清理 `clear_auth_cookie` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `response`（Response）：待读取或更新的 HTTP 响应
#   - `request`（Request）：当前 HTTP 请求及上下文
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::logout` 调用本符号
#   - 内部调用：`response.delete_cookie`、`cookie_secure_for_request`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
    "get_current_user",
    "get_current_user_from_request",
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
