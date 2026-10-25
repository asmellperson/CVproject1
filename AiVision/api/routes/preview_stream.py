"""已授权的单路 go2rtc MSE 代理；浏览器不接触媒体服务或摄像头地址。"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import json
import logging
import re
from typing import Literal
from urllib.parse import urlencode, urlsplit

import httpx
from anyio import CancelScope, to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.websockets import WebSocketState
from websockets.asyncio.client import connect

from auth.auth import AuthError, get_current_user, get_current_user_from_request
from auth.feature_permissions import require_feature_access
from AiVision.api.deps import get_camera_config_manager
from AiVision.api.routes.cameras import _require_camera_read_access
from AiVision.core.logger import logger
from AiVision.core.settings import settings
from AiVision.features.registry import get_spec

router = APIRouter(tags=["camera-preview"])
_CONNECT_TIMEOUT_SECONDS = 5.0
_AUTH_CHECK_TIMEOUT_SECONDS = 5.0
_IDLE_TIMEOUT_SECONDS = 15.0
_CLOSE_TIMEOUT_SECONDS = 2.0
_MAX_HANDSHAKE_BYTES = 1024
_MAX_MEDIA_BYTES = 8 * 1024 * 1024
_CODECS = re.compile(r"[A-Za-z0-9.,_-]{1,512}")
_MIME = re.compile(r'video/mp4;\s*codecs="[A-Za-z0-9., _-]{1,512}"')
_UNAVAILABLE = "视频预览暂不可用"
_SOURCE_REQUEST = ContextVar("preview_source_request", default=False)


class _SourceRequestLogFilter(logging.Filter):
    """只脱敏当前媒体源注册的日志参数，不影响其他异步请求或业务日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if _SOURCE_REQUEST.get() and isinstance(record.args, tuple):
            record.args = tuple(
                value.copy_remove_param("src") if isinstance(value, httpx.URL) else value
                for value in record.args
            )
        return True


# 在源 logger 过滤后再向已有 handler 传播，避免 INFO 请求 URL 泄漏 RTSP 凭据。
logging.getLogger("httpx").addFilter(_SourceRequestLogFilter())


class PreviewCapability(BaseModel):
    enabled: bool
    mode: Literal["mse", "jpeg"]
    url: str | None
    raw: Literal[True] = True


class PreviewPolicyError(Exception):
    """客户端协议或持续授权不符合单路试点规则。"""


def _load_source(manager, key: str, user: dict, feature: str | None) -> dict:
    source = _require_camera_read_access(manager.get_camera_preview_source(key), user)
    if feature is not None:
        if get_spec(feature) is None:
            raise HTTPException(404, "unknown feature")
        require_feature_access(user, feature, source["department"])
    return source


def _pilot_enabled(source: dict, feature: str | None) -> bool:
    preview = settings.preview
    try:
        address = urlsplit(source["url"])
        valid_source = address.scheme.lower() in {"rtsp", "rtsps"} and bool(address.hostname)
    except ValueError:
        return False
    return bool(
        preview.camera_key and source["shm_name"] == preview.camera_key
        and feature == preview.feature and source["enabled"]
        and valid_source
    )


@router.get("/api/cameras/{key}/preview", response_model=PreviewCapability)
def get_preview_capability(
    key: str,
    feature: str | None = Query(None),
    user: dict = Depends(get_current_user),
    camera_config_manager=Depends(get_camera_config_manager),
) -> PreviewCapability:
    source = _load_source(camera_config_manager, key, user, feature)
    enabled = _pilot_enabled(source, feature)
    return PreviewCapability(
        enabled=enabled, mode="mse" if enabled else "jpeg",
        url=(f"/ws/cameras/{source['shm_name']}/preview?{urlencode({'feature': feature})}" if enabled else None),
    )


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return False
    # HTTP 的通配 CORS 不授权携带 Cookie 的跨站 WebSocket；代理需保留浏览器 Host。
    if origin in {value for value in settings.api.cors_origins if value != "*"}:
        return True
    scheme = "https" if websocket.url.scheme == "wss" else "http"
    return origin == f"{scheme}://{websocket.headers.get('host', '')}"


async def _authorized_source(websocket: WebSocket, manager, key: str, feature: str | None) -> dict:
    async def read_authorization() -> dict:
        # 超时后只放弃只读结果，不再等待阻塞线程；会话必须立即停止继续转发媒体。
        user = await to_thread.run_sync(get_current_user_from_request, websocket, abandon_on_cancel=True)
        source = await to_thread.run_sync(_load_source, manager, key, user, feature, abandon_on_cancel=True)
        if not _pilot_enabled(source, feature):
            raise PreviewPolicyError()
        return source

    try:
        # 用户认证、功能授权和摄像头来源共用一次期限，不能分别重新计时。
        return await asyncio.wait_for(read_authorization(), _AUTH_CHECK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise PreviewPolicyError() from exc


async def _read_handshake(websocket: WebSocket) -> dict:
    message = await asyncio.wait_for(websocket.receive(), _CONNECT_TIMEOUT_SECONDS)
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    text = message.get("text")
    if not isinstance(text, str) or len(text.encode("utf-8")) > _MAX_HANDSHAKE_BYTES:
        raise PreviewPolicyError()
    try:
        handshake = json.loads(text)
    except ValueError as exc:
        raise PreviewPolicyError() from exc
    if (not isinstance(handshake, dict) or set(handshake) != {"type", "value"}
            or handshake["type"] != "mse" or not isinstance(handshake["value"], str)
            or not _CODECS.fullmatch(handshake["value"])):
        raise PreviewPolicyError()
    return handshake


async def _register_source(source: dict) -> tuple[str, str]:
    stream_name = f"fuda_preview_camera_{source['camera_id']}"
    base_url = settings.preview.base_url
    async with httpx.AsyncClient(timeout=_CONNECT_TIMEOUT_SECONDS, trust_env=False) as client:
        privacy = _SOURCE_REQUEST.set(True)
        try:
            # PATCH 只更新内存媒体源，数据库仍是唯一来源，RTSP 凭据不落侧车配置文件。
            response = await client.patch(
                f"{base_url}/api/streams", params={"name": stream_name, "src": source["url"]},
            )
            response.raise_for_status()
        finally:
            _SOURCE_REQUEST.reset(privacy)
    return f"{base_url.replace('http://', 'ws://', 1)}/api/ws?{urlencode({'src': stream_name})}", stream_name


async def _relay_media(websocket: WebSocket, upstream) -> None:
    announced = False
    while True:
        message = await asyncio.wait_for(upstream.recv(), _IDLE_TIMEOUT_SECONDS)
        if isinstance(message, bytes):
            if not announced:
                raise ValueError("媒体协议顺序无效")
            await asyncio.wait_for(websocket.send_bytes(message), _CONNECT_TIMEOUT_SECONDS)
            continue
        if len(message.encode("utf-8")) > _MAX_HANDSHAKE_BYTES:
            raise ValueError("媒体协议消息过长")
        try:
            payload = json.loads(message)
        except ValueError as exc:
            raise ValueError("媒体协议消息无效") from exc
        if not isinstance(payload, dict):
            raise ValueError("媒体协议消息无效")
        if payload.get("type") == "error":
            raise ValueError("媒体服务不可用")
        if payload.get("type") != "mse":
            # 其他协议的消息可能携带源地址，不能作为通用 WebSocket 代理透传。
            continue
        mime = payload.get("value")
        if announced or not isinstance(mime, str) or not _MIME.fullmatch(mime):
            raise ValueError("媒体协议类型无效")
        await asyncio.wait_for(websocket.send_json({"type": "mse", "value": mime}), _CONNECT_TIMEOUT_SECONDS)
        announced = True


async def _watch_client(websocket: WebSocket) -> None:
    message = await websocket.receive()
    if message["type"] != "websocket.disconnect":
        # 握手后客户端只能断开，不允许继续控制 go2rtc 或更换媒体源。
        raise PreviewPolicyError()


async def _reauthorize(websocket: WebSocket, manager, key: str, feature: str | None, original: dict) -> None:
    while True:
        await asyncio.sleep(settings.preview.auth_check_seconds)
        current = await _authorized_source(websocket, manager, key, feature)
        if current != original:
            raise PreviewPolicyError()


async def _stream_media(websocket: WebSocket, source: dict, handshake: dict) -> None:
    upstream_url, _ = await _register_source(source)
    async with connect(
        upstream_url, open_timeout=_CONNECT_TIMEOUT_SECONDS, close_timeout=_CLOSE_TIMEOUT_SECONDS,
        max_size=_MAX_MEDIA_BYTES, max_queue=4, compression=None, proxy=None,
    ) as upstream:
        await asyncio.wait_for(upstream.send(json.dumps(handshake)), _CONNECT_TIMEOUT_SECONDS)
        await _relay_media(websocket, upstream)


async def _relay_session(websocket: WebSocket, manager, key: str, feature: str | None, source: dict, handshake: dict) -> None:
    tasks = {
        asyncio.create_task(_stream_media(websocket, source, handshake)),
        asyncio.create_task(_watch_client(websocket)),
        asyncio.create_task(_reauthorize(websocket, manager, key, feature, source)),
    }
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        # ASGI 断连也会取消当前作用域，清理阶段仍需等待上游退出以释放媒体消费者。
        with CancelScope(shield=True):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def _close_client(websocket: WebSocket, code: int) -> None:
    if websocket.application_state == WebSocketState.DISCONNECTED or websocket.client_state == WebSocketState.DISCONNECTED:
        return
    try:
        await asyncio.wait_for(websocket.close(code=code), _CLOSE_TIMEOUT_SECONDS)
    except (OSError, RuntimeError, TimeoutError):
        logger.debug("[PreviewStream] 客户端连接已结束")


@router.websocket("/ws/cameras/{key}/preview")
async def preview_websocket(
    websocket: WebSocket, key: str, feature: str | None = Query(None),
    camera_config_manager=Depends(get_camera_config_manager),
) -> None:
    close_code = 1000
    try:
        # 明确返回策略关闭码，前端据此停止回退，避免把撤权当成网络故障。
        await websocket.accept()
        if (not _origin_allowed(websocket) or set(websocket.query_params) - {"feature"}
                or len(websocket.query_params.getlist("feature")) != 1):
            raise PreviewPolicyError()
        source = await _authorized_source(websocket, camera_config_manager, key, feature)
        handshake = await _read_handshake(websocket)
        await _relay_session(websocket, camera_config_manager, key, feature, source, handshake)
    except (AuthError, HTTPException, PreviewPolicyError):
        close_code = 1008
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError:
        return
    except Exception as exc:
        close_code = 1011
        # HTTP/媒体异常文本可能含带认证的源地址，仅记录异常类型。
        logger.warning(f"[PreviewStream] 预览连接失败 error_type={type(exc).__name__}")
        if websocket.application_state == WebSocketState.CONNECTED and websocket.client_state == WebSocketState.CONNECTED:
            try:
                await asyncio.wait_for(websocket.send_json({"type": "error", "value": _UNAVAILABLE}), _CONNECT_TIMEOUT_SECONDS)
            except (OSError, RuntimeError, TimeoutError):
                logger.debug("[PreviewStream] 错误提示发送时客户端已断开")
    finally:
        with CancelScope(shield=True):
            await _close_client(websocket, close_code)
