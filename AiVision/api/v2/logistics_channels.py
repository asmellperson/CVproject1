"""物流通道 CRUD、成员、运行状态和拼接画面 API。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ConfigDict

from api.auth import get_current_user, require_admin
from api.deps import get_current_orchestrator, get_logistics_channel_service
from api.v2.cameras import encode_frame_to_jpeg, frame_size_headers
from core.db import get_session
from features import all_specs
from platform.logistics_channel.constants import (
    LOGISTICS_FEATURE_DEPARTMENTS,
    LOGISTICS_FEATURES,
)
from platform.logistics_channel.schema import (
    LogisticsChannelAlarmListResponse,
    LogisticsChannelConfigUpdate,
    LogisticsChannelCreate,
    LogisticsChannelDetailResponse,
    LogisticsChannelListResponse,
    LogisticsChannelMemberCreate,
    LogisticsChannelMemberOrder,
    LogisticsChannelOkResponse,
    LogisticsChannelRuntimeStatusResponse,
    LogisticsChannelStatisticsResponse,
    LogisticsChannelUpdate,
)
from platform.violation.orm import AiViolationImage


router = APIRouter(prefix="/api/v2/logistics-channels", tags=["logistics-channels"])


class LogisticsChannelPutRequest(LogisticsChannelUpdate):
    """通道元数据和通道级检测配置的一次更新。"""

    model_config = ConfigDict(extra="forbid")
    config: LogisticsChannelConfigUpdate | None = None


def _require_feature_access(feature: str, user: dict) -> str:
    if feature not in LOGISTICS_FEATURES:
        raise HTTPException(status_code=404, detail="logistics feature not found")
    if user.get("role") == "admin":
        return feature
    expected_department = LOGISTICS_FEATURE_DEPARTMENTS[feature]
    if user.get("department") != expected_department:
        raise HTTPException(status_code=403, detail="feature department permission required")
    return feature


def _raise_service_error(exc: ValueError) -> None:
    detail = str(exc)
    if "不存在" in detail:
        code = status.HTTP_404_NOT_FOUND
    elif any(marker in detail for marker in ("已存在", "已绑定", "约束冲突", "最多", "上限")):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=detail) from exc


def _get_channel_or_404(service, feature: str, channel_id: int) -> dict:
    channel = service.get_channel(feature, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="logistics channel not found")
    return channel


@router.get("/{feature}", response_model=LogisticsChannelListResponse)
def list_channels(
    feature: str,
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelListResponse:
    return LogisticsChannelListResponse.model_validate(
        service.list_channels(_require_feature_access(feature, user))
    )


@router.post(
    "/{feature}",
    status_code=status.HTTP_201_CREATED,
    response_model=LogisticsChannelDetailResponse,
)
def create_channel(
    feature: str,
    payload: LogisticsChannelCreate,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        return LogisticsChannelDetailResponse.model_validate(
            service.create_channel(feature, payload.name)
        )
    except ValueError as exc:
        _raise_service_error(exc)


@router.get("/{feature}/{channel_id}", response_model=LogisticsChannelDetailResponse)
def get_channel(
    feature: str,
    channel_id: int,
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    return LogisticsChannelDetailResponse.model_validate(
        _get_channel_or_404(service, _require_feature_access(feature, user), channel_id)
    )


@router.put("/{feature}/{channel_id}", response_model=LogisticsChannelDetailResponse)
def update_channel(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelPutRequest,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    metadata = payload.model_dump(exclude_unset=True, exclude={"config"})
    try:
        result = service.update_channel_and_config(
            feature,
            channel_id,
            metadata,
            payload.config,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="logistics channel not found")
        return LogisticsChannelDetailResponse.model_validate(result)
    except ValueError as exc:
        _raise_service_error(exc)


@router.put(
    "/{feature}/{channel_id}/config",
    response_model=LogisticsChannelDetailResponse,
)
def update_channel_config(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelConfigUpdate,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        result = service.update_config(feature, channel_id, payload)
    except ValueError as exc:
        _raise_service_error(exc)
    if result is None:
        raise HTTPException(status_code=404, detail="logistics channel not found")
    return LogisticsChannelDetailResponse.model_validate(result)


@router.delete("/{feature}/{channel_id}", response_model=LogisticsChannelOkResponse)
def delete_channel(
    feature: str,
    channel_id: int,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelOkResponse:
    feature = _require_feature_access(feature, user)
    if not service.delete_channel(feature, channel_id):
        raise HTTPException(status_code=404, detail="logistics channel not found")
    return LogisticsChannelOkResponse(ok=True)


@router.post(
    "/{feature}/{channel_id}/cameras",
    response_model=LogisticsChannelDetailResponse,
)
def add_camera(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelMemberCreate,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        if payload.camera_id is not None:
            result = service.add_existing_camera(feature, channel_id, payload.camera_id)
        else:
            result = service.create_camera_and_bind(feature, channel_id, payload)
        return LogisticsChannelDetailResponse.model_validate(result)
    except ValueError as exc:
        _raise_service_error(exc)


@router.put(
    "/{feature}/{channel_id}/cameras/order",
    response_model=LogisticsChannelDetailResponse,
)
def reorder_cameras(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelMemberOrder,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        return LogisticsChannelDetailResponse.model_validate(
            service.reorder_members(feature, channel_id, payload.camera_ids)
        )
    except ValueError as exc:
        _raise_service_error(exc)


@router.put(
    "/{feature}/{channel_id}/cameras/{camera_id}",
    response_model=LogisticsChannelDetailResponse,
)
def move_camera(
    feature: str,
    channel_id: int,
    camera_id: int,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        return LogisticsChannelDetailResponse.model_validate(
            service.move_camera(feature, camera_id, channel_id)
        )
    except ValueError as exc:
        _raise_service_error(exc)


@router.delete(
    "/{feature}/{channel_id}/cameras/{camera_id}",
    response_model=LogisticsChannelOkResponse,
)
def remove_camera(
    feature: str,
    channel_id: int,
    camera_id: int,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelOkResponse:
    feature = _require_feature_access(feature, user)
    if not service.remove_camera(feature, channel_id, camera_id):
        raise HTTPException(status_code=404, detail="channel camera membership not found")
    return LogisticsChannelOkResponse(ok=True)


@router.get(
    "/{feature}/{channel_id}/status",
    response_model=LogisticsChannelRuntimeStatusResponse,
)
def get_channel_status(
    feature: str,
    channel_id: int,
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
    orchestrator=Depends(get_current_orchestrator),
) -> LogisticsChannelRuntimeStatusResponse:
    feature = _require_feature_access(feature, user)
    channel = _get_channel_or_404(service, feature, channel_id)
    value = orchestrator.get_logistics_channel_status(feature, channel_id)
    if value is not None:
        return LogisticsChannelRuntimeStatusResponse.model_validate(value)
    return LogisticsChannelRuntimeStatusResponse.model_validate({
        "feature_name": feature,
        "channel_id": channel_id,
        "channel_name": channel["name"],
        "reason": "unknown",
        "alarm": False,
        "camera_ids": [member["camera_id"] for member in channel.get("members", [])],
        "camera_counts": {},
        "camera_states": {},
        "offending_camera_ids": [],
        "updated_at": None,
    })


@router.get("/{feature}/{channel_id}/frame.jpg")
def get_channel_frame(
    feature: str,
    channel_id: int,
    quality: int = Query(85, ge=1, le=100),
    max_width: int | None = Query(None, ge=1, le=4096),
    max_height: int | None = Query(None, ge=1, le=4096),
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
    orchestrator=Depends(get_current_orchestrator),
) -> Response:
    feature = _require_feature_access(feature, user)
    _get_channel_or_404(service, feature, channel_id)
    frame = orchestrator.get_logistics_channel_frame(feature, channel_id)
    if frame is None:
        raise HTTPException(status_code=503, detail="logistics channel frame not available")
    content = encode_frame_to_jpeg(
        frame,
        quality,
        max_width=max_width,
        max_height=max_height,
    )
    headers = {"Cache-Control": "no-store"}
    if max_width is None and max_height is None:
        headers.update(frame_size_headers(frame))
    return Response(
        content=content,
        media_type="image/jpeg",
        headers=headers,
    )


def _alarm_dict(row: AiViolationImage) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "feature_name": (row.event_metadata or {}).get("feature_name"),
        "channel_id": int(row.subject_id),
        "channel_name": row.subject_name,
        "reason": row.reason,
        "created_at": row.create_time.isoformat(sep=" ") if row.create_time else None,
        "image_url": f"/api/v2/alarms/{row.id}/image",
        "metadata": row.event_metadata or {},
    }


def _channel_alarm_query(session, feature: str, channel_id: int):
    return session.query(AiViolationImage).filter(
        AiViolationImage.subject_type == "logistics_channel",
        AiViolationImage.subject_id == str(channel_id),
        AiViolationImage.violation_type == all_specs()[feature].violation_type,
    )


@router.get(
    "/{feature}/{channel_id}/alarms",
    response_model=LogisticsChannelAlarmListResponse,
)
def list_channel_alarms(
    feature: str,
    channel_id: int,
    limit: int = Query(200, ge=1, le=1000),
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelAlarmListResponse:
    feature = _require_feature_access(feature, user)
    _get_channel_or_404(service, feature, channel_id)
    session = get_session()
    try:
        rows = _channel_alarm_query(session, feature, channel_id).order_by(
            AiViolationImage.create_time.desc(), AiViolationImage.id.desc()
        ).limit(limit).all()
        return LogisticsChannelAlarmListResponse.model_validate(
            {"items": [_alarm_dict(row) for row in rows]}
        )
    finally:
        session.close()


@router.get(
    "/{feature}/{channel_id}/statistics",
    response_model=LogisticsChannelStatisticsResponse,
)
def channel_statistics(
    feature: str,
    channel_id: int,
    days: int = Query(7, ge=1, le=90),
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelStatisticsResponse:
    feature = _require_feature_access(feature, user)
    _get_channel_or_404(service, feature, channel_id)
    now = dt.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    range_start = today_start - dt.timedelta(days=days - 1)
    session = get_session()
    try:
        rows = _channel_alarm_query(session, feature, channel_id).filter(
            AiViolationImage.create_time >= range_start
        ).order_by(AiViolationImage.create_time.asc()).all()
        counts: dict[str, int] = {}
        for row in rows:
            if row.create_time:
                key = row.create_time.strftime("%Y-%m-%d")
                counts[key] = counts.get(key, 0) + 1
        daily = []
        for offset in range(days):
            key = (range_start + dt.timedelta(days=offset)).strftime("%Y-%m-%d")
            daily.append({"day": key, "count": counts.get(key, 0)})
        return LogisticsChannelStatisticsResponse.model_validate({
            "summary": {
                "total": len(rows),
                "today": sum(1 for row in rows if row.create_time and row.create_time >= today_start),
            },
            "daily": daily,
        })
    finally:
        session.close()
