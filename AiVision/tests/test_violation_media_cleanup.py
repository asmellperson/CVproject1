import datetime
import importlib
import importlib.util
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATA_PATH", "/tmp/aivision-test-data")
os.environ.setdefault("MYSQL_DB_URL", "127.0.0.1")
os.environ.setdefault("MYSQL_DB_USER", "test")
os.environ.setdefault("MYSQL_DB_PASSWORD", "test")
os.environ.setdefault("MYSQL_DB_NAME", "test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.db import Base

try:
    violation_cleanup = importlib.import_module("platform.violation.cleanup")
    AiViolationImage = importlib.import_module("platform.violation.orm").AiViolationImage
except ModuleNotFoundError:
    # pytest 自身可能已加载标准库 platform；用别名加载项目包，避免名称冲突。
    _PLATFORM_ROOT = Path(__file__).resolve().parents[1] / "platform"
    _PLATFORM_SPEC = importlib.util.spec_from_file_location(
        "aivision_platform",
        _PLATFORM_ROOT / "__init__.py",
        submodule_search_locations=[str(_PLATFORM_ROOT)],
    )
    assert _PLATFORM_SPEC is not None and _PLATFORM_SPEC.loader is not None
    _PLATFORM_MODULE = importlib.util.module_from_spec(_PLATFORM_SPEC)
    sys.modules.setdefault("aivision_platform", _PLATFORM_MODULE)
    _PLATFORM_SPEC.loader.exec_module(_PLATFORM_MODULE)
    violation_cleanup = importlib.import_module("aivision_platform.violation.cleanup")
    AiViolationImage = importlib.import_module(
        "aivision_platform.violation.orm"
    ).AiViolationImage


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def local_session_scope():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return factory, local_session_scope


def _add_record(factory, *, row_id: int, image_path: Path, created_at: datetime.datetime):
    with factory() as session:
        session.add(AiViolationImage(
            id=row_id,
            image_path=str(image_path),
            violation_type=6,
            camera_no="camera-1",
            create_time=created_at,
        ))
        session.commit()


def test_cleanup_deletes_expired_records_files_and_historical_orphans(tmp_path):
    factory, local_session_scope = _database()
    now = datetime.datetime(2026, 8, 10, 12, 0, 0)
    root = tmp_path / "alarm-data"
    old_image = root / "6" / "old.png"
    recent_image = root / "6" / "recent.png"
    orphan = root / "6" / "orphan.png"
    outside = tmp_path / "outside.png"
    for path in (old_image, recent_image, orphan, outside):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
    old_timestamp = (now - datetime.timedelta(days=8)).timestamp()
    os.utime(old_image, (old_timestamp, old_timestamp))
    os.utime(orphan, (old_timestamp, old_timestamp))

    _add_record(factory, row_id=1, image_path=old_image, created_at=now - datetime.timedelta(days=8))
    _add_record(factory, row_id=2, image_path=recent_image, created_at=now - datetime.timedelta(days=1))
    _add_record(factory, row_id=3, image_path=outside, created_at=now - datetime.timedelta(days=8))
    cleaner = violation_cleanup.ViolationMediaCleaner(
        root,
        retention_days=7,
        max_bytes=1024,
        session_scope_factory=local_session_scope,
    )

    stats = cleaner.cleanup(now=now)

    with factory() as session:
        remaining_ids = [row.id for row in session.query(AiViolationImage).order_by(AiViolationImage.id)]
    assert remaining_ids == [2, 3]
    assert not old_image.exists()
    assert not orphan.exists()
    assert recent_image.exists()
    assert outside.exists()
    assert stats.removed_records == 1
    assert stats.removed_files == 2
    assert stats.skipped_unsafe_paths == 1


def test_cleanup_capacity_removes_oldest_database_backed_image(tmp_path):
    factory, local_session_scope = _database()
    now = datetime.datetime(2026, 8, 10, 12, 0, 0)
    root = tmp_path / "alarm-data"
    oldest = root / "6" / "oldest.png"
    newest = root / "6" / "newest.png"
    for path in (oldest, newest):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"12345678")
    _add_record(factory, row_id=1, image_path=oldest, created_at=now - datetime.timedelta(days=2))
    _add_record(factory, row_id=2, image_path=newest, created_at=now - datetime.timedelta(days=1))
    cleaner = violation_cleanup.ViolationMediaCleaner(
        root,
        retention_days=30,
        max_bytes=10,
        session_scope_factory=local_session_scope,
    )

    stats = cleaner.cleanup(now=now)

    with factory() as session:
        remaining_ids = [row.id for row in session.query(AiViolationImage).order_by(AiViolationImage.id)]
    assert remaining_ids == [2]
    assert not oldest.exists()
    assert newest.exists()
    assert stats.removed_records == 1
    assert stats.removed_bytes == 8


def test_cleanup_capacity_keeps_fresh_image_during_push_grace_period(tmp_path):
    factory, local_session_scope = _database()
    now = datetime.datetime(2026, 8, 10, 12, 0, 0)
    root = tmp_path / "alarm-data"
    old_image = root / "6" / "old.png"
    fresh_image = root / "6" / "fresh.png"
    for path in (old_image, fresh_image):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"12345678")
    _add_record(factory, row_id=1, image_path=old_image, created_at=now - datetime.timedelta(days=1))
    _add_record(factory, row_id=2, image_path=fresh_image, created_at=now - datetime.timedelta(seconds=30))
    cleaner = violation_cleanup.ViolationMediaCleaner(
        root,
        retention_days=30,
        max_bytes=1,
        session_scope_factory=local_session_scope,
    )

    cleaner.cleanup(now=now)

    with factory() as session:
        remaining_ids = [row.id for row in session.query(AiViolationImage).order_by(AiViolationImage.id)]
    assert remaining_ids == [2]
    assert not old_image.exists()
    assert fresh_image.exists()
