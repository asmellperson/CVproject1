"""安检图片原子保存、31 天留存、权限隔离与媒体清理的回归验证。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import threading

import cv2
import numpy as np
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def store(monkeypatch, tmp_path):
    """使用临时目录和启用外键的内存数据库，绝不连接现场数据库。"""
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "test",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path), "ALARM_MEDIA_RETENTION_DAYS": "31",
    }.items():
        monkeypatch.setenv(key, value)
    from AiVision.features.security_inspection import service
    from AiVision.features.security_inspection.orm import InspectionSession, InspectionSessionImage
    from AiVision.cameras.orm import AiCameraConfig

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        """开启外键以验证事务顺序及级联约束。"""
        connection.execute("PRAGMA foreign_keys=ON")

    for model in (AiCameraConfig, InspectionSession, InspectionSessionImage):
        model.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(service, "get_session", factory)
    monkeypatch.setattr(service, "session_scope", factory.begin)
    monkeypatch.setattr(service.settings.storage, "alarm_media_retention_days", 31)
    now = datetime(2026, 10, 12, 12)
    real_cutoff = service.InspectionService.retention_cutoff
    monkeypatch.setattr(service.InspectionService, "retention_cutoff", staticmethod(
        lambda instant=None: real_cutoff(instant or now),
    ))
    yield SimpleNamespace(service=service.InspectionService(), factory=factory, engine=engine, now=now,
                          Session=InspectionSession, Image=InspectionSessionImage, module=service)
    engine.dispose()


def task(store, name="session", *, age=timedelta(), department="general_electric"):
    """构造时长固定的判定任务，覆盖被删除摄像头仍保留会话的情况。"""
    start = store.now - age
    return SimpleNamespace(session_id=name, camera_id=1, camera_name="安检入口", camera_key="inspection",
                           department=department, roi_name="工位一", start_ts=start.timestamp(),
                           end_ts=(start + timedelta(seconds=12)).timestamp(), generation=0, frames=[])


def jpeg():
    """生成可真实解码的测试图片，避免只验证任意字节能够落库。"""
    from AiVision.features.security_inspection.evidence import encode_evidence_image
    return encode_evidence_image(np.full((32, 48, 3), 120, dtype=np.uint8))


def verdict():
    """提供正式契约的不合规判定。"""
    from AiVision.features.security_inspection.schema import InspectionVerdict
    return InspectionVerdict(compliant=False, confidence=0.95, reason="安检动作未完成")


def test_non_compliant_image_and_session_commit_together(store):
    data = jpeg()
    store.service.record(task(store), "non_compliant", verdict(), image_data=data)
    history = store.service.history("general_electric", camera_id=None, limit=10, offset=0)
    assert history["retention_days"] == 31
    assert history["items"][0]["has_image"] is True
    assert history["items"][0]["duration_sec"] == 12
    assert store.service.image("general_electric", "session") == (data, "image/jpeg")
    assert store.service.image("research_institute", "session") is None
    assert cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape == (32, 48, 3)


def test_missing_image_rejected_and_image_insert_failure_rolls_back(store):
    with pytest.raises(ValueError, match="证据图片"):
        store.service.record(task(store, "missing"), "non_compliant", verdict())
    with store.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_image BEFORE INSERT ON ai_security_inspection_session_image "
            "BEGIN SELECT RAISE(ABORT, 'image storage unavailable'); END"
        )
    with pytest.raises(Exception, match="image storage unavailable"):
        store.service.record(task(store, "failure"), "non_compliant", verdict(), image_data=jpeg())
    with store.factory() as session:
        assert session.query(store.Session).count() == session.query(store.Image).count() == 0


def test_history_and_statistics_share_window_and_cleanup_all_statuses(store):
    states = ("compliant", "non_compliant", "error", "cancelled")
    for status in states:
        kwargs = {"image_data": jpeg()} if status == "non_compliant" else {}
        store.service.record(task(store, f"old-{status}", age=timedelta(days=31, seconds=1)), status, **kwargs)
        store.service.record(task(store, f"boundary-{status}", age=timedelta(days=31)), status, **kwargs)
    store.service.record(task(store, "another-department", department="research_institute"), "compliant")
    page = store.service.history("general_electric", camera_id=None, limit=1, offset=1)
    assert page["stats"] == {"total": 4, "compliant": 1, "non_compliant": 1, "error": 1, "cancelled": 1, "rate": 50.0}
    assert len(page["items"]) == 1
    assert store.service.image("general_electric", "old-non_compliant") is None
    assert store.service.image("general_electric", "boundary-non_compliant") is not None
    assert store.service.cleanup_history() == 4
    assert store.service.cleanup_history() == 0
    with store.factory() as session:
        assert session.query(store.Session).count() == 5
        assert session.query(store.Image).count() == 1


def test_cleanup_multiple_batches_without_loading_images(store, monkeypatch):
    monkeypatch.setattr(store.module, "CLEANUP_BATCH_SIZE", 2)
    for index in range(5):
        store.service.record(task(store, str(index), age=timedelta(days=32)), "non_compliant", image_data=jpeg())
    statements = []

    @event.listens_for(store.engine, "before_cursor_execute")
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        """确认分页和清理只读取标识，不把 BLOB 全量加载到内存。"""
        if statement.startswith("SELECT"):
            statements.append(statement)

    assert store.service.cleanup_history() == 5
    assert all("image_data" not in statement for statement in statements)


def test_consumer_stores_evidence_before_suppressed_alarm(store):
    from AiVision.features.security_inspection.consumer import InspectionConsumer

    consumer = object.__new__(InspectionConsumer)
    consumer._camera_state_lock = threading.RLock()
    consumer.config_cache = {1: {"shm_name": "inspection", "sql_enable": False, "alarm_interval": 86400}}
    consumer._task_is_current = Mock(return_value=True)
    consumer._handle_alarm = Mock(return_value=False)
    consumer.service = store.service
    for name in ("first", "during-cooldown"):
        current = task(store, name)
        current.frames = [jpeg(), jpeg()]
        consumer._complete(current, verdict(), None, 1.0)
        assert store.service.image("general_electric", name) is not None
    assert consumer._handle_alarm.call_count == 2


def test_all_registered_media_directories_and_capacity_do_not_shorten_retention(store, tmp_path):
    from AiVision.alarms.records.cleanup import ALARM_MEDIA_DIRECTORIES
    from AiVision.alarms.types import VIOLATION_TYPE_META
    from AiVision.core.media_cleanup import MediaCleaner, MediaRecord

    assert {str(value) for value in VIOLATION_TYPE_META} <= set(ALARM_MEDIA_DIRECTORIES)
    current = tmp_path / "12" / "current.jpg"
    old = tmp_path / "16" / "old.jpg"
    boundary = tmp_path / "11" / "boundary.jpg"
    for path in (current, old, boundary):
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(jpeg())
    records = {1: MediaRecord(1, store.now, (str(current),)),
               2: MediaRecord(2, store.now - timedelta(days=32), (str(old),)),
               3: MediaRecord(3, store.now - timedelta(days=31), (str(boundary),))}
    deleted = []

    def delete_record(record, remove_file):
        """模拟业务先删文件再删记录的正式契约。"""
        if all(remove_file(path) for path in record.paths):
            deleted.append(record.id)
            return 1
        return 0

    references = SimpleNamespace(media_directories=ALARM_MEDIA_DIRECTORIES,
                                 iter_records=lambda before: [r for r in records.values() if r.created_at < before],
                                 referenced_paths=lambda paths: {str(p) for p in paths}, delete_record=delete_record)
    cleaner = MediaCleaner(tmp_path, retention_days=31, max_bytes=1, references=(references,))
    stats = cleaner.cleanup(store.now)
    assert deleted == [2] and stats.removed_records == 1
    assert current.exists() and boundary.exists() and not old.exists()
    outside = tmp_path / "unrelated" / "user.jpg"
    outside.parent.mkdir()
    outside.write_bytes(jpeg())
    assert not cleaner._remove_file(outside, stats, ALARM_MEDIA_DIRECTORIES)
    assert outside.exists()


def test_image_routes_retain_department_authorization(store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth.auth import get_current_user
    from auth.external import inspection_reader
    from AiVision.api.deps import get_department_service, get_inspection_service
    from AiVision.api.routes.security_inspection import router
    from AiVision.api.routes.external.security_inspection import router as external_router

    store.service.record(task(store), "non_compliant", image_data=jpeg())
    app = FastAPI()
    app.include_router(router)
    app.include_router(external_router, prefix="/api/external")
    app.dependency_overrides[get_inspection_service] = lambda: store.service
    app.dependency_overrides[get_current_user] = lambda: {
        "role": "viewer", "departments": ["general_electric"],
        "feature_access": {"general_electric": ["security_inspection"]},
    }
    app.dependency_overrides[inspection_reader] = lambda: SimpleNamespace(departments=["general_electric"])
    app.dependency_overrides[get_department_service] = lambda: SimpleNamespace(
        feature_access=lambda: {"general_electric": ["security_inspection"], "research_institute": ["security_inspection"]},
    )
    client = TestClient(app)
    for prefix in ("/api/security-inspection", "/api/external/security-inspection"):
        response = client.get(f"{prefix}/history/session/image.jpg?department=general_electric")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "no-store"
        assert client.get(f"{prefix}/history/session/image.jpg?department=research_institute").status_code == 403
        assert client.get(f"{prefix}/history/missing/image.jpg?department=general_electric").status_code == 404


def test_migration_adds_index_and_backfills_available_images(store, tmp_path):
    from AiVision.alarms.records.orm import AiAlarmEvent
    from AiVision.migrations.security_inspection_retention_20261012 import apply, check

    # 报警表只需迁移查询所需列，避免 SQLite 的 BIGINT 自增方言差异。
    with store.engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE ai_violation_image (id INTEGER PRIMARY KEY, image_path TEXT, "
                                   "violation_type INTEGER, feature_name TEXT, department TEXT, event_metadata JSON)")
    with store.factory.begin() as session:
        for name in ("available", "missing"):
            current = task(store, name)
            session.add(store.Session(session_id=name, camera_name=current.camera_name, department=current.department,
                                      roi_name=current.roi_name, started_at=store.now, ended_at=store.now,
                                      status="non_compliant"))
    path = tmp_path / "12" / "saved.png"
    path.parent.mkdir()
    path.write_bytes(jpeg())
    with store.engine.begin() as connection:
        for number, name in enumerate(("available", "missing"), start=1):
            connection.execute(AiAlarmEvent.__table__.insert().values(
                id=number, image_path=str(path if name == "available" else tmp_path / "12" / "gone.png"),
                violation_type=12, feature_name="security_inspection", department="general_electric",
                event_metadata={"session_id": name},
            ))
        store.Image.__table__.drop(connection)
        connection.execute(text("DROP INDEX ix_inspection_started_at"))
    assert check(store.engine)["needs_time_index"] is True
    result = apply(store.engine, tmp_path)
    assert result["copied"] == 1 and result["recent_sessions_without_image"] == 1
    assert result["needs_time_index"] is result["needs_image_table"] is False
    assert apply(store.engine, tmp_path)["copied"] == 0
    with store.engine.connect() as connection:
        assert connection.scalar(select(store.Image.session_id)) == "available"


def test_evidence_rejects_missing_or_corrupt_frames(store):
    from AiVision.features.security_inspection.evidence import build_evidence_image

    for frames in ([], [b"broken"]):
        with pytest.raises(ValueError, match="关键帧"):
            build_evidence_image(frames)
