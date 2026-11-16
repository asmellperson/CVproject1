"""烟雾事件后台订阅回归，不连接摄像头、模型或真实通知服务。"""
from queue import Empty, Queue
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
import time

import cv2
import numpy as np
import pytest
from pydantic import ValidationError


@pytest.fixture
def modules(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "smoke_test",
        "MYSQL_DB_PASSWORD": "smoke_test", "MYSQL_DB_NAME": "smoke_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "smoke-test-signing-key-00000000",
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.features.smoke_detection import consumer, schema
    from AiVision.features.smoke_detection.events import SmokeEvent
    return consumer, schema, SmokeEvent


class Device:
    """可显式收发和取消的设备流，用真实线程验证生命周期。"""

    def __init__(self, camera, value):
        self.camera, self.value = camera, value
        self.queue = Queue()
        self.connected = Event()
        self.closed = Event()

    def iter_events(self, stop_event, on_connected=None, on_activity=None, on_protocol_warning=None):
        on_connected()
        self.connected.set()
        while not stop_event.is_set() and not self.closed.is_set():
            try:
                item = self.queue.get(timeout=0.05)
            except Empty:
                continue
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            on_activity()
            yield item

    def close(self):
        self.closed.set()
        self.queue.put(None)


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        Event().wait(0.01)
    assert predicate()


def runtime(modules, monkeypatch, *, frames=None, times=None):
    module, schema, _ = modules
    cfg = {**schema.SmokeValueSchema().model_dump(), "camera_id": 1, "name": "烟雾设备",
           "shm_name": "camera_1", "department": "general_electric", "enable": True,
           "camera_enable": True, "sql_enable": True}
    configs = {(1, "smoke_detection"): cfg}
    cameras = {1: {"id": 1, "url": "rtsp://operator:local-secret@camera.test/Streaming/Channels/101"}}
    monkeypatch.setattr(module.config_cache, "get_all_function_configs", lambda: dict(configs))
    monkeypatch.setattr(module.config_cache, "get_function_config", lambda key, feature: configs.get((key, feature)))
    monkeypatch.setattr(module.config_cache, "get_camera_config", cameras.get)
    dispatcher = Mock(return_value=True)
    monkeypatch.setattr(module, "_FRAME_MAX_AGE_SECONDS", 10)
    from AiVision.features._shared import consumer as shared
    monkeypatch.setattr(shared.alarm_dispatcher, "maybe_dispatch", dispatcher)
    devices = []

    def factory(camera, value):
        device = Device(camera, value)
        devices.append(device)
        return device

    consumer = module.SmokeConsumer(
        spec=SimpleNamespace(name="smoke_detection", alarm_types=(18,)), infer_dict={}, result_queue=Queue(),
        latest_frames=frames or {}, latest_frame_times=times or {}, is_camera_active=lambda key: True,
        device_factory=factory, reconnect_seconds=0.01, stop_timeout_seconds=1,
    )
    return consumer, configs, cameras, devices, dispatcher


def smoke_event(modules, *, active=True, date_time="2026-11-16T10:00:00+08:00", event_id="event-1", **kwargs):
    return modules[2]("smokeDetection", 1, active, date_time, event_id, **kwargs)


def test_schema_has_no_local_smoke_algorithm_or_stream_sampling_parameters(modules):
    _, schema, _ = modules
    expected = {"device_scheme", "device_port", "event_channel_id", "thermal_channel_id", "alarm_interval"}
    assert set(schema.SmokeValueSchema().model_dump()) == expected
    from AiVision.features.smoke_detection.orm import SmokeConfigORM
    assert set(SmokeConfigORM().to_value_dict()) == expected
    for value in ({"threshold": 0.5}, {"roi_pos": []}, {"cap_interval": 0.1},
                  {"device_port": True}, {"device_port": 0}, {"device_scheme": "ftp"}):
        with pytest.raises(ValidationError):
            schema.SmokeValueSchema.model_validate(value)


def test_active_event_dispatches_without_frame_and_preserves_source(modules, monkeypatch):
    consumer, _, _, devices, dispatcher = runtime(modules, monkeypatch)
    try:
        consumer.start()
        wait_until(lambda: devices and devices[0].connected.is_set())
        before = consumer.get_monitor_status("camera_1")
        assert before["connection_state"] == "connected" and before["alarm_state"] == "unknown"
        devices[0].queue.put(smoke_event(modules))
        wait_until(lambda: dispatcher.call_count == 1)
        request = dispatcher.call_args.args[0]
        assert request.frame is None and request.violation_type == 18
        assert request.metadata["source"] == "device"
        assert request.metadata["device_event_time"] == "2026-11-16T10:00:00+08:00"
        assert request.metadata["device_channel_id"] == 1
        assert consumer.get_monitor_status("camera_1")["alarm_state"] == "active"
        assert consumer.result_router._state != "running"
    finally:
        consumer.stop()
    assert devices[0].closed.is_set()


def test_same_ongoing_and_replayed_event_is_not_duplicated(modules, monkeypatch):
    consumer, _, _, devices, dispatcher = runtime(modules, monkeypatch)
    try:
        consumer.start()
        wait_until(lambda: devices and devices[0].connected.is_set())
        subscription = consumer._subscriptions[1]
        consumer._receive_event(subscription, smoke_event(modules))
        consumer._receive_event(subscription, smoke_event(modules, event_id="repeat", date_time="2026-11-16T10:00:01+08:00"))
        assert dispatcher.call_count == 1
        consumer._receive_event(subscription, smoke_event(modules, active=False))
        assert consumer.get_monitor_status("camera_1")["alarm_state"] == "inactive"
        consumer._receive_event(subscription, smoke_event(modules))
        assert dispatcher.call_count == 1
        consumer._receive_event(subscription, smoke_event(modules, active=False))
        consumer._receive_event(subscription, smoke_event(modules, date_time="2026-11-16T10:01:00+08:00"))
        assert dispatcher.call_count == 2
    finally:
        consumer.stop()


def test_wrong_channel_and_other_alarm_types_never_dispatch(modules, monkeypatch):
    consumer, _, _, devices, dispatcher = runtime(modules, monkeypatch)
    try:
        consumer.start()
        wait_until(lambda: devices and devices[0].connected.is_set())
        subscription = consumer._subscriptions[1]
        for event_type, channel in [("fireDetection", 1), ("thermometry", 1), ("smokeAndFireDetection", 1), ("smokeDetection", 2)]:
            consumer._receive_event(subscription, modules[2](event_type, channel, True, "2026-11-16T10:00:00+08:00", "test"))
        dispatcher.assert_not_called()
        assert consumer.get_monitor_status("camera_1")["alarm_state"] == "unknown"
    finally:
        consumer.stop()


def test_disconnect_is_unknown_and_reconnect_preserves_duplicate_state(modules, monkeypatch):
    consumer, _, _, devices, dispatcher = runtime(modules, monkeypatch)
    try:
        consumer.start()
        wait_until(lambda: devices and devices[0].connected.is_set())
        subscription = consumer._subscriptions[1]
        consumer._receive_event(subscription, smoke_event(modules))
        consumer._connection(subscription, "disconnected", "连接中断")
        status = consumer.get_monitor_status("camera_1")
        assert status["alarm_state"] == "unknown" and not status["alarm"]
        consumer._connection(subscription, "connected", "重新连接")
        consumer._receive_event(subscription, smoke_event(modules))
        assert dispatcher.call_count == 1
        assert consumer.get_monitor_status("camera_1")["alarm_state"] == "active"
        # 断线期间恢复又出现的新事件，即使没有收到inactive，也不能永远被旧持续态压制。
        consumer._connection(subscription, "disconnected", "再次中断")
        consumer._connection(subscription, "connected", "重新连接")
        consumer._receive_event(subscription, smoke_event(modules, date_time="2026-11-16T10:02:00+08:00"))
        assert dispatcher.call_count == 2
    finally:
        consumer.stop()


def test_stopped_runtime_does_not_restore_removed_or_disabled_camera(modules, monkeypatch):
    consumer, configs, _, devices, _ = runtime(modules, monkeypatch)
    consumer.start()
    wait_until(lambda: devices and devices[0].connected.is_set())
    consumer.stop()
    configs.clear()
    try:
        consumer.start()
        assert not consumer.config_cache and not consumer._subscriptions
        consumer.stop()
        configs[1, "smoke_detection"] = {"enable": True, "camera_enable": False}
        consumer.start()
        assert not consumer.config_cache and not consumer._subscriptions
    finally:
        consumer.stop()


def test_reconfigure_replaces_credentials_and_old_callbacks_are_ignored(modules, monkeypatch):
    consumer, configs, cameras, devices, dispatcher = runtime(modules, monkeypatch)
    try:
        consumer.start()
        wait_until(lambda: devices and devices[0].connected.is_set())
        previous = consumer._subscriptions[1]
        cameras[1] = {"id": 1, "url": "rtsp://updated:other-secret@new-camera.test/live"}
        configs[1, "smoke_detection"] = {**configs[1, "smoke_detection"], "device_port": 443, "device_scheme": "https"}
        consumer.update_config(1)
        wait_until(lambda: len(devices) == 2 and devices[1].connected.is_set())
        assert devices[0].closed.is_set()
        assert devices[1].camera == cameras[1]
        assert devices[1].value["device_port"] == 443
        consumer._receive_event(previous, smoke_event(modules))
        dispatcher.assert_not_called()
        consumer.update_status(1, False)
        assert devices[1].closed.is_set()
        assert consumer.get_monitor_status("camera_1") is None
        assert not consumer._subscriptions and not consumer.config_cache
    finally:
        consumer.stop()


def test_alarm_evidence_prefers_device_picture_and_rejects_stale_frame(modules, monkeypatch):
    latest = np.full((12, 12, 3), 20, dtype=np.uint8)
    consumer, _, _, devices, _ = runtime(modules, monkeypatch, frames={"camera_1": latest},
                                        times={"camera_1": time.time() - 100})
    try:
        consumer.start()
        wait_until(lambda: devices and devices[0].connected.is_set())
        subscription = consumer._subscriptions[1]
        assert consumer._event_frame(subscription, smoke_event(modules)) is None
        consumer.latest_frame_times["camera_1"] = time.time()
        assert np.array_equal(consumer._event_frame(subscription, smoke_event(modules)), latest)
        _, encoded = cv2.imencode(".jpg", np.full((16, 16, 3), 240, dtype=np.uint8))
        event = smoke_event(modules, picture=encoded.tobytes())
        evidence = consumer._event_frame(subscription, event)
        assert evidence.shape == (16, 16, 3) and evidence.mean() > 200
        assert consumer.get_live_preview("camera_1", latest, now=time.time()) is latest
    finally:
        consumer.stop()


def test_batch_commit_lost_acknowledgement_does_not_duplicate_imageless_events(modules, monkeypatch, tmp_path):
    """真实SQLite事务模拟已提交但客户端丢回执，混合图片批次与多条无图记录。"""
    from contextlib import contextmanager
    from datetime import datetime
    from sqlalchemy import Integer, MetaData, create_engine
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import sessionmaker
    from AiVision.alarms.records import service

    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    table = service.AiAlarmEvent.__table__.to_metadata(metadata)
    table.c.id.type = Integer()
    metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    writer = object.__new__(service.AsyncViolationWriter)
    writer._data_path = tmp_path
    writer._write_attempts = 2
    writer._retry_backoff = 0
    base = dict(violation_type=18, feature_name="smoke_detection", department="general_electric",
                camera_no="camera_1", ts=datetime.now())
    unrelated = writer._save_alarm_snapshot({**base, "frame": None, "event_metadata": {"tag": "unrelated"}})
    with sessions.begin() as session:
        session.add(service.AiAlarmEvent(**unrelated))
    batch = [writer._save_alarm_snapshot({**base, "frame": None, "event_metadata": {"tag": value}})
             for value in ("first", "second")]
    batch.append(writer._save_alarm_snapshot({**base, "frame": np.zeros((8, 8, 3), dtype=np.uint8)}))
    attempts = 0

    @contextmanager
    def commit_then_lose_ack():
        nonlocal attempts
        attempts += 1
        with sessions.begin() as session:
            yield session
        if attempts == 1:
            raise SQLAlchemyError("模拟提交已成功但回执丢失")

    monkeypatch.setattr(service, "session_scope", commit_then_lose_ack)
    try:
        assert writer._flush_batch(batch)
        assert attempts == 2
        with sessions() as session:
            rows = session.query(service.AiAlarmEvent).all()
            assert len(rows) == 4
            imageless = [row for row in rows if not row.image_path]
            assert len(imageless) == 3
            assert len({row.event_metadata["storage_event_key"] for row in imageless}) == 3
    finally:
        engine.dispose()


def test_expired_imageless_alarm_cleanup_does_not_attempt_empty_path(modules, tmp_path):
    from contextlib import contextmanager
    from datetime import datetime, timedelta
    from AiVision.alarms.records.cleanup import ViolationMediaCleaner
    from AiVision.core.media_cleanup import MediaRecord

    row = SimpleNamespace(id=42, create_time=datetime.now() - timedelta(days=40), image_path="", video_path=None)
    session = SimpleNamespace(get=lambda model, key: row, delete=Mock())

    @contextmanager
    def transaction():
        yield session

    cleaner = ViolationMediaCleaner(tmp_path, retention_days=31, max_bytes=0, session_scope_factory=transaction)
    remove_file = Mock(side_effect=AssertionError("无图记录不应尝试删除空路径"))
    assert cleaner.delete_record(MediaRecord(row.id, row.create_time, ()), remove_file) == 1
    remove_file.assert_not_called()
    session.delete.assert_called_once_with(row)


def test_connected_stream_requires_recognized_smoke_protocol_and_surfaces_warning(modules, monkeypatch):
    consumer, _, _, devices, dispatcher = runtime(modules, monkeypatch)
    try:
        consumer.start()
        wait_until(lambda: devices and devices[0].connected.is_set())
        subscription = consumer._subscriptions[1]
        before = consumer.get_monitor_status("camera_1")
        assert before["connection_state"] == "connected"
        assert not before["event_protocol_verified"]
        assert before["alarm_state"] == "unknown"
        assert before["message"] == "设备报警接口已连接，等待烟雾事件"
        consumer._protocol_warning(subscription, "设备上报烟火相关事件，烟雾子类型尚未核验，请完成设备联调")
        warning = consumer.get_monitor_status("camera_1")
        assert warning["reason"] == "unsupported_event" and warning["alarm_state"] == "unknown"
        assert not warning["event_protocol_verified"]
        dispatcher.assert_not_called()
        consumer._receive_event(subscription, smoke_event(modules))
        verified = consumer.get_monitor_status("camera_1")
        assert verified["event_protocol_verified"] and verified["reason"] == "smoke_alarm"
        assert verified["alarm_state"] == "active"
        assert dispatcher.call_count == 1
    finally:
        consumer.stop()


def test_heartbeat_keeps_transport_connected_without_inventing_smoke_state(modules, monkeypatch):
    consumer, _, _, devices, dispatcher = runtime(modules, monkeypatch)
    try:
        consumer.start()
        wait_until(lambda: devices and devices[0].connected.is_set())
        subscription = consumer._subscriptions[1]
        connected_at = consumer._smoke_states[1].last_activity_at
        monkeypatch.setattr(modules[0].time, "time", lambda: connected_at + 20)
        consumer._activity(subscription)
        monkeypatch.setattr(modules[0].time, "time", lambda: connected_at + 40)
        status = consumer.get_monitor_status("camera_1")
        assert status["connection_state"] == "connected"
        assert status["alarm_state"] == "unknown"
        assert not status["event_protocol_verified"]
        assert status["last_event_at"] is None
        assert status["valid_for_seconds"] == 10
        dispatcher.assert_not_called()
        # 真正没有心跳或事件时仍应过期，不把长期静默描述成设备正常。
        monkeypatch.setattr(modules[0].time, "time", lambda: connected_at + 51)
        expired = consumer.get_monitor_status("camera_1")
        assert expired["connection_state"] == "disconnected"
        assert expired["alarm_state"] == "unknown"
        assert expired["valid_for_seconds"] == 0
        assert "未收到心跳或事件" in expired["message"]
    finally:
        consumer.stop()


def test_reconnected_verified_protocol_waits_for_new_device_state(modules, monkeypatch):
    consumer, _, _, devices, dispatcher = runtime(modules, monkeypatch)
    try:
        consumer.start()
        wait_until(lambda: devices and devices[0].connected.is_set())
        subscription = consumer._subscriptions[1]
        consumer._receive_event(subscription, smoke_event(modules))
        devices[0].queue.put(None)
        wait_until(lambda: len(devices) == 2 and devices[1].connected.is_set())
        status = consumer.get_monitor_status("camera_1")
        assert status["connection_state"] == "connected"
        assert status["event_protocol_verified"]
        assert status["alarm_state"] == "unknown"
        assert status["message"] == "设备报警接口已连接，等待烟雾事件"
        assert dispatcher.call_count == 1
    finally:
        consumer.stop()


@pytest.fixture
def smoke_mysql_schema(modules, monkeypatch):
    """复现现场 MySQL 8 的反射文本，其余结构与正式烟雾表完全一致。"""
    from sqlalchemy import UniqueConstraint
    from sqlalchemy.dialects import mysql, sqlite
    from AiVision.core import schema
    from AiVision.cameras import orm as _camera_orm  # noqa: F401
    from AiVision.alarms.devices import orm as _horn_orm  # noqa: F401
    from AiVision.features.smoke_detection.orm import SmokeConfigORM

    table = SmokeConfigORM.__table__
    checks = [
        {"name": "ck_smoke_device_port", "sqltext": "(`device_port` between 1 and 65535)"},
        {"name": "ck_smoke_event_channel", "sqltext": "(`event_channel_id` > 0)"},
        {"name": "ck_smoke_thermal_channel", "sqltext": "(`thermal_channel_id` > 0)"},
        {"name": "ck_smoke_device_scheme", "sqltext": "(`device_scheme` in (_utf8mb4'http',_utf8mb4'https'))"},
        {"name": "ck_smoke_alarm_interval", "sqltext": "(`alarm_interval` > 0)"},
    ]
    inspector = SimpleNamespace(
        get_columns=lambda name: [
            {"name": column.name, "type": column.type, "nullable": column.nullable,
             "default": str(column.server_default.arg) if column.server_default is not None else None}
            for column in table.columns
        ],
        get_pk_constraint=lambda name: {"constrained_columns": [column.name for column in table.primary_key]},
        get_indexes=lambda name: [
            {"column_names": [column.name for column in index.columns], "unique": index.unique}
            for index in table.indexes
        ],
        get_unique_constraints=lambda name: [
            {"column_names": [column.name for column in constraint.columns]}
            for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
        ],
        get_foreign_keys=lambda name: [
            {"constrained_columns": [column.name for column in constraint.columns],
             "referred_table": constraint.referred_table.name,
             "referred_columns": [element.column.name for element in constraint.elements],
             "options": {"ondelete": constraint.ondelete}}
            for constraint in table.foreign_key_constraints
        ],
        get_check_constraints=lambda name: checks,
    )
    monkeypatch.setattr(schema, "inspect", lambda connection: inspector)
    return SimpleNamespace(schema=schema, table=table, checks=checks,
                           connection=SimpleNamespace(dialect=mysql.dialect()), sqlite=sqlite.dialect())


def test_smoke_bootstrap_accepts_mysql_utf8mb4_check_reflection(smoke_mysql_schema):
    reflected = smoke_mysql_schema
    reflected.schema.assert_table_matches(reflected.connection, reflected.table)


@pytest.mark.parametrize("scheme_sql", [
    "(`device_scheme` in (_utf8mb4'http',_utf8mb4'ftp'))",
    "(`device_scheme` in (_utf8mb4'HTTP',_utf8mb4'https'))",
    "(`device_scheme` in (_utf8mb4'h ttp',_utf8mb4'https'))",
    "(`device_scheme` in (_utf8mb4'http()',_utf8mb4'https'))",
    "(`device_scheme` in ('_utf8mb4http',_utf8mb4'https'))",
    "(`device_scheme` in (_binary'http',_binary'https'))",
    "(`device_scheme` in (_latin1'http',_latin1'https'))",
])
def test_smoke_bootstrap_rejects_changed_check_literal_semantics(smoke_mysql_schema, scheme_sql):
    reflected = smoke_mysql_schema
    reflected.checks[3]["sqltext"] = scheme_sql
    with pytest.raises(ValueError, match="CHECK 约束不一致"):
        reflected.schema.assert_table_matches(reflected.connection, reflected.table)


@pytest.mark.parametrize("change", ["range", "missing"])
def test_smoke_bootstrap_still_rejects_real_schema_drift(smoke_mysql_schema, change):
    reflected = smoke_mysql_schema
    if change == "range":
        reflected.checks[0]["sqltext"] = "(`device_port` between 1 and 65536)"
    else:
        reflected.checks.pop(0)
    with pytest.raises(ValueError, match="CHECK 约束不一致"):
        reflected.schema.assert_table_matches(reflected.connection, reflected.table)


def test_smoke_bootstrap_does_not_apply_mysql_literal_rules_to_sqlite(smoke_mysql_schema):
    reflected = smoke_mysql_schema
    reflected.connection.dialect = reflected.sqlite
    with pytest.raises(ValueError, match="CHECK 约束不一致"):
        reflected.schema.assert_table_matches(reflected.connection, reflected.table)
