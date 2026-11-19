"""非法闯闸状态和报警查询，调用方校验事业部功能与资源归属。"""
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
import time

from AiVision.alarms.records.orm import AiAlarmEvent
from AiVision.core.db import get_session
from .schema import ALARM_TYPE, FEATURE, STATUS_STALE_SECONDS, TailgatingAlarm, TailgatingHistory, TailgatingStatus


def camera_status(camera: dict, orchestrator, *, mark_sample: Callable[[], None] | None = None) -> TailgatingStatus:
    key = camera["shm_name"]
    online = bool(orchestrator and orchestrator.camera_runtime_manager.is_running(key))
    status = TailgatingStatus(camera_key=key, camera_name=camera["name"], department=camera["department"],
                             online=online, state="waiting", reason="waiting")
    if not camera["enabled"] or not camera["functions"].get(FEATURE):
        return status.model_copy(update={"state": "disabled", "reason": "disabled"})
    if not online:
        return status.model_copy(update={"state": "offline" if orchestrator else "waiting", "reason": "offline" if orchestrator else "waiting"})
    consumer = orchestrator.consumers.get(FEATURE)
    detail = consumer.get_monitor_status(key) if consumer else None
    if detail is None:
        return status
    if mark_sample is not None:
        mark_sample()
    age = time.time() - detail["updated_at_s"]
    if not 0 <= age <= STATUS_STALE_SECONDS:
        return status.model_copy(update={"state": "stale", "reason": "stale"})
    return TailgatingStatus.model_validate({**status.model_dump(),
        "state": "error" if detail["error"] else "waiting" if detail["reason"] == "unconfigured" else "ready",
        "reason": detail["reason"], "count": detail["count"], "alarm": detail["alarm"],
        "persons": detail["persons"], "events": detail["events"], "error": detail["error"],
        "sample_interval_seconds": detail["sample_interval_seconds"],
        "updated_at": datetime.fromtimestamp(detail["updated_at_s"], timezone.utc).isoformat(),
        # 返回剩余时长，避免浏览器与服务器时钟偏差导致有效结果反复被清空。
        "valid_for_seconds": STATUS_STALE_SECONDS - age,
    })


def _query(session, department: str):
    """列表、详情和图片共用报警身份过滤，避免按 ID 读到其他业务记录。"""
    return session.query(AiAlarmEvent).filter_by(
        feature_name=FEATURE, violation_type=ALARM_TYPE, department=department,
    )


def _alarm(row: AiAlarmEvent) -> TailgatingAlarm:
    metadata = row.event_metadata or {}
    return TailgatingAlarm(
        id=str(row.id), camera_key=row.camera_no, camera_name=row.subject_name or row.camera_no or "",
        department=row.department, reason=row.reason or "", created_at=row.create_time.astimezone().isoformat(),
        tailgating=metadata.get("tailgating"),
        image_url=f"/api/external/tailgating/alarms/{row.id}/image?department={row.department}" if row.image_path else None,
    )


def history(
    department: str, *, camera_key: str | None, start: datetime | None, end: datetime | None,
    limit: int, offset: int,
) -> TailgatingHistory:
    if start is not None and end is not None and start >= end:
        raise ValueError("开始时间必须早于结束时间")
    with get_session() as session:
        query = _query(session, department)
        if camera_key is not None:
            query = query.filter_by(camera_no=camera_key)
        # 报警表存储服务器本地时间，带时区的筛选边界需先转换再比较。
        if start is not None:
            query = query.filter(AiAlarmEvent.create_time >= start.astimezone().replace(tzinfo=None))
        if end is not None:
            query = query.filter(AiAlarmEvent.create_time < end.astimezone().replace(tzinfo=None))
        total = query.count()
        rows = query.order_by(AiAlarmEvent.create_time.desc(), AiAlarmEvent.id.desc()).offset(offset).limit(limit)
        return TailgatingHistory(total=total, items=[_alarm(row) for row in rows])


def alarm_detail(department: str, alarm_id: int) -> TailgatingAlarm | None:
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
