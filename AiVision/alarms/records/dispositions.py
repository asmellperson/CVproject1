"""报警处置的持久化与授权分页。"""
from datetime import datetime

from fastapi import HTTPException

from AiVision.core.db import get_session, session_scope
from .orm import AiAlarmDisposition, AiAlarmEvent
from .queries import alarm_query, require_alarm_access
from .schema import AlarmDisposition, DispositionUpdate, DISPOSITION_HISTORY_LIMIT


def disposition_dict(row: AiAlarmDisposition) -> dict:
    """通过正式模型整理处置状态、操作者及历史，并将时间转为 ISO 文本。"""
    return AlarmDisposition(
        alarm_id=str(row.alarm_id), status=row.status, note=row.note,
        updated_at=row.updated_at.isoformat(), updated_by=row.updated_by, history=row.history,
    ).model_dump()


def _query(session, user):
    """普通用户只查询可访问告警的处置，管理员可查看证据过期后的处置历史。"""
    query = session.query(AiAlarmDisposition)
    # 管理员可以查看已过保留期的报警处置；普通用户需核验报警归属快照。
    if user["role"] != "admin":
        visible_ids = alarm_query(session, user).with_entities(AiAlarmEvent.id)
        query = query.filter(AiAlarmDisposition.alarm_id.in_(visible_ids))
    return query


def list_dispositions(user: dict, limit: int, cursor: str | None) -> dict:
    """按告警 ID 升序游标分页，多取一项判断是否还有下一页。"""
    with get_session() as session:
        query = _query(session, user)
        if cursor is not None:
            query = query.filter(AiAlarmDisposition.alarm_id > int(cursor))
        rows = query.order_by(AiAlarmDisposition.alarm_id).limit(limit + 1).all()
        page = rows[:limit]
        return {
            "items": [disposition_dict(row) for row in page],
            "next_cursor": str(page[-1].alarm_id) if len(rows) > limit else None,
        }


def get_disposition(user: dict, alarm_id: str) -> dict:
    """在用户可见范围内查询处置，不存在或不可见时返回 404。"""
    with get_session() as session:
        row = _query(session, user).filter(AiAlarmDisposition.alarm_id == int(alarm_id)).one_or_none()
        if row is None:
            raise HTTPException(404, "alarm disposition not found")
        return disposition_dict(row)


def update_disposition(user: dict, payload: DispositionUpdate) -> dict:
    """先锁告警再锁处置，校验访问权限后追加有界历史并保存当前操作者。

    首次创建与后续更新遵循同一锁顺序，避免并发操作覆盖处置历史。
    """
    with session_scope() as session:
        # 锁定报警主记录，使首次创建和后续更新按同一顺序串行，避免丢失处置历史。
        alarm = session.query(AiAlarmEvent).filter_by(id=int(payload.alarm_id)).with_for_update().one_or_none()
        if alarm is None:
            raise HTTPException(404, "alarm not found")
        require_alarm_access(alarm, user)
        row = session.query(AiAlarmDisposition).filter_by(alarm_id=alarm.id).with_for_update().one_or_none()
        history = []
        if row is not None:
            previous = disposition_dict(row)
            history = [*previous["history"], {key: previous[key] for key in (
                "status", "note", "updated_at", "updated_by",
            )}][-DISPOSITION_HISTORY_LIMIT:]
        else:
            row = AiAlarmDisposition(alarm_id=alarm.id)
            session.add(row)
        row.status = payload.status
        row.note = payload.note.strip()
        row.updated_at = datetime.now().replace(microsecond=0)
        row.updated_by = {"employee_id": user["employee_id"], "name": user["name"]}
        row.history = history
        result = disposition_dict(row)
    return result
