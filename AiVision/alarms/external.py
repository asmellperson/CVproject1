"""外部报警按数字类型统一查询，功能归属由正式注册表推导。"""
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import and_, or_

from AiVision.core.db import get_session
from .records.orm import AiAlarmEvent
from .records.schema import ExternalAlarmListResponse, ExternalAlarmResponse
from .types import VIOLATION_TYPE_META


# 仅汇总已明确提供免登录报警接入的功能，不扩展其他业务的公开范围。
SUPPORTED_FEATURES = ("detect_human", "security_fence", "tailgating")


def feature_types() -> dict[int, str]:
    """复用正式编号归属，调用方不再维护编号与英文功能名的双重映射。"""
    from AiVision.features.registry import all_specs

    specs = all_specs()
    return {number: feature for feature in SUPPORTED_FEATURES for number in specs[feature].alarm_types}


@dataclass(frozen=True)
class ExternalAlarmScope:
    department: str
    feature_types: dict[int, str]


def _query(session, scope: ExternalAlarmScope, selected: Collection[int] | None = None):
    conditions = [
        and_(AiAlarmEvent.violation_type == number, AiAlarmEvent.feature_name == feature)
        for number, feature in scope.feature_types.items() if selected is None or number in selected
    ]
    # 同时核对持久化归属，历史脏记录不能借用另一个类型的功能分配。
    return session.query(AiAlarmEvent).filter(
        AiAlarmEvent.department == scope.department, or_(False, *conditions),
    )


def _alarm(row: AiAlarmEvent) -> ExternalAlarmResponse:
    meta = VIOLATION_TYPE_META[row.violation_type]
    camera_name = row.subject_name or row.camera_no or ""
    return ExternalAlarmResponse(
        id=str(row.id), feature_name=row.feature_name, violation_type=row.violation_type,
        event_type=meta["event_type"], event_label=meta["label"],
        camera_key=row.camera_no, camera_name=camera_name, department=row.department,
        reason=row.reason or f"{meta['label']} - {camera_name}",
        created_at=row.create_time.astimezone().isoformat(),
        image_url=f"/api/external/alarms/{row.id}/image?department={row.department}" if row.image_path else None,
    )


def history(
    scope: ExternalAlarmScope, *, violation_types: list[int] | None, camera_key: str | None,
    start: datetime | None, end: datetime | None, limit: int, offset: int,
) -> ExternalAlarmListResponse:
    selected = set(violation_types) if violation_types is not None else None
    if selected is not None:
        if selected - feature_types().keys():
            raise ValueError("不支持的报警类型")
        if selected - scope.feature_types.keys():
            raise PermissionError("此事业部未分配对应报警功能")
    if start is not None and end is not None and start >= end:
        raise ValueError("开始时间必须早于结束时间")
    with get_session() as session:
        query = _query(session, scope, selected)
        if camera_key is not None:
            query = query.filter_by(camera_no=camera_key)
        # 与公共报警表一致，将带时区边界转换为服务器本地时间再比较。
        if start is not None:
            query = query.filter(AiAlarmEvent.create_time >= start.astimezone().replace(tzinfo=None))
        if end is not None:
            query = query.filter(AiAlarmEvent.create_time < end.astimezone().replace(tzinfo=None))
        total = query.count()
        rows = query.order_by(AiAlarmEvent.create_time.desc(), AiAlarmEvent.id.desc()).offset(offset).limit(limit)
        return ExternalAlarmListResponse(total=total, items=[_alarm(row) for row in rows])


def alarm_detail(scope: ExternalAlarmScope, alarm_id: int) -> ExternalAlarmResponse | None:
    with get_session() as session:
        row = _query(session, scope).filter_by(id=alarm_id).first()
        return _alarm(row) if row else None


def alarm_image(scope: ExternalAlarmScope, alarm_id: int) -> Path | None:
    with get_session() as session:
        row = _query(session, scope).filter_by(id=alarm_id).first()
        if row and row.image_path:
            path = Path(row.image_path)
            return path if path.is_file() else None
    return None
