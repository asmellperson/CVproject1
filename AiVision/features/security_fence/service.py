"""平台和外部接口共用的围栏查询服务，调用方负责事业部授权。"""
from datetime import datetime, timezone
from pathlib import Path
import time

from sqlalchemy import func

from AiVision.alarms.records.orm import AiAlarmEvent
from AiVision.core.db import get_session
from AiVision.features._shared.config_manager import feature_config_manager
from AiVision.features.face_recognition.library.service import FaceLibraryService
from .orm import FencePersonAuthorization
from .runtime import current_mode
from .schema import FEATURE, STALE_SECONDS, FenceAlarm, FenceConfig, FenceHistory, FenceStatus


person_library = FaceLibraryService(authorization_model=FencePersonAuthorization)


def camera_status(camera: dict, orchestrator) -> FenceStatus:
    from AiVision.features.registry import get_spec

    payload = feature_config_manager.get_config(get_spec(FEATURE), camera["camera_id"])
    config = FenceConfig.model_validate(payload["config"]) if payload else FenceConfig()
    consumer = orchestrator.consumers.get(FEATURE) if orchestrator is not None else None
    online = bool(orchestrator is not None and camera["shm_name"] in orchestrator.camera_runtime_manager.list_running())
    snapshot = consumer.get_monitor_status(camera["shm_name"]) if consumer is not None else None
    mode = current_mode(config.value, datetime.now(timezone.utc))
    result = FenceStatus(
        camera_id=camera["camera_id"], camera_key=camera["shm_name"], camera_name=camera["name"],
        department=camera["department"], online=online, state="waiting", mode=mode, timezone=config.value.timezone,
    )
    if not camera["enabled"] or not config.enable:
        result.state = "disabled"
    elif consumer is None or not consumer.running:
        result.error = "围栏检测尚未运行"
    elif not online:
        result.state = "offline"
    elif snapshot is not None:
        result.updated_at = datetime.fromtimestamp(snapshot["updated_at_s"], timezone.utc).isoformat()
        if time.time() - snapshot["updated_at_s"] > STALE_SECONDS or snapshot["mode"] != mode:
            result.state = "stale"
        else:
            result.state = "error" if snapshot["error"] else "ready"
            for field in ("count", "pending_count", "alarm", "persons", "frame_width", "frame_height", "error"):
                setattr(result, field, snapshot[field])
            if snapshot["error"] and not result.alarm:
                result.alarm = None
    return FenceStatus.model_validate(result.model_dump())


def _query(session, department: str):
    return session.query(AiAlarmEvent).filter_by(feature_name=FEATURE, department=department)


def _alarm(row) -> FenceAlarm:
    metadata = row.event_metadata or {}
    return FenceAlarm(
        id=str(row.id), camera_key=row.camera_no, camera_name=metadata.get("camera_name", row.subject_name or ""),
        department=row.department, reason=row.reason or "", created_at=row.create_time.astimezone().isoformat(),
        person=metadata.get("person"),
        image_url=f"/api/external/security-fence/alarms/{row.id}/image?department={row.department}" if row.image_path else None,
    )


def history(department: str, *, camera_key: str | None, start: datetime | None, end: datetime | None, limit: int, offset: int) -> FenceHistory:
    if start is not None and end is not None and start >= end:
        raise ValueError("开始时间必须早于结束时间")
    with get_session() as session:
        query = _query(session, department)
        if camera_key is not None:
            query = query.filter_by(camera_no=camera_key)
        # 既有报警表按服务器本地时间存储，入口要求带时区并在查询边界统一转换。
        if start is not None:
            query = query.filter(AiAlarmEvent.create_time >= start.astimezone().replace(tzinfo=None))
        if end is not None:
            query = query.filter(AiAlarmEvent.create_time < end.astimezone().replace(tzinfo=None))
        counts = dict(query.with_entities(AiAlarmEvent.reason, func.count()).group_by(AiAlarmEvent.reason).all())
        rows = query.order_by(AiAlarmEvent.create_time.desc(), AiAlarmEvent.id.desc()).offset(offset).limit(limit)
        return FenceHistory(total=sum(counts.values()), by_reason={reason or "": count for reason, count in counts.items()}, items=[_alarm(row) for row in rows])


def alarm_detail(department: str, alarm_id: int) -> FenceAlarm | None:
    with get_session() as session:
        row = _query(session, department).filter_by(id=alarm_id).first()
        return _alarm(row) if row else None


def alarm_image(department: str, alarm_id: int) -> Path | None:
    with get_session() as session:
        row = _query(session, department).filter_by(id=alarm_id).first()
        if row and row.image_path:
            path = Path(row.image_path)
            return path if path.is_file() else None
    return None
