"""告警快照、队列排空和事务失败恢复的回归测试；数据库仅使用临时 SQLite。"""
from contextlib import contextmanager
import datetime
import json
import os
from queue import Queue
import threading

import cv2
import numpy as np
import pytest
from sqlalchemy import Integer, MetaData, create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATA_PATH", "/tmp/aivision-test-data")
os.environ.setdefault("MYSQL_DB_URL", "127.0.0.1")
os.environ.setdefault("MYSQL_DB_USER", "test")
os.environ.setdefault("MYSQL_DB_PASSWORD", "test")
os.environ.setdefault("MYSQL_DB_NAME", "test")
from AiVision.platform.violation import service
from AiVision.platform.violation.orm import AiAlarmEvent


@pytest.fixture
def writer_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'alarms.db'}")
    table = AiAlarmEvent.__table__.to_metadata(MetaData())
    table.c.id.type = Integer()
    table.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def scope():
        with factory.begin() as session:
            yield session

    monkeypatch.setattr(service, "session_scope", scope)
    monkeypatch.setattr(service.settings.storage, "data_path", str(tmp_path / "media"))
    writer = service.AsyncViolationWriter()
    writer._batch_size = 2
    writer._retry_backoff = 0.001
    yield writer, factory, scope
    writer.stop()
    engine.dispose()


def enqueue(writer, value=12, **extra):
    writer.enqueue(
        np.full((16, 24, 3), value, dtype=np.uint8), 6, "camera-1",
        feature_name="detect_logistics_single_person", department="general_electric", **extra,
    )


def test_enqueue_freezes_frame_and_nested_metadata(writer_db):
    writer, factory, _ = writer_db
    frame = np.full((16, 24, 3), 35, dtype=np.uint8)
    metadata = {"camera_counts": {"1": 2}}
    writer.enqueue(frame, 1, "camera-1", feature_name="blocks", department="research_institute", event_metadata=metadata)
    frame[:] = 255
    metadata["camera_counts"]["1"] = 100
    writer.stop()
    with factory() as session:
        row = session.query(AiAlarmEvent).one()
        assert np.all(cv2.imread(row.image_path) == 35)
        assert row.event_metadata == {"camera_counts": {"1": 2}}
        assert (row.violation_type, row.feature_name, row.department) == (1, "blocks", "research_institute")


def test_full_queue_and_stopped_writer_do_not_raise(writer_db, monkeypatch):
    writer, factory, _ = writer_db
    messages = []
    monkeypatch.setattr(service.logger, "warning", messages.append)
    writer._queue = Queue(maxsize=1)
    enqueue(writer)
    enqueue(writer)
    assert writer._queue.qsize() == 1
    assert any("队列已满" in message for message in messages)
    writer.stop()
    enqueue(writer)
    assert writer._queue.unfinished_tasks == 0
    assert writer._queue.empty()
    with factory() as session:
        assert session.query(AiAlarmEvent).count() == 1
    assert any("停止接收" in message for message in messages)


def test_stop_drains_multiple_batches_and_waits_for_commit(writer_db, monkeypatch):
    writer, factory, scope = writer_db
    entered = threading.Event()
    release = threading.Event()

    @contextmanager
    def slow_scope():
        with scope() as session:
            yield session
            entered.set()
            assert release.wait(3)

    monkeypatch.setattr(service, "session_scope", slow_scope)
    for value in range(7):
        enqueue(writer, value)
    writer._thread = threading.Thread(target=writer._run)
    writer._thread.start()
    stopper = threading.Thread(target=writer.stop)
    try:
        assert entered.wait(3)
        stopper.start()
        stopper.join(0.05)
        assert stopper.is_alive()
    finally:
        release.set()
        stopper.join(3)
    assert not stopper.is_alive()
    assert writer._queue.unfinished_tasks == 0
    with factory() as session:
        assert session.query(AiAlarmEvent).count() == 7


def test_failed_commit_retries_entire_batch_with_backoff(writer_db, monkeypatch):
    writer, factory, scope = writer_db
    attempts = []
    delays = []

    @contextmanager
    def flaky_scope():
        with scope() as session:
            attempts.append(True)
            yield session
            if len(attempts) < 3:
                raise RuntimeError("commit failed")

    monkeypatch.setattr(service, "session_scope", flaky_scope)
    monkeypatch.setattr(service.time, "sleep", delays.append)
    enqueue(writer)
    enqueue(writer)
    writer.stop()
    assert len(attempts) == 3
    assert delays == [0.001, 0.002]
    with factory() as session:
        assert session.query(AiAlarmEvent).count() == 2
    assert not list(writer._data_path.glob("alarm_failed_batches/*.json"))


def test_lost_commit_acknowledgement_does_not_duplicate_records(writer_db, monkeypatch):
    writer, factory, scope = writer_db
    attempts = []

    @contextmanager
    def lost_ack_scope():
        attempts.append(True)
        with scope() as session:
            yield session
        if len(attempts) == 1:
            raise RuntimeError("connection lost after successful commit")

    monkeypatch.setattr(service, "session_scope", lost_ack_scope)
    enqueue(writer)
    writer.stop()
    with factory() as session:
        assert session.query(AiAlarmEvent).count() == 1
    assert len(attempts) == 2


def test_exhausted_retries_preserve_batch_and_continue_draining(writer_db, monkeypatch):
    writer, factory, _ = writer_db
    attempts = []

    @contextmanager
    def unavailable():
        attempts.append(True)
        raise RuntimeError("database unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(service, "session_scope", unavailable)
    for value in range(3):
        enqueue(writer, value)
    writer.stop()
    assert len(attempts) == 6
    files = list(writer._data_path.glob("alarm_failed_batches/*.json"))
    rows = [row for path in files for row in json.loads(path.read_text())]
    assert len(rows) == 3
    assert all(row["department"] == "general_electric" for row in rows)
    assert writer._queue.unfinished_tasks == 0
    with factory() as session:
        assert session.query(AiAlarmEvent).count() == 0


def test_identical_timestamps_have_distinct_png_files(writer_db):
    writer, _, _ = writer_db
    item = {"frame": np.zeros((16, 24, 3), dtype=np.uint8), "ts": datetime.datetime.now(), "violation_type": 1, "feature_name": "blocks", "department": "research_institute", "camera_no": "same"}
    first = writer._save_alarm_snapshot(item)
    item["frame"][:] = 127
    second = writer._save_alarm_snapshot(item)
    assert first["image_path"] != second["image_path"]
    assert np.all(cv2.imread(first["image_path"]) == 0)
    assert np.all(cv2.imread(second["image_path"]) == 127)


def test_snapshot_failure_does_not_block_drain(writer_db, monkeypatch):
    writer, factory, _ = writer_db
    monkeypatch.setattr(service.cv2, "imwrite", lambda *_: False)
    enqueue(writer)
    writer.stop()
    assert writer._queue.unfinished_tasks == 0
    with factory() as session:
        assert session.query(AiAlarmEvent).count() == 0
