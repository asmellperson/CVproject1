from datetime import datetime, timedelta, timezone

from auth import auth
from auth.access_audit import AccessAuditStore


def test_retention_and_account_deletion_preserve_recent_history(auth_database):
    audit = AccessAuditStore(auth_database)
    users = {}
    for employee_id in ("admin", "expired", "recent"):
        users[employee_id] = auth.create_auth_user(
            employee_id=employee_id,
            name=employee_id,
            role="admin" if employee_id == "admin" else "viewer",
            departments=["all"] if employee_id == "admin" else ["general_electric"],
            password="test-password",
        )
    now = datetime.now(timezone.utc)
    first = now - timedelta(days=1)
    audit.record_visit(users["expired"], visited_at=now - timedelta(days=91))
    audit.record_visit(users["recent"], visited_at=first)
    audit.record_visit(users["recent"], visited_at=now)
    auth.delete_auth_user("recent", actor_employee_id="admin")
    rows = audit.list_recent()
    assert len(rows) == 1
    assert rows[0]["employee_id"] == "recent"
    assert rows[0]["visit_count"] == 2
    assert rows[0]["first_seen_at"] == first.isoformat().replace("+00:00", "Z")
    assert rows[0]["last_seen_at"] == now.isoformat().replace("+00:00", "Z")


def test_expired_account_visit_starts_a_new_retention_window(auth_database):
    audit = AccessAuditStore(auth_database)
    user = auth.create_auth_user(
        employee_id="viewer",
        name="普通用户",
        role="viewer",
        departments=["general_electric"],
        password="test-password",
    )
    now = datetime.now(timezone.utc)
    audit.record_visit(user, visited_at=now - timedelta(days=91))
    audit.record_visit(user, visited_at=now)
    row = audit.list_recent()[0]
    assert (
        row["first_seen_at"]
        == row["last_seen_at"]
        == now.isoformat().replace("+00:00", "Z")
    )
    assert row["visit_count"] == 1
