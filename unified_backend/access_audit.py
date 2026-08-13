"""Privacy-minimal access audit storage for the unified visual platform."""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, status

from auth.auth import get_current_user


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
    """Keep one aggregated, privacy-minimal access record per account."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self._initialize_lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS access_viewers (
                        employee_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        role TEXT NOT NULL,
                        department TEXT,
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        visit_count INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_access_viewers_last_seen
                    ON access_viewers(last_seen_at DESC)
                    """
                )
                connection.commit()
                self._initialized = True
            finally:
                connection.close()

    def record_visit(
        self,
        user: dict[str, Any],
        *,
        visited_at: datetime | None = None,
    ) -> None:
        employee_id = str(user.get("employee_id", "")).strip()
        name = str(user.get("name", "")).strip()
        if not employee_id or not name:
            raise ValueError("access audit requires employee_id and name")

        self.initialize()
        visit_time = visited_at or datetime.now(timezone.utc)
        if visit_time.tzinfo is None:
            visit_time = visit_time.replace(tzinfo=timezone.utc)
        visit_time = visit_time.astimezone(timezone.utc)
        timestamp = visit_time.isoformat().replace("+00:00", "Z")
        connection = self._connect()
        try:
            self._delete_expired(connection, visit_time)
            connection.execute(
                """
                INSERT INTO access_viewers (
                    employee_id,
                    name,
                    role,
                    department,
                    first_seen_at,
                    last_seen_at,
                    visit_count
                ) VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(employee_id) DO UPDATE SET
                    name = excluded.name,
                    role = excluded.role,
                    department = excluded.department,
                    last_seen_at = excluded.last_seen_at,
                    visit_count = access_viewers.visit_count + 1
                """,
                (
                    employee_id,
                    name,
                    str(user.get("role", "")).strip(),
                    str(user.get("department", "")).strip() or None,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def list_recent(self, limit: int = DEFAULT_ACCESS_AUDIT_LIMIT) -> list[dict[str, Any]]:
        self.initialize()
        normalized_limit = max(1, min(int(limit), MAX_ACCESS_AUDIT_LIMIT))
        connection = self._connect()
        try:
            self._delete_expired(connection, datetime.now(timezone.utc))
            rows = connection.execute(
                """
                SELECT
                    employee_id,
                    name,
                    role,
                    department,
                    first_seen_at,
                    last_seen_at,
                    visit_count
                FROM access_viewers
                ORDER BY last_seen_at DESC, employee_id ASC
                LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()
            connection.commit()
        finally:
            connection.close()
        return [dict(row) for row in rows]

    @staticmethod
    def _delete_expired(
        connection: sqlite3.Connection,
        reference_time: datetime,
    ) -> None:
        cutoff = reference_time - timedelta(days=get_access_audit_retention_days())
        cutoff_value = cutoff.astimezone(timezone.utc).isoformat().replace(
            "+00:00",
            "Z",
        )
        connection.execute(
            "DELETE FROM access_viewers WHERE last_seen_at < ?",
            (cutoff_value,),
        )
