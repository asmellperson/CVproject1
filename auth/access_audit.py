"""Privacy-minimal access audit storage for the unified visual platform."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from AiVision.core.db import get_session
from auth.auth import get_current_user
from auth.orm import AccessViewer, AuthUser, utc_now


DEFAULT_PLATFORM_OWNER_EMPLOYEE_ID = "260210063"
DEFAULT_ACCESS_AUDIT_LIMIT = 100
MAX_ACCESS_AUDIT_LIMIT = 500
DEFAULT_ACCESS_AUDIT_RETENTION_DAYS = 90


def get_platform_owner_employee_id() -> str:
    return os.getenv(
        "PLATFORM_OWNER_EMPLOYEE_ID",
        DEFAULT_PLATFORM_OWNER_EMPLOYEE_ID,
    ).strip()


def get_access_audit_retention_days() -> int:
    raw_value = os.getenv(
        "ACCESS_AUDIT_RETENTION_DAYS",
        str(DEFAULT_ACCESS_AUDIT_RETENTION_DAYS),
    )
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_ACCESS_AUDIT_RETENTION_DAYS


def is_platform_owner(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    employee_id = str(user.get("employee_id", "")).strip()
    owner_employee_id = get_platform_owner_employee_id()
    return bool(employee_id and owner_employee_id and employee_id == owner_employee_id)


def require_access_audit_owner(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not is_platform_owner(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="access audit permission required",
        )
    return user


def add_access_audit_capability(user: dict[str, Any]) -> dict[str, Any]:
    public_user = dict(user)
    public_user["capabilities"] = {
        "view_access_audit": is_platform_owner(user),
    }
    return public_user


class AccessAuditStore:
    """每个账号保留一条聚合访问记录，账号删除不级联删除历史。"""

    def __init__(self, session_factory: Callable[[], Session] = get_session):
        self._session_factory = session_factory

    def record_visit(
        self, user: dict[str, Any], *, visited_at: datetime | None = None
    ) -> None:
        visit_time = visited_at or datetime.now(timezone.utc)
        if visit_time.tzinfo is None:
            visit_time = visit_time.replace(tzinfo=timezone.utc)
        visit_time = visit_time.astimezone(timezone.utc).replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            # 同一账号的首次访问也要串行，防止并发插入冲突或丢失计数。
            account = session.get(AuthUser, user["employee_id"], with_for_update=True)
            if account is None or not account.enabled:
                return
            row = session.get(AccessViewer, account.employee_id)
            if row is None:
                row = AccessViewer(
                    employee_id=account.employee_id,
                    first_seen_at=visit_time,
                    visit_count=0,
                )
                session.add(row)
            elif row.last_seen_at < visit_time - timedelta(
                days=get_access_audit_retention_days()
            ):
                row.first_seen_at = visit_time
                row.visit_count = 0
            row.name = account.name
            row.role = account.role
            row.department = account.departments[0] if account.departments else None
            row.last_seen_at = visit_time
            row.visit_count += 1

    def list_recent(
        self, limit: int = DEFAULT_ACCESS_AUDIT_LIMIT
    ) -> list[dict[str, Any]]:
        with self._session_factory() as session, session.begin():
            self._delete_expired(session, utc_now())
            rows = session.scalars(
                select(AccessViewer)
                .order_by(AccessViewer.last_seen_at.desc(), AccessViewer.employee_id)
                .limit(max(1, min(limit, MAX_ACCESS_AUDIT_LIMIT)))
            )
            return [
                {
                    "employee_id": row.employee_id,
                    "name": row.name,
                    "role": row.role,
                    "department": row.department,
                    "first_seen_at": row.first_seen_at.isoformat() + "Z",
                    "last_seen_at": row.last_seen_at.isoformat() + "Z",
                    "visit_count": row.visit_count,
                }
                for row in rows
            ]

    @staticmethod
    def _delete_expired(session: Session, reference_time: datetime) -> None:
        cutoff = reference_time - timedelta(days=get_access_audit_retention_days())
        session.execute(delete(AccessViewer).where(AccessViewer.last_seen_at < cutoff))


access_audit_store = AccessAuditStore()
