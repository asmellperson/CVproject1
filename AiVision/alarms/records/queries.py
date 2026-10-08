"""报警权限、列表和统计的数据库查询；不依赖内部 HTTP 服务。"""
import datetime as dt
from collections import Counter, defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_

from auth.alarm_permissions import allowed_alarm_event_types
from AiVision.departments.department_registry import DEPARTMENT_SPECS, require_department
from AiVision.features.registry import get_spec
from AiVision.alarms.types import DEFAULT_ALARM_TYPE_META, VIOLATION_TYPE_META
from .orm import AiAlarmEvent, AiAlarmDisposition

_TYPE_META = VIOLATION_TYPE_META
_DEFAULT_META = DEFAULT_ALARM_TYPE_META
_MAX_CAMERA_ID = 2**31 - 1


def _meta(violation_type: int | None) -> dict[str, str]:
    """根据数据库正式编号查告警名称。"""
    return _TYPE_META.get(violation_type, _DEFAULT_META)

def _dict_value(value: object) -> dict[str, Any]:
    """确保某个metadata字段一定是字典，而且key一定转成字符串"""
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}

def _int_list(value: object) -> list[int]:
    """把metadata里的摄像头ID列表清洗成合法、去重的整数列表"""
    # 1、必须是list
    if not isinstance(value, list):
        return []
    result: list[int] = []
    seen: set[int] = set()                   # 去重
    # 遍历列表
    for item in value:
        if isinstance(item, bool):           # 排除bool
            continue
        if isinstance(item, int):            # 本来是int直接用
            camera_id = item
        elif isinstance(item, str):
            normalized = item.strip()        # 去空格
            # 只接受纯数字
            if not normalized or any(char not in "0123456789" for char in normalized):
                continue
            try:
                camera_id = int(normalized)          #转成整数
            except (ValueError, OverflowError):
                continue
        else:
            continue
        # 合法且不能重复
        if not 1 <= camera_id <= _MAX_CAMERA_ID or camera_id in seen:
            continue
        seen.add(camera_id)
        result.append(camera_id)
    return result

def _channel_alarm_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    """从通道告警的metadata中，把多摄像头相关字段整理出来"""
    # 取摄像头的参数，并保证是字典
    raw_states = _dict_value(metadata.get("camera_states"))
    # 只保留value本身也是字典的数据
    camera_states = {
        key: dict(value)
        for key, value in raw_states.items()
        if isinstance(value, dict)
    }

    raw_counts = _dict_value(metadata.get("camera_counts"))
    camera_counts: dict[str, int | None] = {}
    # 只接受None或者>=0的整数
    for key, value in raw_counts.items():
        if value is None:
            camera_counts[key] = None
        elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            camera_counts[key] = value

    # 处理摄像头名称，并统一转成字符串
    explicit_names = _dict_value(metadata.get("camera_names"))
    camera_names = {
        key: str(value)
        for key, value in explicit_names.items()
        if value is not None
    }
    for key, state in camera_states.items():
        if state.get("camera_name") is not None:
            # 如果camera_states有的摄像头名称而camera_names没有就补进去，有就不补
            camera_names.setdefault(key, str(state["camera_name"]))
    evidence_error = metadata.get("evidence_error")
    # 整理成统一格式返回
    return {
        "camera_ids": _int_list(metadata.get("camera_ids")),
        "camera_names": camera_names,
        "camera_counts": camera_counts,
        "camera_states": camera_states,
        "offending_camera_ids": _int_list(metadata.get("offending_camera_ids")),
        "evidence_error": str(evidence_error) if evidence_error is not None else None,
    }

def event_dict(row: AiAlarmEvent) -> dict[str, Any]:
    """把数据库告警事件转换成以 subject 为主语义的接口记录。"""
    violation_type = row.violation_type
    meta = _meta(violation_type)
    raw_metadata = row.event_metadata
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    subject_type = row.subject_type
    subject_id = row.subject_id
    subject_name = row.subject_name
    persisted_reason = row.reason
    raw_camera_no = row.camera_no
    is_channel = subject_type == "logistics_channel"

    feature_name = row.feature_name
    department = row.department

    camera_no = (raw_camera_no or None) if not is_channel else None
    camera_name = None
    channel_id = None
    channel_name = None
    if is_channel:
        channel_id_value = subject_id
        channel_id = str(channel_id_value) if channel_id_value is not None else None
        channel_name = str(
            subject_name
            or "物流通道"
        )
        subject_id = channel_id
        subject_name = channel_name
    elif subject_type in ("face_person", "unknown_face"):
        camera_name = metadata["camera_name"]
    else:
        camera_name = str(
            subject_name
            or "未知摄像头"
        )
        subject_name = subject_name if subject_name is not None else camera_name

    display_subject = str(subject_name or "未知主体")
    reason = str(
        persisted_reason
        or f"{meta['label']} - {display_subject}"
    )
    create_time = row.create_time
    created_at = create_time.isoformat(sep=" ") if create_time else None
    return {
        "id": str(row.id),
        "event_type": meta["event_type"],
        "event_label": meta["label"],
        "violation_type": violation_type,
        "feature_name": feature_name,
        "department": department,
        "camera_no": camera_no,
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
        "image_url": f"/api/alarms/{row.id}/image",
        "video_path": row.video_path,
        "video_status": row.video_status,
        "video_url": f"/api/alarms/{row.id}/video" if row.video_status == "ready" else None,
        **_channel_alarm_fields(metadata),
        "metadata": metadata,
    }


def alarm_departments(user: dict, department: str | None = None) -> list[str] | None:
    """None 表示管理员全量范围，普通用户只使用正式事业部授权。"""
    departments = None if user["role"] == "admin" else [
        value for value in user["departments"] if value in DEPARTMENT_SPECS
    ]
    if departments is not None and (user["role"] != "viewer" or not departments):
        raise HTTPException(403, "alarm department permission required")
    if department is not None:
        try:
            require_department(department)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if departments is not None and department not in departments:
            raise HTTPException(403, "alarm department permission required")
        return [department]
    return departments


def alarm_query(session, user: dict, department=None, feature=None, event_types=None):
    """所有权限与事件筛选在分页、计数之前应用。"""
    departments = alarm_departments(user, department)
    query = session.query(AiAlarmEvent)
    if departments is not None:
        query = query.filter(AiAlarmEvent.department.in_(departments))
    allowed = allowed_alarm_event_types(user, departments or ())
    if allowed is not None:
        query = query.filter(AiAlarmEvent.violation_type.in_(
            [number for number, meta in _TYPE_META.items() if meta["event_type"] in allowed]
        ))
    if feature is not None:
        if get_spec(feature) is None:
            raise HTTPException(404, "unknown feature")
        query = query.filter(AiAlarmEvent.feature_name == feature)
    if event_types is not None:
        requested = {value.strip() for value in event_types.split(",") if value.strip()}
        query = query.filter(or_(
            AiAlarmEvent.violation_type.in_(
                [number for number, meta in _TYPE_META.items() if meta["event_type"] in requested]
            ),
            AiAlarmEvent.feature_name.in_(requested),
        ))
    return query


def require_alarm_access(row: AiAlarmEvent, user: dict) -> None:
    """同时核对事业部及事件类型授权，不满足时抛出 403。"""
    departments = alarm_departments(user)
    allowed = allowed_alarm_event_types(user, departments or ())
    if ((departments is not None and row.department not in departments)
            or (allowed is not None and _meta(row.violation_type)["event_type"] not in allowed)):
        raise HTTPException(403, "alarm department permission required")


def alarm_items(session, rows: list[AiAlarmEvent]) -> list[dict]:
    """批量取得处置摘要并合并事件响应，避免逐条查询造成额外数据库开销。"""
    if not rows:
        return []
    dispositions = {row.alarm_id: row for row in session.query(AiAlarmDisposition).filter(
        AiAlarmDisposition.alarm_id.in_([row.id for row in rows])
    ).all()}
    items = []
    for row in rows:
        item = event_dict(row)
        disposition = dispositions.get(row.id)
        item.update(
            disposition_status=disposition.status if disposition is not None else "pending",
            disposition_note=disposition.note if disposition is not None else "",
            disposition_updated_at=disposition.updated_at.isoformat() if disposition is not None else None,
            disposition_updated_by=disposition.updated_by if disposition is not None else None,
        )
        items.append(item)
    return items


def alarm_statistics(session, query, days: int) -> dict:
    """数据库完成分组计数，统计范围不受最近报警列表条数限制。"""
    now = dt.datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - dt.timedelta(days=days - 1)
    query = query.filter(AiAlarmEvent.create_time >= start, AiAlarmEvent.create_time <= now)
    day_column = func.date(AiAlarmEvent.create_time)
    hour_column = func.hour(AiAlarmEvent.create_time)
    type_column = AiAlarmEvent.violation_type
    daily_counts = defaultdict(Counter)
    hourly_counts = defaultdict(Counter)
    type_counts = Counter()
    for day, kind, count in query.with_entities(day_column, type_column, func.count()).group_by(day_column, type_column):
        key = str(day)
        daily_counts[key][kind] = count
        type_counts[kind] += count
    for hour, kind, count in query.with_entities(hour_column, type_column, func.count()).group_by(hour_column, type_column):
        hourly_counts[hour][kind] = count
    subjects = query.with_entities(
        AiAlarmEvent.subject_type, AiAlarmEvent.subject_id,
        func.max(AiAlarmEvent.subject_name).label("subject_name"), func.count().label("count"),
    ).group_by(AiAlarmEvent.subject_type, AiAlarmEvent.subject_id)
    subject_count = subjects.count()
    by_subject = [{
        "subject_type": kind, "subject_id": subject_id, "subject_name": name, "value": count,
    } for kind, subject_id, name, count in subjects.order_by(
        func.count().desc(), AiAlarmEvent.subject_type, AiAlarmEvent.subject_id,
    ).limit(8)]

    def bucket(label, value, counts):
        """把数据库按告警类型的计数转换为总数及正式事件标识分项。"""
        return {label: value, "total": sum(counts.values()), **{
            _meta(kind)["event_type"]: count for kind, count in counts.items()
        }}

    daily = [bucket("day", day.strftime("%m-%d"), daily_counts[day.strftime("%Y-%m-%d")])
             for day in (start + dt.timedelta(days=offset) for offset in range(days))]
    hourly = [bucket("time", f"{hour:02d}:00", hourly_counts[hour]) for hour in range(24)]
    total = sum(type_counts.values())
    peak = max(hourly, key=lambda item: item["total"])["time"] if total else "-"
    recent = query.order_by(AiAlarmEvent.create_time.desc(), AiAlarmEvent.id.desc()).limit(8).all()
    return {
        "summary": {
            "total": total, "today": daily[-1]["total"], "avg_per_day": round(total / days, 2),
            "active_subjects": subject_count, "peak_hour": peak,
        },
        "by_type": [{"event_type": _meta(kind)["event_type"], "name": _meta(kind)["label"], "value": count}
                    for kind, count in sorted(type_counts.items())],
        "by_subject": by_subject, "daily": daily, "hourly": hourly, "recent": alarm_items(session, recent),
    }
