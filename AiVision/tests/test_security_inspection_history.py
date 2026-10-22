"""安检有效判定的统计口径、失败与取消历史保留和分页回归验证。"""

from datetime import datetime, timedelta
from importlib import import_module
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def history_database(monkeypatch, tmp_path):
    # 查询只连接隔离的内存数据库，不依赖部署环境或修改线上记录。
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "tests", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "tests", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)

    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.core.db import Base
    from AiVision.features.security_inspection import service
    from AiVision.features.security_inspection.orm import InspectionSession, InspectionSessionImage
    from AiVision.features.security_inspection.schema import HistoryResponse

    now = datetime(2026, 10, 21, 12)
    monkeypatch.setattr(service.settings.storage, "alarm_media_retention_days", 31)
    monkeypatch.setattr(service.InspectionService, "retention_cutoff", staticmethod(lambda: now - timedelta(days=31)))
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[
        AiCameraConfig.__table__, InspectionSession.__table__, InspectionSessionImage.__table__,
    ])
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(service, "get_session", factory)
    with factory.begin() as session:
        for camera_id in (1, 2):
            session.add(AiCameraConfig(
                id=camera_id, name=f"摄像头{camera_id}", shm_name=f"camera_{camera_id}",
                url=f"test://camera/{camera_id}", department="general_electric",
            ))

    def add_record(session_id, status, *, camera_id=1, department="general_electric", started_at=None):
        start = started_at or now
        verdict = {"compliant": status == "compliant", "confidence": 0.9, "reason": "实际判定"}
        with factory.begin() as session:
            session.add(InspectionSession(
                session_id=session_id, camera_id=camera_id, camera_name=f"摄像头{camera_id}",
                department=department, roi_name="security_staff_1", started_at=start,
                ended_at=start + timedelta(seconds=10), status=status,
                verdict=verdict if status in ("compliant", "non_compliant") else None,
                error="摄像头状态或检测配置已变更" if status == "cancelled" else
                "福达AI请求超时" if status == "error" else None,
            ))
            if status == "non_compliant":
                session.flush()
                session.add(InspectionSessionImage(
                    session_id=session_id, image_data=b"evidence", media_type="image/jpeg",
                ))

    yield SimpleNamespace(
        service=service.InspectionService(), add=add_record, factory=factory, now=now,
        record=InspectionSession, response=HistoryResponse,
    )
    engine.dispose()


@pytest.mark.parametrize("entrypoint", ["service", "platform", "external"])
def test_only_completed_verdicts_count_towards_total_without_losing_history(history_database, entrypoint):
    database = history_database
    for session_id, status in (
        ("good-1", "compliant"), ("good-2", "compliant"), ("bad", "non_compliant"),
        ("failed", "error"), ("roi-change", "cancelled"),
    ):
        database.add(session_id, status)

    query = {"department": "general_electric", "camera_id": None, "limit": 10, "offset": 0}
    if entrypoint == "service":
        payload = database.service.history(**query)
    else:
        module = "AiVision.api.routes.security_inspection" if entrypoint == "platform" else "AiVision.api.routes.external.security_inspection"
        payload = import_module(module).history(**query, service=database.service)
    result = database.response.model_validate(payload)
    assert result.stats.model_dump() == {
        "total": 3, "compliant": 2, "non_compliant": 1, "error": 1, "cancelled": 1, "rate": 66.7,
    }
    assert result.stats.total == result.stats.compliant + result.stats.non_compliant
    assert len(result.items) == result.stats.total + result.stats.error + result.stats.cancelled == 5
    cancelled = next(item for item in result.items if item.session_id == "roi-change")
    assert cancelled.status == "cancelled"
    assert cancelled.error == "摄像头状态或检测配置已变更"
    assert next(item for item in result.items if item.session_id == "bad").has_image
    with database.factory() as session:
        assert session.query(database.record).count() == 5


@pytest.mark.parametrize("statuses, total, cancelled", [
    ([], 0, 0), (["cancelled", "cancelled"], 0, 2), (["error"], 0, 0), (["error", "cancelled"], 0, 1),
])
def test_no_completed_verdict_keeps_zero_rate_without_hiding_failures(history_database, statuses, total, cancelled):
    database = history_database
    for index, status in enumerate(statuses):
        database.add(str(index), status)

    result = database.service.history("general_electric", camera_id=None, limit=10, offset=0)
    assert result["stats"]["total"] == total
    assert result["stats"]["cancelled"] == cancelled
    assert result["stats"]["error"] == statuses.count("error")
    assert result["stats"]["rate"] == 0.0
    assert len(result["items"]) == len(statuses)


def test_history_pagination_includes_failed_and_cancelled_records_on_every_page(history_database):
    database = history_database
    database.add("good", "compliant")
    database.add("bad", "non_compliant")
    database.add("failed", "error")
    for index in range(3):
        database.add(f"cancelled-{index}", "cancelled")

    results = [database.service.history("general_electric", camera_id=None, limit=2, offset=offset)
               for offset in (0, 2, 4)]
    assert all(result["stats"]["total"] == 2 and result["stats"]["error"] == 1
               and result["stats"]["cancelled"] == 3 for result in results)
    ids = [item["session_id"] for result in results for item in result["items"]]
    assert len(ids) == len(set(ids)) == 6
    assert set(ids) == {"good", "bad", "failed", "cancelled-0", "cancelled-1", "cancelled-2"}


@pytest.mark.parametrize("camera_id, total, non_compliant", [(None, 2, 1), (1, 1, 0)])
def test_stats_and_history_keep_department_camera_and_retention_scope(history_database, camera_id, total, non_compliant):
    database = history_database
    database.add("good", "compliant")
    database.add("cancelled", "cancelled", started_at=database.now - timedelta(days=31))
    database.add("another-camera", "non_compliant", camera_id=2)
    database.add("another-department", "error", department="electrical_components")
    database.add("expired", "compliant", started_at=database.now - timedelta(days=31, seconds=1))
    database.add("expired-cancelled", "cancelled", started_at=database.now - timedelta(days=32))

    result = database.service.history("general_electric", camera_id=camera_id, limit=10, offset=0)
    assert result["stats"]["total"] == total
    assert result["stats"]["non_compliant"] == non_compliant
    assert result["stats"]["error"] == 0
    assert result["stats"]["cancelled"] == 1
    assert len(result["items"]) == total + 1
    assert not {"another-department", "expired", "expired-cancelled"} & {
        item["session_id"] for item in result["items"]
    }
