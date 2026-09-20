"""人员报警通知的短期缩略图授权；不是登录令牌，不授权详情或视频。"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

import cv2
from fastapi import HTTPException, Response

from AiVision.core.settings import settings
from AiVision.departments.department_registry import require_department

_PURPOSE = "human-alarm-notification-thumbnail-v1"
_THUMBNAIL_MAX_EDGE = 320


def _signature(alarm_id: int, department: str, expires: int) -> str:
    # 复用部署脚本注入的共享认证密钥，但签名域独立，不能当 JWT 使用。
    secret = os.environ.get("AUTH_SECRET", "")
    if len(secret) < 32:
        raise ValueError("人员报警通知缩略图要求配置至少 32 字符的 AUTH_SECRET")
    message = f"{_PURPOSE}:{alarm_id}:{department}:{expires}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def issue_thumbnail_token(alarm_id: int, department: str) -> str:
    require_department(department)
    if type(alarm_id) is not int or alarm_id <= 0:
        raise ValueError("人员报警通知缺少有效的报警 ID 或事业部")
    expires = int(time.time()) + settings.alarm.wechat_thumbnail_ttl_seconds
    return f"{expires}.{_signature(alarm_id, department, expires)}"


def verify_thumbnail_token(token: str, alarm_id: int, department: str) -> bool:
    if len(token) > 100:
        return False
    try:
        require_department(department)
        raw_expiry, signature = token.split(".")
        expires = int(raw_expiry)
        now = int(time.time())
        if not now < expires <= now + settings.alarm.wechat_thumbnail_ttl_seconds:
            return False
        return hmac.compare_digest(signature, _signature(alarm_id, department, expires))
    except (ValueError, TypeError):
        return False


def thumbnail_response(image_path: str) -> Response:
    frame = cv2.imread(image_path)
    if frame is None:
        raise HTTPException(status_code=404, detail="alarm image not found")
    height, width = frame.shape[:2]
    scale = min(1., _THUMBNAIL_MAX_EDGE / max(height, width))
    if scale < 1:
        frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                           interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", frame)
    if not ok:
        raise HTTPException(status_code=500, detail="alarm thumbnail encoding failed")
    return Response(jpeg.tobytes(), media_type="image/jpeg", headers={
        "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    })
