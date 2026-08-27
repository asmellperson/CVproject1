"""报警记录与统计聚合接口。"""
from __future__ import annotations

import datetime as dt
import os
from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from core.db import get_session
from core.logger import logger
from core.video_encoding import VideoEncodingError, ensure_browser_compatible_mp4
from platform.camera.orm import AiCameraConfig
from platform.violation.orm import AiViolationImage


router = APIRouter(prefix="/api/v2/alarms", tags=["alarms"])

_TYPE_META = {
    1: {"event_type": "blocks", "label": "区域入侵", "color": "#ef4444"},
    2: {"event_type": "detect_door", "label": "大门开关", "color": "#f59e0b"},
    3: {"event_type": "detect_phone", "label": "手机检测", "color": "#f97316"},
    4: {"event_type": "detect_face", "label": "人脸检测", "color": "#8b5cf6"},
    5: {"event_type": "detect_human", "label": "人体逗留", "color": "#2563eb"},
    6: {"event_type": "detect_logistics_single_person", "label": "物流通道单人检测", "color": "#0f766e"},
    7: {"event_type": "detect_logistics_single_person_electronics_electrician", "label": "物流通道单人检测（电子电工）", "color": "#0f766e"},
    8: {"event_type": "detect_logistics_single_person_electrical_components", "label": "物流通道单人检测（电气部件）", "color": "#0f766e"},
    9: {"event_type": "detect_logistics_single_person_precious_metal_recycling", "label": "物流通道单人检测（贵金属回收）", "color": "#0f766e"},
    10: {"event_type": "detect_human_haoda", "label": "人体逗留检测（皓达公司）", "color": "#1d4ed8"},
}
_DEFAULT_META = {"event_type": "unknown", "label": "未知报警", "color": "#64748b"}
_MAX_CAMERA_ID = 2**31 - 1  # AiCameraConfig.id 使用有符号 SQL Integer。


class AlarmEventResponse(BaseModel):
    """统一告警列表项，同时兼容旧摄像头告警和通道告警。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    event_type: str
    event_label: str
    violation_type: int | None = None
    camera_no: str
    camera_name: str
    subject_type: str
    subject_id: str | None = None
    subject_name: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    reason: str
    status: str | None = None
    confidence: float = 1
    created_at: str | None = None
    image_path: str | None = None
    image_url: str
    video_path: str | None = None
    video_status: str | None = None
    camera_ids: list[int] = Field(default_factory=list)
    camera_names: dict[str, str] = Field(default_factory=dict)
    camera_counts: dict[str, int | None] = Field(default_factory=dict)
    camera_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    offending_camera_ids: list[int] = Field(default_factory=list)
    evidence_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AlarmListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AlarmEventResponse] = Field(default_factory=list)


def _meta(violation_type: int | None) -> dict[str, str]:
    return _TYPE_META.get(int(violation_type or 0), _DEFAULT_META)


def _camera_names(session) -> dict[str, str]:
    rows = session.query(AiCameraConfig.shm_name, AiCameraConfig.name).all()
    return {shm: name for shm, name in rows if shm}


def _dict_value(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            camera_id = item
        elif isinstance(item, str):
            normalized = item.strip()
            if not normalized or any(char not in "0123456789" for char in normalized):
                continue
            try:
                camera_id = int(normalized)
            except (ValueError, OverflowError):
                continue
        else:
            continue
        if not 1 <= camera_id <= _MAX_CAMERA_ID or camera_id in seen:
            continue
        seen.add(camera_id)
        result.append(camera_id)
    return result


def _channel_alarm_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    raw_states = _dict_value(metadata.get("camera_states"))
    camera_states = {
        key: dict(value)
        for key, value in raw_states.items()
        if isinstance(value, dict)
    }
    raw_counts = _dict_value(metadata.get("camera_counts"))
    camera_counts: dict[str, int | None] = {}
    for key, value in raw_counts.items():
        if value is None:
            camera_counts[key] = None
        elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            camera_counts[key] = value

    explicit_names = _dict_value(metadata.get("camera_names"))
    camera_names = {
        key: str(value)
        for key, value in explicit_names.items()
        if value is not None
    }
    for key, state in camera_states.items():
        if state.get("camera_name") is not None:
            camera_names.setdefault(key, str(state["camera_name"]))
    evidence_error = metadata.get("evidence_error")
    return {
        "camera_ids": _int_list(metadata.get("camera_ids")),
        "camera_names": camera_names,
        "camera_counts": camera_counts,
        "camera_states": camera_states,
        "offending_camera_ids": _int_list(metadata.get("offending_camera_ids")),
        "evidence_error": str(evidence_error) if evidence_error is not None else None,
    }


def _event_dict(row: AiViolationImage, cameras: dict[str, str]) -> dict[str, Any]:
    meta = _meta(getattr(row, "violation_type", None))
    camera_key = getattr(row, "camera_no", None) or ""
    raw_metadata = getattr(row, "event_metadata", None)
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    subject_type = str(getattr(row, "subject_type", None) or "camera")
    subject_id = getattr(row, "subject_id", None)
    subject_name = getattr(row, "subject_name", None)
    persisted_reason = getattr(row, "reason", None)
    is_channel = subject_type == "logistics_channel"
    channel_id_value = subject_id if subject_id is not None else metadata.get("channel_id")
    channel_id = str(channel_id_value) if is_channel and channel_id_value is not None else None
    channel_name = None
    if is_channel:
        channel_name = str(
            subject_name
            or metadata.get("channel_name")
            or cameras.get(camera_key)
            or camera_key
            or "物流通道"
        )
        camera_key = f"logistics_channel_{channel_id}" if channel_id else "logistics_channel"
    camera_name = str(channel_name or cameras.get(camera_key) or camera_key or "-")
    if not is_channel:
        subject_id = subject_id if subject_id is not None else (camera_key or None)
        subject_name = subject_name if subject_name is not None else camera_name
    reason = str(
        persisted_reason
        or metadata.get("reason")
        or f"{meta['label']} - {camera_name if camera_name != '-' else '未知摄像头'}"
    )
    create_time = getattr(row, "create_time", None)
    created_at = create_time.isoformat(sep=" ") if create_time else None
    return {
        "id": str(row.id),
        "event_type": meta["event_type"],
        "event_label": meta["label"],
        "violation_type": row.violation_type,
        "camera_no": camera_key,
        "camera_name": camera_name,
        "subject_type": subject_type,
        "subject_id": str(subject_id) if subject_id is not None else None,
        "subject_name": str(subject_name) if subject_name is not None else None,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "reason": reason,
        "status": reason if is_channel else None,
        "confidence": 1,
        "created_at": created_at,
        "image_path": row.image_path,
        "image_url": f"/api/aivision/alarms/{row.id}/image",
        "video_path": getattr(row, "video_path", None),
        "video_status": getattr(row, "video_status", None),
        **_channel_alarm_fields(metadata),
        "metadata": metadata,
    }


@router.get("", response_model=AlarmListResponse)
def list_alarms(limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    session = get_session()
    try:
        cameras = _camera_names(session)
        rows = (
            session.query(AiViolationImage)
            .order_by(AiViolationImage.create_time.desc(), AiViolationImage.id.desc())
            .limit(limit)
            .all()
        )
        return {"items": [_event_dict(row, cameras) for row in rows]}
    finally:
        session.close()


@router.get("/{alarm_id}/image")
def alarm_image(alarm_id: int):
    session = get_session()
    try:
        row = session.query(AiViolationImage).filter(AiViolationImage.id == alarm_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="alarm not found")
        if not row.image_path or not os.path.exists(row.image_path):
            raise HTTPException(status_code=404, detail="alarm image not found")
        return FileResponse(row.image_path, media_type="image/png")
    finally:
        session.close()


@router.get("/{alarm_id}/video")
def alarm_video(alarm_id: int):
    session = get_session()
    try:
        row = session.query(AiViolationImage).filter(AiViolationImage.id == alarm_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="alarm not found")
        if getattr(row, "video_status", None) != "ready":
            raise HTTPException(status_code=404, detail="alarm video is not ready")
        video_path = getattr(row, "video_path", None)
        if not video_path or not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail="alarm video not found")
        try:
            compatible_path = ensure_browser_compatible_mp4(video_path)
        except VideoEncodingError as exc:
            logger.warning(f"[AlarmVideo] 浏览器兼容转换失败 alarm_id={alarm_id}: {exc}")
            raise HTTPException(status_code=500, detail="alarm video is not browser compatible") from exc
        return FileResponse(compatible_path, media_type="video/mp4")
    finally:
        session.close()


@router.get("/statistics/summary")
def alarm_statistics(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    now = dt.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    range_start = today_start - dt.timedelta(days=days - 1)

    session = get_session()
    try:
        cameras = _camera_names(session)
        rows = (
            session.query(AiViolationImage)
            .filter(AiViolationImage.create_time >= range_start)
            .order_by(AiViolationImage.create_time.asc())
            .all()
        )

        total = len(rows)
        today = sum(1 for row in rows if row.create_time and row.create_time >= today_start)
        type_counts = Counter(int(row.violation_type or 0) for row in rows)
        subject_counts: Counter[str] = Counter()
        subject_names: dict[str, str] = {}
        for row in rows:
            event = _event_dict(row, cameras)
            subject_key = event["camera_no"] or "unknown"
            subject_counts[subject_key] += 1
            subject_names[subject_key] = event["camera_name"] or subject_key
        hourly_counts = Counter(row.create_time.hour for row in rows if row.create_time)
        daily_by_type: dict[str, Counter[int]] = defaultdict(Counter)
        hourly_by_type: dict[int, Counter[int]] = defaultdict(Counter)

        for row in rows:
            if not row.create_time:
                continue
            day_key = row.create_time.strftime("%m-%d")
            violation_type = int(row.violation_type or 0)
            daily_by_type[day_key][violation_type] += 1
            hourly_by_type[row.create_time.hour][violation_type] += 1

        daily = []
        for offset in range(days):
            day = range_start + dt.timedelta(days=offset)
            key = day.strftime("%m-%d")
            bucket = daily_by_type.get(key, Counter())
            daily.append({
                "day": key,
                "total": sum(bucket.values()),
                **{_meta(vtype)["event_type"]: count for vtype, count in bucket.items()},
            })

        hourly = []
        for hour in range(24):
            bucket = hourly_by_type.get(hour, Counter())
            hourly.append({
                "time": f"{hour:02d}:00",
                "total": sum(bucket.values()),
                **{_meta(vtype)["event_type"]: count for vtype, count in bucket.items()},
            })

        by_type = [
            {
                "event_type": meta["event_type"],
                "name": meta["label"],
                "value": type_counts.get(vtype, 0),
                "color": meta["color"],
            }
            for vtype, meta in _TYPE_META.items()
            if type_counts.get(vtype, 0) > 0
        ]

        by_camera = [
            {
                "camera_no": camera_no,
                "name": subject_names.get(camera_no, camera_no),
                "value": value,
            }
            for camera_no, value in subject_counts.most_common(8)
        ]

        peak_hour = hourly_counts.most_common(1)[0][0] if hourly_counts else None
        return {
            "summary": {
                "total": total,
                "today": today,
                "week": total,
                "avg_per_day": round(total / days, 2),
                "active_cameras": len(subject_counts),
                "peak_hour": f"{peak_hour:02d}:00" if peak_hour is not None else "-",
            },
            "by_type": by_type,
            "by_camera": by_camera,
            "daily": daily,
            "hourly": hourly,
            "recent": [_event_dict(row, cameras) for row in rows[-8:]][::-1],
        }
    finally:
        session.close()
