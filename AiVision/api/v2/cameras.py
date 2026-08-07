"""
api/v2/cameras.py
摄像头 CRUD + 当前帧 JPEG 输出。
"""
from __future__ import annotations

import threading
import time
from typing import Any

import cv2
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from api.auth import get_current_user, require_admin
from api.deps import get_camera_service, get_current_orchestrator
from core.logger import logger
from core.settings import settings


router = APIRouter(prefix="/api/v2/cameras", tags=["cameras"])

_JPEG_CACHE_MAX_ITEMS = 128
_jpeg_cache_lock = threading.Lock()
_jpeg_cache: dict[tuple[Any, ...], bytes] = {}
_jpeg_cache_order: list[tuple[Any, ...]] = []


class CameraCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    shm_name: str = Field(..., min_length=1)
    fps: int = Field(5, gt=0)
    max_restart: int = Field(10, ge=0)
    enable: bool | None = None
    enabled: bool | None = None
    department: str | None = None


class CameraUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    fps: int | None = Field(None, gt=0)
    max_restart: int | None = Field(None, ge=0)
    enable: bool | None = None
    enabled: bool | None = None
    department: str | None = None


def camera_read_department(user: dict, requested_department: str | None) -> str | None:
    """返回当前用户可读取的部门过滤值。"""
    if user.get("role") == "admin":
        return requested_department
    department = user.get("department")
    if not department:
        raise HTTPException(status_code=403, detail="camera department permission required")
    if requested_department is not None and requested_department != department:
        raise HTTPException(status_code=403, detail="camera department permission required")
    return str(department)


def get_camera_for_user(camera_service, key: str, user: dict) -> dict[str, Any]:
    """按 key 读取摄像头，并阻止 viewer 通过 id/shm 枚举其他部门。"""
    camera = camera_service.get_camera(key)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    if user.get("role") != "admin":
        department = user.get("department")
        if not department or camera.get("department") != department:
            raise HTTPException(status_code=403, detail="camera department permission required")
    return camera


@router.get("")
def list_cameras(
    department: str | None = Query(None, description="可选按部门过滤"),
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
) -> list[dict[str, Any]]:
    return camera_service.list_cameras(
        department=camera_read_department(user, department)
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreateRequest,
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
) -> dict[str, Any]:
    try:
        return camera_service.create_camera(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{key}")
def get_camera(
    key: str,
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
) -> dict[str, Any]:
    return get_camera_for_user(camera_service, key, user)


@router.put("/{key}")
def update_camera(
    key: str,
    payload: CameraUpdateRequest,
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
) -> dict[str, Any]:
    try:
        camera = camera_service.update_camera(key, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return camera


@router.patch("/{key}")
def patch_camera(
    key: str,
    payload: CameraUpdateRequest,
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
) -> dict[str, Any]:
    return update_camera(key, payload, _user, camera_service)


@router.delete("/{key}")
def delete_camera(
    key: str,
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
) -> dict[str, bool]:
    ok = camera_service.delete_camera(key)
    if not ok:
        raise HTTPException(status_code=404, detail="camera not found")
    return {"ok": True}


def encode_frame_to_jpeg(
    frame,
    quality: int = 85,
    max_width: int | None = None,
    max_height: int | None = None,
    cache_token: tuple[Any, ...] | None = None,
) -> bytes:
    if frame is None:
        raise HTTPException(status_code=404, detail="frame not available")
    quality = max(1, min(int(quality), 100))
    cache_key = (cache_token, quality, max_width, max_height) if cache_token is not None else None
    if cache_key is not None:
        with _jpeg_cache_lock:
            cached = _jpeg_cache.get(cache_key)
            if cached is not None:
                return cached

    if max_width or max_height:
        height, width = frame.shape[:2]
        width_scale = (max_width / width) if max_width and width > max_width else 1.0
        height_scale = (max_height / height) if max_height and height > max_height else 1.0
        scale = min(width_scale, height_scale)
        if scale < 1.0:
            frame = cv2.resize(
                frame,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise HTTPException(status_code=500, detail="failed to encode frame")
    content = encoded.tobytes()
    if cache_key is not None:
        with _jpeg_cache_lock:
            if cache_key not in _jpeg_cache:
                _jpeg_cache_order.append(cache_key)
            _jpeg_cache[cache_key] = content
            while len(_jpeg_cache_order) > _JPEG_CACHE_MAX_ITEMS:
                old_key = _jpeg_cache_order.pop(0)
                _jpeg_cache.pop(old_key, None)
    return content


def frame_size_headers(frame) -> dict[str, str]:
    if frame is None:
        return {}
    height, width = frame.shape[:2]
    return {
        "X-Frame-Width": str(width),
        "X-Frame-Height": str(height),
    }


def build_camera_frame_response(
    *,
    key: str,
    feature: str | None,
    quality: int,
    max_width: int | None,
    max_height: int | None,
    orchestrator,
) -> Response:
    """读取、编码并返回预览帧；慢请求输出分阶段耗时。"""
    started_at = time.monotonic()
    if hasattr(orchestrator, "get_camera_frame_info"):
        frame, updated_at = orchestrator.get_camera_frame_info(key, feature=feature)
    else:
        frame, updated_at = orchestrator.get_camera_frame(key, feature=feature), 0.0
    lookup_seconds = time.monotonic() - started_at

    if frame is None and updated_at:
        raise HTTPException(status_code=503, detail="camera frame is stale")

    encode_started_at = time.monotonic()
    content = encode_frame_to_jpeg(
        frame,
        quality,
        max_width=max_width,
        max_height=max_height,
        cache_token=(key, feature or "", updated_at),
    )
    encode_seconds = time.monotonic() - encode_started_at
    total_seconds = time.monotonic() - started_at

    if total_seconds >= settings.runtime.slow_frame_log_seconds:
        height, width = frame.shape[:2]
        logger.warning(
            f"[CameraFrame] 慢响应 key={key} feature={feature or '-'} "
            f"lookup={lookup_seconds:.3f}s encode={encode_seconds:.3f}s "
            f"total={total_seconds:.3f}s source={width}x{height} "
            f"max_width={max_width or '-'} max_height={max_height or '-'}"
        )

    return Response(
        content=content,
        media_type="image/jpeg",
        headers=frame_size_headers(frame),
    )


@router.get("/{key}/frame.jpg")
def get_camera_frame_jpg(
    key: str,
    feature: str | None = Query(None, description="可选 feature 名，优先返回该功能的标注帧"),
    quality: int = Query(85, ge=1, le=100),
    max_width: int | None = Query(None, ge=1, le=4096),
    max_height: int | None = Query(None, ge=1, le=4096),
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
    orchestrator=Depends(get_current_orchestrator),
) -> Response:
    get_camera_for_user(camera_service, key, user)
    return build_camera_frame_response(
        key=key,
        feature=feature,
        quality=quality,
        max_width=max_width,
        max_height=max_height,
        orchestrator=orchestrator,
    )
