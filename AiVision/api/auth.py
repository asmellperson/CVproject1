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

from fastapi import Depends, HTTPException, Request, status

COOKIE_NAME = "aicv_auth_token"
JWT_ALGORITHM = "HS256"
DEV_AUTH_SECRET = "dev-aicv-auth-secret-change-me"

logger = logging.getLogger("aivision.auth")


class AuthError(Exception):
    pass


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def get_auth_secret() -> str:
    secret = os.getenv("AUTH_SECRET")
    if secret:
        return secret
    logger.warning("AUTH_SECRET is not set; using insecure development default secret.")
    return DEV_AUTH_SECRET


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_auth_users_path() -> Path:
    raw = os.getenv("AUTH_USERS_FILE")
    if raw:
        return Path(raw)
    return _repo_root().parent / "guard_room" / "config" / "auth_users.json"


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
