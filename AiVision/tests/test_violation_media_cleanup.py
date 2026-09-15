# 文件说明：包含资源清理的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import datetime
import os
import pytest
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATA_PATH", "/tmp/aivision-test-data")
os.environ.setdefault("MYSQL_DB_URL", "127.0.0.1")
os.environ.setdefault("MYSQL_DB_USER", "test")
os.environ.setdefault("MYSQL_DB_PASSWORD", "test")
os.environ.setdefault("MYSQL_DB_NAME", "test")
from AiVision.alarms.records import cleanup as violation_cleanup
from AiVision.core.media_cleanup import MediaCleanupStats
from AiVision.alarms.records.orm import AiAlarmEvent


# 功能：实现 `_database` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_violation_media_cleanup.py` 的 `test_cleanup_deletes_expired_records_files_and_historical_orphans`
#         调用本符号；`AiVision/tests/test_violation_media_cleanup.py` 的 `test_cleanup_capacity_removes_oldest_database_backed_image`
#         调用本符号；`AiVision/tests/test_violation_media_cleanup.py` 的
#         `test_cleanup_capacity_keeps_fresh_image_during_push_grace_period` 调用本符号
#   - 内部调用：`create_engine`、`AiAlarmEvent.__table__.create`、`sessionmaker`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _database():
    engine = create_engine("sqlite:///:memory:")
    AiAlarmEvent.__table__.create(engine)
    factory = sessionmaker(bind=engine)

    # 功能：实现 `local_session_scope` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`factory`、`session.commit`、`session.rollback`、`session.close`。
    # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
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


# 功能：创建或构建 `_add_record` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `factory`（未显式标注）：`factory` 对应的业务输入值
#   - `row_id`（int）：`row_id` 对应业务对象的唯一标识
#   - `image_path`（Path）：`image_path` 对应的业务输入值
#   - `created_at`（datetime.datetime）：`created_at` 对应的业务输入值
#   - `video_path`（Path | None）：`video_path` 对应的业务输入值；默认值为 `None`
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：`AiVision/tests/test_violation_media_cleanup.py` 的 `test_cleanup_deletes_expired_records_files_and_historical_orphans`
#         调用本符号；`AiVision/tests/test_violation_media_cleanup.py` 的 `test_cleanup_capacity_removes_oldest_database_backed_image`
#         调用本符号；`AiVision/tests/test_violation_media_cleanup.py` 的
#         `test_cleanup_capacity_keeps_fresh_image_during_push_grace_period` 调用本符号
#   - 内部调用：`factory`、`session.add`、`AiAlarmEvent`、`str`、`session.commit`。
# 副作用/注意事项：可能读取或修改数据库事务。
def _add_record(
    factory,
    *,
    row_id: int,
    image_path: Path,
    created_at: datetime.datetime,
    video_path: Path | None = None,
):
    with factory() as session:
        session.add(AiAlarmEvent(
            id=row_id,
            image_path=str(image_path),
            video_path=str(video_path) if video_path else None,
            violation_type=6, feature_name="detect_logistics_single_person", department="general_electric",
            camera_no="camera-1",
            create_time=created_at,
        ))
        session.commit()


# 功能：验证 `test_cleanup_deletes_expired_records_files_and_historical_orphans` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_database`、`datetime.datetime`、`path.parent.mkdir`、`path.write_bytes`、`(now -
#          datetime.timedelta(days=8)).timestamp`、`datetime.timedelta`、`os.utime`、`_add_record`、`violation_cleanup.ViolationMediaCleaner`、`cleaner.cleanup`
#          等共 18 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_cleanup_deletes_expired_records_files_and_historical_orphans(tmp_path):
    factory, local_session_scope = _database()
    now = datetime.datetime(2026, 8, 10, 12, 0, 0)
    root = tmp_path / "alarm-data"
    old_image = root / "6" / "old.png"
    old_video = root / "alarm_clips" / "old.mp4"
    recent_image = root / "6" / "recent.png"
    orphan = root / "6" / "orphan.png"
    outside = tmp_path / "outside.png"
    for path in (old_image, old_video, recent_image, orphan, outside):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
    old_timestamp = (now - datetime.timedelta(days=8)).timestamp()
    os.utime(old_image, (old_timestamp, old_timestamp))
    os.utime(old_video, (old_timestamp, old_timestamp))
    os.utime(orphan, (old_timestamp, old_timestamp))

    _add_record(
        factory,
        row_id=1,
        image_path=old_image,
        video_path=old_video,
        created_at=now - datetime.timedelta(days=8),
    )
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
        remaining_ids = [row.id for row in session.query(AiAlarmEvent).order_by(AiAlarmEvent.id)]
    assert remaining_ids == [2, 3]
    assert not old_image.exists()
    assert not old_video.exists()
    assert not orphan.exists()
    assert recent_image.exists()
    assert outside.exists()
    assert stats.removed_records == 1
    assert stats.removed_files == 3
    assert stats.skipped_unsafe_paths == 1


# 功能：验证 `test_cleanup_capacity_removes_oldest_database_backed_image` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_database`、`datetime.datetime`、`path.parent.mkdir`、`path.write_bytes`、`_add_record`、`datetime.timedelta`、`violation_cleanup.ViolationMediaCleaner`、`cleaner.cleanup`、`factory`、`session.query(AiAlarmEvent).order_by`
#          等共 13 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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
        remaining_ids = [row.id for row in session.query(AiAlarmEvent).order_by(AiAlarmEvent.id)]
    assert remaining_ids == [2]
    assert not oldest.exists()
    assert newest.exists()
    assert stats.removed_records == 1
    assert stats.removed_bytes == 8


# 功能：验证 `test_cleanup_capacity_keeps_fresh_image_during_push_grace_period` 对应的资源清理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_database`、`datetime.datetime`、`path.parent.mkdir`、`path.write_bytes`、`_add_record`、`datetime.timedelta`、`violation_cleanup.ViolationMediaCleaner`、`cleaner.cleanup`、`factory`、`session.query(AiAlarmEvent).order_by`
#          等共 13 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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
        remaining_ids = [row.id for row in session.query(AiAlarmEvent).order_by(AiAlarmEvent.id)]
    assert remaining_ids == [2]
    assert not old_image.exists()
    assert fresh_image.exists()


@pytest.mark.parametrize("max_bytes", [0, 1])
def test_cleanup_never_scans_other_business_media_or_empty_directories(tmp_path, max_bytes):
    factory, scope = _database()
    now = datetime.datetime.now()
    root = tmp_path / "data"
    unrelated = [root / "face_library" / "portrait.png", root / "uploads" / "video.mp4", root / "snapshot.jpg",
                 root / "recognize_face" / "recognition.png"]
    old_alarm = root / "9" / "old.png"
    for path in [*unrelated, old_alarm]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"12345678")
        old = (now - datetime.timedelta(days=8)).timestamp()
        os.utime(path, (old, old))
    empty_business = root / "uploads" / "empty"
    empty_business.mkdir()
    _add_record(factory, row_id=1, image_path=unrelated[0], created_at=now - datetime.timedelta(days=8))
    cleaner = violation_cleanup.ViolationMediaCleaner(root, retention_days=7, max_bytes=max_bytes, session_scope_factory=scope)
    assert cleaner._media_size() == 8
    stats = cleaner.cleanup(now=now)
    assert all(path.is_file() for path in unrelated)
    assert empty_business.is_dir()
    assert not old_alarm.exists()
    assert cleaner._media_size() == 0
    assert stats.skipped_unsafe_paths >= 1
    with factory() as session:
        assert session.query(AiAlarmEvent).count() == 1


def test_cleanup_rejects_symlinks_and_traversal_even_inside_data_path(tmp_path):
    _, scope = _database()
    root = tmp_path / "data"
    media = root / "1"
    media.mkdir(parents=True)
    other = root / "uploads"
    other.mkdir()
    image = other / "portrait.png"
    image.write_bytes(b"portrait")
    linked_file = media / "linked.png"
    linked_file.symlink_to(image)
    linked_dir = media / "nested"
    linked_dir.symlink_to(other, target_is_directory=True)
    (root / "alarm_clips").symlink_to(other, target_is_directory=True)
    cleaner = violation_cleanup.ViolationMediaCleaner(root, retention_days=7, max_bytes=1, session_scope_factory=scope)
    assert cleaner._media_files() == []
    stats = MediaCleanupStats()
    for path in [linked_file, linked_dir / image.name, root / "alarm_clips" / image.name, media / ".." / "uploads" / image.name, media / "notes.json"]:
        assert cleaner._remove_managed_file(path, stats) == (False, 0)
    assert stats.skipped_unsafe_paths == 5
    assert image.read_bytes() == b"portrait"


def test_quota_keeps_fresh_orphan_and_removes_old_orphan_only(tmp_path):
    _, scope = _database()
    now = datetime.datetime.now()
    root = tmp_path / "data"
    fresh = root / "alarm_clips" / "fresh.mp4"
    old = root / "alarm_clips" / "old.mp4"
    fresh.parent.mkdir(parents=True)
    for path, seconds in [(fresh, 30), (old, 601)]:
        path.write_bytes(b"12345678")
        ts = (now - datetime.timedelta(seconds=seconds)).timestamp()
        os.utime(path, (ts, ts))
    cleaner = violation_cleanup.ViolationMediaCleaner(root, retention_days=7, max_bytes=1, session_scope_factory=scope)
    cleaner.cleanup(now=now)
    assert fresh.is_file()
    assert not old.exists()
