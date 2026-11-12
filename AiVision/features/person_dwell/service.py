"""人员逗留报警的外部只读查询，调用方负责事业部功能分配校验。"""
from datetime import datetime
from pathlib import Path

from AiVision.alarms.records.orm import AiAlarmEvent
from AiVision.alarms.types import VIOLATION_TYPE_META
from AiVision.core.db import get_session
from .schema import ALARM_TYPE, FEATURE, HumanDwellAlarm, HumanDwellHistory


def _query(session, department: str):
    """列表、详情与图片使用同一归属条件，不能按 ID 读取其他功能证据。"""
    return session.query(AiAlarmEvent).filter_by(
        feature_name=FEATURE, violation_type=ALARM_TYPE, department=department,
    )


def _alarm(row: AiAlarmEvent) -> HumanDwellAlarm:
    meta = VIOLATION_TYPE_META[ALARM_TYPE]
    camera_name = row.subject_name or row.camera_no or ""
    return HumanDwellAlarm(
        id=str(row.id), feature_name=FEATURE, violation_type=ALARM_TYPE,
        event_type=meta["event_type"], event_label=meta["label"],
        camera_key=row.camera_no, camera_name=camera_name, department=row.department,
        # 已有人员报警可能未保存原因，沿用平台展示的正式类型与摄像头说明。
        reason=row.reason or f"{meta['label']} - {camera_name}",
        created_at=row.create_time.astimezone().isoformat(),
        image_url=f"/api/external/human-dwell/alarms/{row.id}/image?department={row.department}" if row.image_path else None,
    )


def history(
    department: str, *, camera_key: str | None, start: datetime | None, end: datetime | None,
    limit: int, offset: int,
) -> HumanDwellHistory:
    if start is not None and end is not None and start >= end:
        raise ValueError("开始时间必须早于结束时间")
    with get_session() as session:
        query = _query(session, department)
        if camera_key is not None:
            query = query.filter_by(camera_no=camera_key)
        # 与公共报警表一致，将带时区边界转换为服务器本地时间再比较。
        if start is not None:
            query = query.filter(AiAlarmEvent.create_time >= start.astimezone().replace(tzinfo=None))
        if end is not None:
            query = query.filter(AiAlarmEvent.create_time < end.astimezone().replace(tzinfo=None))
        total = query.count()
        rows = query.order_by(AiAlarmEvent.create_time.desc(), AiAlarmEvent.id.desc()).offset(offset).limit(limit)
        return HumanDwellHistory(total=total, items=[_alarm(row) for row in rows])


def alarm_detail(department: str, alarm_id: int) -> HumanDwellAlarm | None:
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
