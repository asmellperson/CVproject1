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

COOKIE_NAME = "aicv_auth_token"
JWT_ALGORITHM = "HS256"
DEV_AUTH_SECRET = "dev-aicv-auth-secret-change-me"

logger = logging.getLogger("guard_room.auth")


class LoginRequest(BaseModel):
    employee_id: str
    password: str


class AuthError(Exception):
    pass


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _json_b64(data: dict[str, Any]) -> str:
    return _b64url_encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def get_auth_secret() -> str:
    secret = os.getenv("AUTH_SECRET")
    if secret:
        return secret
    logger.warning("AUTH_SECRET is not set; using insecure development default secret.")
    return DEV_AUTH_SECRET


def get_default_password() -> str:
    return os.getenv("AUTH_DEFAULT_PASSWORD", "Fuda@2026")


def get_token_expire_hours() -> int:
    raw = os.getenv("AUTH_TOKEN_EXPIRE_HOURS", "12")
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid AUTH_TOKEN_EXPIRE_HOURS=%r; using 12 hours.", raw)
        return 12


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_auth_users_path() -> Path:
    raw = os.getenv("AUTH_USERS_FILE")
    if raw:
        return Path(raw)
    return _repo_root() / "config" / "auth_users.json"


def load_auth_users() -> list[dict[str, Any]]:
    path = get_auth_users_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        logger.error("Auth users file not found: %s", path)
        raise AuthError("auth users file not found") from exc
    except json.JSONDecodeError as exc:
        logger.error("Auth users file is invalid JSON: %s", path)
        raise AuthError("auth users file is invalid") from exc


def find_enabled_user(employee_id: str) -> dict[str, str] | None:
    employee_id = str(employee_id).strip()
    for item in load_auth_users():
        if str(item.get("employee_id", "")).strip() != employee_id:
            continue
        if not item.get("enabled", False):
            return None
        return {
            "employee_id": employee_id,
            "name": str(item.get("name", "")),
            "role": str(item.get("role", "viewer")),
        }
    return None


def create_token(user: dict[str, str]) -> str:
    now = int(time.time())
    payload = {
        "sub": user["employee_id"],
        "name": user.get("name", ""),
        "role": user.get("role", "viewer"),
        "iat": now,
        "exp": now + get_token_expire_hours() * 3600,
    }
    header = {"typ": "JWT", "alg": JWT_ALGORITHM}
    signing_input = f"{_json_b64(header)}.{_json_b64(payload)}"
    signature = hmac.new(get_auth_secret().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_token(token: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(get_auth_secret().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
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

    if int(payload.get("exp", 0)) < int(time.time()):
        raise AuthError("token expired")
    return payload


def token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def get_current_user_from_request(request: Request) -> dict[str, str]:
    token = token_from_request(request)
    if not token:
        raise AuthError("not authenticated")
    payload = decode_token(token)
    user = find_enabled_user(str(payload.get("sub", "")))
    if user is None:
        raise AuthError("user disabled or not allowed")
    return user


def get_current_user(request: Request) -> dict[str, str]:
    try:
        return get_current_user_from_request(request)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def require_admin(user: dict[str, str] = Depends(get_current_user)) -> dict[str, str]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin permission required")
    return user


def verify_login(employee_id: str, password: str) -> dict[str, str] | None:
    user = find_enabled_user(employee_id)
    if user is None:
        return None
    if not hmac.compare_digest(password, get_default_password()):
        return None
    return user


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
        max_age=get_token_expire_hours() * 3600,
    )


def clear_auth_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=cookie_secure_for_request(request),
        samesite="lax",
    )
