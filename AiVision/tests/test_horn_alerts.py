"""喇叭响度、独立通知间隔及持续逗留播报的回归验证。"""
import audioop
import importlib
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def backend(monkeypatch, tmp_path):
    # 只使用隔离的内存数据库；导入配置时不依赖部署环境的凭据和目录。
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "tests",
        "MYSQL_DB_PASSWORD": "unused", "MYSQL_DB_NAME": "tests", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    modules = {name: importlib.import_module(f"AiVision.alarms.devices.{name}")
               for name in ("audio", "schema", "service", "horn", "runtime_manager", "orm")}
    from AiVision.core import db
    from AiVision.core.settings import settings
    from AiVision.departments import DEPARTMENT_SPECS
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.features.person_dwell.orm import HumanConfigORM

    monkeypatch.setattr(settings.storage, "data_path", str(tmp_path))
    return SimpleNamespace(**modules, db=db, settings=settings, department=next(iter(DEPARTMENT_SPECS)),
                           camera=AiCameraConfig, human=HumanConfigORM)


@pytest.fixture
def database(backend, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    backend.db.Base.metadata.create_all(engine, tables=[
        backend.orm.AiHornConfig.__table__, backend.orm.AiHornAudio.__table__,
        backend.camera.__table__, backend.human.__table__,
    ])
    factory = sessionmaker(engine, expire_on_commit=False)
    for module in (backend.db, backend.audio, backend.service):
        monkeypatch.setattr(module, "get_session", factory)
    yield factory
    engine.dispose()


def encoded_samples(*samples):
    return audioop.lin2alaw(struct.pack(f"<{len(samples)}h", *samples), 2)


@pytest.mark.parametrize("volume", [0, 50, 100, 150, 200])
def test_volume_scales_pcm_without_changing_duration(backend, volume):
    source = encoded_samples(*([1000, -1000, 2000, -2000] * 160))
    adjusted = backend.audio.HornAudioService.adjust_volume(source, volume)
    assert len(adjusted) == len(source)
    if volume == 100:
        assert adjusted is source
    elif volume == 0:
        assert adjusted == backend.audio.SILENCE * len(source)
    else:
        original_rms = audioop.rms(audioop.alaw2lin(source, 2), 2)
        adjusted_rms = audioop.rms(audioop.alaw2lin(adjusted, 2), 2)
        assert adjusted_rms / original_rms == pytest.approx(volume / 100, rel=.05)


def test_amplification_clips_without_wrapping_sign(backend):
    result = backend.audio.HornAudioService.adjust_volume(encoded_samples(30000, -30000), 200)
    positive, negative = struct.unpack("<hh", audioop.alaw2lin(result, 2))
    assert positive >= 30000
    assert negative <= -30000


@pytest.mark.parametrize("volume", [-1, 201, True, 50.5, "100", None, float("nan")])
def test_invalid_volume_is_rejected_by_api_and_playback(backend, volume):
    with pytest.raises(ValidationError):
        backend.schema.HornSipWrite(username="test", auth_id="test", volume_percent=volume)
    with pytest.raises(backend.audio.HornAudioError):
        backend.audio.HornAudioService.adjust_volume(b"\xd5", volume)


def test_volume_is_saved_returned_and_defaulted_for_existing_devices(backend, database):
    service = backend.service.HornService(runtime_manager=Mock())
    sip = {"username": "test", "auth_id": "test", "port": 5060, "password": "unused"}
    created = service.create_horn({"name": "test speaker", "department": backend.department,
                                  "url": "http://127.0.0.2", "password": "unused", "sip": sip})
    assert created["sip"]["volume_percent"] == 100
    assert "password" not in created["sip"]
    updated = service.update_horn(created["id"], {"sip": {**sip, "password": "", "volume_percent": 0}})
    assert updated["sip"]["volume_percent"] == 0
    internal = service.runtime_configs(created["id"])[0]
    assert internal["sip"]["volume_percent"] == 0
    assert internal["sip"]["password"] == "unused"
    with database.begin() as session:
        row = session.get(backend.orm.AiHornConfig, created["id"])
        row.sip_config = sip
    assert service.get_horn(created["id"])["sip"]["volume_percent"] == 100


@pytest.mark.parametrize("volume", [0, 50, 100, 200])
def test_preview_and_alarm_use_device_volume_without_modifying_shared_audio(backend, database, monkeypatch, volume):
    source = encoded_samples(*([1000, -1000] * 160))
    with database.begin() as session:
        row = backend.orm.AiHornAudio(name="test.aac", storage_key="a" * 32, size=1, duration=.04)
        session.add(row)
        session.flush()
        audio_id = row.id
    root = backend.audio.horn_audio_service.root
    root.mkdir()
    path = root / f"{'a' * 32}.alaw"
    path.write_bytes(source)
    horn = backend.horn.Horn({"id": 1, "horn_url": "http://127.0.0.2",
                              "sip": {"volume_percent": volume}}, connect_on_init=False)
    horn.status = True
    monkeypatch.setattr(horn, "prepare_sip", lambda: True)
    server = Mock()
    monkeypatch.setattr(backend.horn, "horn_sip_service", SimpleNamespace(server=server))
    assert horn.play(audio_id, preview=True)
    # 正式播报紧接试播，不能被设备层固定的五秒冷却吞掉。
    assert horn.play(audio_id)
    assert server.play.call_count == 2
    expected = backend.audio.HornAudioService.adjust_volume(source, volume)
    assert all(call.args[1] == expected for call in server.play.call_args_list)
    assert path.read_bytes() == source
    assert backend.audio.horn_audio_service.read_encoded(audio_id) == source


def make_dispatcher(monkeypatch):
    from AiVision.alarms import dispatcher as module
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock.now)
    dispatcher = module.AlarmDispatcher()
    dispatcher.horn_runtime_manager = Mock()
    dispatcher.wechat = Mock()
    dispatcher.violation_writer = Mock()
    dispatcher.violation_writer.save_now.return_value = SimpleNamespace(id=1)
    return module, dispatcher, clock


def alarm_request(backend, module, *, horn=0, wechat=300, camera_id=1, sql=False):
    return module.AlarmRequest(
        feature_name="detect_human", camera_id=camera_id, camera_name="test camera", frame=None,
        violation_type=5, department=backend.department, cooldown_subject_type="camera",
        cooldown_subject_id=str(camera_id), alarm_config={
            "sql": {"enable": sql},
            "horn": {"enable": True, "interval": horn, "parm": {"horn_id": 1, "horn_event_id": 2}},
            "wechat": {"enable": True, "interval": wechat, "parm": {"user": "test_user"}},
        },
    )


def test_zero_horn_interval_does_not_repeat_wechat_or_database(backend, monkeypatch):
    module, dispatcher, clock = make_dispatcher(monkeypatch)
    request = alarm_request(backend, module)
    for moment in (0, .1, 1, 5, 100, 299.9, 300):
        clock.now = moment
        assert dispatcher.maybe_dispatch(request, alarm_interval=5)
    assert dispatcher.horn_runtime_manager.enqueue_play.call_count == 7
    assert dispatcher._wechat_queue.qsize() == 2
    assert dispatcher.violation_writer.save_now.call_count == 2
    dispatcher.violation_writer.enqueue.assert_not_called()


def test_all_three_channels_keep_their_own_cooldown(backend, monkeypatch):
    module, dispatcher, clock = make_dispatcher(monkeypatch)
    request = alarm_request(backend, module, horn=10, wechat=3, sql=True)
    for moment in (0, 1, 3, 4, 5, 6, 10):
        clock.now = moment
        dispatcher.maybe_dispatch(request, alarm_interval=5)
    assert dispatcher.horn_runtime_manager.enqueue_play.call_count == 2
    assert dispatcher._wechat_queue.qsize() == 4
    assert dispatcher.violation_writer.save_now.call_count == 4
    assert dispatcher.violation_writer.enqueue.call_count == 1
    dispatcher.reset_cooldown(1, 5)
    assert dispatcher.maybe_dispatch(request, alarm_interval=5)
    assert dispatcher.horn_runtime_manager.enqueue_play.call_count == 3


@pytest.mark.parametrize("interval", [-1, True, float("inf"), float("nan"), "0"])
def test_invalid_channel_interval_is_rejected(backend, monkeypatch, interval):
    from AiVision.features._shared.alarm_schema import AlarmConfigSchema
    with pytest.raises(ValidationError):
        AlarmConfigSchema.model_validate({"horn": {"interval": interval}})
    module, dispatcher, _ = make_dispatcher(monkeypatch)
    with pytest.raises(ValueError):
        dispatcher.maybe_dispatch(alarm_request(backend, module, horn=interval))


def test_busy_speaker_coalesces_requests_without_queuing_repeats(backend):
    manager = backend.runtime_manager.HornRuntimeManager()
    horn = Mock()
    assert not manager.enqueue_play(1, 2)
    manager._active = True
    manager._entries[1] = ({}, horn)
    assert manager.enqueue_play(1, 2)
    assert manager.enqueue_play(1, 2)
    assert manager._queue.qsize() == 1
    assert not manager.enqueue_play(2, 2)


def test_dwell_repeats_after_ten_seconds_and_stops_when_person_leaves(backend, monkeypatch):
    from AiVision.features._shared import consumer as base_module, dwell_consumer as dwell_module
    from AiVision.features.person_dwell.consumer import HumanConsumer
    from AiVision.features.person_dwell.schema import HumanValueSchema
    from AiVision.inference.contracts import INFERENCE_STATUS_OK

    module, dispatcher, clock = make_dispatcher(monkeypatch)
    monkeypatch.setattr(base_module, "alarm_dispatcher", dispatcher)
    monkeypatch.setattr(dwell_module, "monotonic", lambda: clock.now)
    cfg = {**HumanValueSchema(MAX_TIME=10).model_dump(), "department": backend.department,
           "shm_name": "test", "horn_enable": True, "horn_id": 1, "horn_event_id": 2,
           "horn_interval": 0, "wechat_enable": True, "wechat_user": "test_user", "wechat_interval": 300}
    consumer = HumanConsumer.__new__(HumanConsumer)
    consumer.spec = SimpleNamespace(required_models=("yolo_human",), alarm_types=(5,))
    consumer.feature_name = "detect_human"
    consumer.config_cache = {1: cfg}
    consumer.frame_cache = {}
    consumer._trackers, consumer._observation_clocks = {}, {}
    detection = {"bbox": [10, 10, 100, 200], "confidence": .9, "class_id": 0, "type": "person"}
    observations = [detection]
    consumer.dispatch_inference_sync = lambda *args, **kwargs: {"status": INFERENCE_STATUS_OK, "detections": observations}
    for moment, expected in ((0, False), (9.9, False), (10, True), (10.2, True), (11, True)):
        clock.now = moment
        result = consumer._process(None, 1)
        assert result[0] is expected
        consumer._handle_alarm(1, result, None)
    assert dispatcher.horn_runtime_manager.enqueue_play.call_count == 3
    assert dispatcher._wechat_queue.qsize() == 1
    observations.clear()
    clock.now = 12
    result = consumer._process(None, 1)
    assert not result[0]
    consumer._handle_alarm(1, result, None)
    assert dispatcher.horn_runtime_manager.enqueue_play.call_count == 3


def test_independent_intervals_persist_in_feature_configuration(backend, database):
    from AiVision.features.person_dwell.schema import HumanConfigSchema
    config = HumanConfigSchema.model_validate({"alarm": {
        "horn": {"interval": 0}, "wechat": {"interval": 300},
    }}).model_dump()
    row = backend.human(camera_id=1)
    row.apply_config_dict(config)
    with database.begin() as session:
        session.add(row)
        session.flush()
        identifier = row.id
    with database() as session:
        saved = session.get(backend.human, identifier).to_config_dict()
    assert saved["alarm"]["horn"]["interval"] == 0
    assert saved["alarm"]["wechat"]["interval"] == 300
    assert "horn_interval" not in saved["value"]
    assert saved["value"]["alarm_interval"] == 5


@pytest.mark.parametrize("feature", [
    "visual_language_detection", "blocks", "security_fence", "tailgating", "detect_door", "detect_face",
    "detect_human", "detect_phone", "recognize_face", "security_inspection", "agv_person_check",
])
def test_every_camera_detection_round_trips_independent_intervals(backend, feature):
    from AiVision.features.registry import get_spec
    spec = get_spec(feature)
    config = spec.config_schema.model_validate({"alarm": {
        "horn": {"interval": 0}, "wechat": {"interval": 300},
    }})
    row = spec.orm_class(camera_id=1)
    row.apply_config_dict(config.model_dump())
    saved = spec.config_schema.model_validate(row.to_config_dict())
    assert saved.alarm.horn.interval == 0
    assert saved.alarm.wechat.interval == 300


def test_logistics_and_guard_accept_separate_intervals(backend):
    from AiVision.features.logistics_channel.schema import LogisticsChannelAlarm
    from AiVision.features.guard_behavior.schema import GuardBehaviorRuntimeAlarmPolicy
    alarm = LogisticsChannelAlarm.model_validate({"horn": {"interval": 0}, "wechat": {"interval": 300}})
    assert alarm.horn.interval == 0 and alarm.wechat.interval == 300
    policy = GuardBehaviorRuntimeAlarmPolicy(violation_type=8, alarm_interval=5, horn_interval=0, wechat_interval=300)
    assert policy.horn_interval == 0 and policy.wechat_interval == 300


def test_logistics_intervals_persist_through_service_mapping(backend, database):
    from AiVision.features.logistics_channel.orm import LogisticsChannel, LogisticsChannelAlarmSchedule
    from AiVision.features.logistics_channel.schema import LogisticsChannelConfigResponse
    from AiVision.features.logistics_channel.service import LogisticsChannelService

    engine = database.kw["bind"]
    backend.db.Base.metadata.create_all(engine, tables=[LogisticsChannel.__table__, LogisticsChannelAlarmSchedule.__table__])
    with database.begin() as session:
        channel = LogisticsChannel(name="test channel", feature_name="detect_logistics_single_person", department=backend.department)
        session.add(channel)
        session.flush()
        LogisticsChannelService()._apply_config_values(channel, {"alarm": {
            "horn": {"interval": 0}, "wechat": {"interval": 300},
        }})
        identifier = channel.id
    with database() as session:
        saved = LogisticsChannelConfigResponse.model_validate(session.get(LogisticsChannel, identifier))
    assert saved.alarm.horn.interval == 0
    assert saved.alarm.wechat.interval == 300


def test_guard_intervals_persist_through_policy_service(backend, database):
    from AiVision.features.guard_behavior.orm import GuardBehaviorSite, GuardBehaviorAlarmPolicy
    from AiVision.features.guard_behavior.schema import GuardBehaviorRuntimeAlarmPolicy
    from AiVision.features.guard_behavior.service import GuardBehaviorService

    engine = database.kw["bind"]
    backend.db.Base.metadata.create_all(engine, tables=[GuardBehaviorSite.__table__, GuardBehaviorAlarmPolicy.__table__])
    with database.begin() as session:
        site = GuardBehaviorSite(name="test site", department=backend.department)
        session.add(site)
        session.flush()
        policy = GuardBehaviorAlarmPolicy(site_id=site.id, violation_type=8)
        session.add(policy)
        session.flush()
        site_id, identifier = site.id, policy.id
    saved = GuardBehaviorService().update_alarm_policy(site_id, 8, {"horn_interval": 0, "wechat_interval": 300})
    assert saved["horn_interval"] == 0 and saved["wechat_interval"] == 300
    with database() as session:
        runtime = GuardBehaviorRuntimeAlarmPolicy.model_validate(session.get(GuardBehaviorAlarmPolicy, identifier))
    assert runtime.horn_interval == 0 and runtime.wechat_interval == 300


def test_interval_migration_preserves_existing_configuration_and_is_repeatable(backend, monkeypatch):
    from AiVision.migrations import alarm_channel_intervals_20261021 as migration

    metadata = MetaData()
    for table in (backend.orm.AiHornConfig.__table__, backend.camera.__table__, backend.human.__table__):
        table.to_metadata(metadata)
    previous = metadata.tables[backend.human.__tablename__]
    for name in migration.INTERVAL_COLUMNS:
        previous._columns.remove(previous.c[name])
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    monkeypatch.setattr(migration, "_tables", lambda: [backend.human.__table__])
    try:
        with engine.begin() as connection:
            connection.execute(previous.insert().values(camera_id=1, alarm_interval=17, MAX_TIME=10))
        assert migration.check(engine)["tables"][previous.name] == ["horn_interval", "wechat_interval"]
        assert migration.apply(engine)["tables"][previous.name] == []
        assert migration.apply(engine)["tables"][previous.name] == []
        with engine.connect() as connection:
            row = connection.execute(select(backend.human.__table__)).mappings().one()
        assert row["alarm_interval"] == 17
        assert row["MAX_TIME"] == 10
        assert row["horn_interval"] is None and row["wechat_interval"] is None
    finally:
        engine.dispose()


def test_migration_covers_all_thirteen_alarm_configuration_tables(backend):
    from AiVision.migrations import alarm_channel_intervals_20261021 as migration
    tables = migration._tables()
    assert len(tables) == 13
    metadata = MetaData()
    for table in tables[0].metadata.tables.values():
        table.to_metadata(metadata)
    for table in tables:
        previous = metadata.tables[table.name]
        for name in migration.INTERVAL_COLUMNS:
            previous._columns.remove(previous.c[name])
    engine = create_engine("sqlite:///:memory:")
    try:
        metadata.create_all(engine)
        assert all(len(columns) == 2 for columns in migration.check(engine)["tables"].values())
        result = migration.apply(engine)
        assert len(result["tables"]) == 13
        assert not any(result["tables"].values())
    finally:
        engine.dispose()
