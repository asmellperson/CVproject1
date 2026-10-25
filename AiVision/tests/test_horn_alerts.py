"""喇叭响度、独立通知间隔及持续逗留播报的回归验证。"""
import audioop
import importlib
import queue
import struct
import threading
from datetime import datetime, timezone
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


def drain_playback(manager):
    """同步消费已有内存任务，不启动设备服务或后台线程。"""
    stop = threading.Event()
    jobs = manager._queue
    get = jobs.get

    def next_job(*args, **kwargs):
        if jobs.empty():
            stop.set()
            raise queue.Empty
        return get(*args, **kwargs)

    jobs.get = next_job
    try:
        manager._play_loop(stop, jobs)
    finally:
        jobs.get = get


def fence_playback(backend, monkeypatch, *, horn_interval=0, alarm_interval=10):
    from AiVision.features._shared import consumer as base_module
    from AiVision.features.security_fence import consumer as fence_module
    from AiVision.features.security_fence.runtime import FenceRuntime
    from AiVision.features.security_fence.schema import FenceValue

    module, dispatcher, clock = make_dispatcher(monkeypatch)
    monkeypatch.setattr(base_module, "alarm_dispatcher", dispatcher)
    monkeypatch.setattr(fence_module, "alarm_dispatcher", dispatcher)
    monkeypatch.setattr(backend.runtime_manager, "horn_sip_service", SimpleNamespace(server=Mock()))
    horn = Mock()
    horn.play.return_value = True
    horn.snapshot.return_value = {"state": "stopped"}
    manager = backend.runtime_manager.HornRuntimeManager(config_loader=lambda *_: [])
    manager._active = True
    manager._entries[1] = ({}, horn)
    dispatcher.horn_runtime_manager = manager
    consumer = fence_module.FenceConsumer.__new__(fence_module.FenceConsumer)
    consumer.feature_name = "security_fence"
    consumer.spec = SimpleNamespace(alarm_types=(15, 16))
    config = {"department": backend.department, "shm_name": "camera_1", "name": "围栏入口",
              "sql_enable": True, "horn_enable": True, "horn_id": 1, "horn_event_id": 2,
              "horn_interval": horn_interval, "alarm_interval": alarm_interval,
              "wechat_enable": True, "wechat_user": "test_user"}
    consumer.config_cache, consumer.frame_cache = {1: config}, {}
    value = FenceValue(confirmation_frames=1, alarm_interval=float(alarm_interval))
    runtime = FenceRuntime(value)
    consumer.runtimes = {1: runtime}
    consumer.unidentified_slots, consumer.unidentified_subjects, consumer.alarm_subjects = {}, {}, {}
    people = [{"bbox": [0., 0., 100., 200.]}]
    faces = [{"bbox": [20., 20., 80., 80.], "matched": True, "person_id": 1,
              "person_name": "员工", "similarity": .95}]

    def sample(moment, *, visible=True, allowed=()):
        clock.now = moment
        current = consumer.runtimes[1]
        persons = current.update(people if visible else [], faces if visible else [], (240, 320, 3),
                                 now=datetime(2026, 10, 25, 4, tzinfo=timezone.utc),
                                 monotonic=moment, allowed_person_ids=allowed)
        consumer._handle_alarm(1, (any(p.alarm for p in persons), {"persons": [p.model_dump() for p in persons]}), None)
        return persons

    return SimpleNamespace(module=module, dispatcher=dispatcher, clock=clock, manager=manager,
                           horn=horn, consumer=consumer, runtime=runtime, config=config, sample=sample)


def test_fence_zero_interval_repeats_after_actual_completion_without_duplicate_records(backend, monkeypatch):
    case = fence_playback(backend, monkeypatch)
    case.sample(0)
    case.sample(.1)
    assert case.manager._queue.qsize() == 1
    drain_playback(case.manager)
    case.sample(.2)
    drain_playback(case.manager)
    assert case.horn.play.call_count == 2
    assert case.dispatcher.violation_writer.save_now.call_count == 1
    assert case.dispatcher._wechat_queue.qsize() == 1


@pytest.mark.parametrize("interval", [10, None])
def test_fence_horn_interval_counts_audio_duration_from_trigger(backend, monkeypatch, interval):
    case = fence_playback(backend, monkeypatch, horn_interval=interval)
    case.sample(0)
    case.clock.now = 6
    drain_playback(case.manager)
    case.sample(6)
    case.sample(9.9)
    assert case.manager._queue.empty()
    case.sample(10)
    drain_playback(case.manager)
    assert case.horn.play.call_count == 2
    assert case.dispatcher.violation_writer.save_now.call_count == 1


def test_fence_rejected_horn_retries_without_consuming_long_interval(backend, monkeypatch):
    case = fence_playback(backend, monkeypatch, horn_interval=3600)
    case.manager._active = False
    case.sample(0)
    case.manager._active = True
    case.sample(4.9)
    assert case.manager._queue.empty()
    case.sample(5)
    drain_playback(case.manager)
    assert case.horn.play.call_count == 1
    assert case.dispatcher.violation_writer.save_now.call_count == 1
    assert case.dispatcher._wechat_queue.qsize() == 1


@pytest.mark.parametrize("failure", [False, RuntimeError("offline")])
def test_fence_play_failure_retries_and_then_respects_success_interval(backend, monkeypatch, failure):
    case = fence_playback(backend, monkeypatch, horn_interval=30)
    case.horn.play.side_effect = [failure, True] if isinstance(failure, Exception) else None
    case.horn.play.return_value = failure
    case.sample(0)
    drain_playback(case.manager)
    case.horn.play.side_effect = None
    case.horn.play.return_value = True
    case.sample(4.9)
    assert case.manager._queue.empty()
    case.sample(5)
    drain_playback(case.manager)
    case.sample(5.1)
    assert case.horn.play.call_count == 2
    assert case.manager._queue.empty()
    assert case.dispatcher.violation_writer.save_now.call_count == 1


def test_fence_expired_job_retries_from_failure_completion_time(backend, monkeypatch):
    case = fence_playback(backend, monkeypatch, horn_interval=60, alarm_interval=60)
    case.sample(0)
    case.clock.now = backend.settings.alarm.horn_queue_ttl_seconds + .1
    drain_playback(case.manager)
    case.horn.play.assert_not_called()
    case.sample(case.clock.now + 5)
    drain_playback(case.manager)
    assert case.horn.play.call_count == 1
    assert case.dispatcher.violation_writer.save_now.call_count == 1


def test_fence_no_current_violation_does_not_repeat_after_completion(backend, monkeypatch):
    case = fence_playback(backend, monkeypatch)
    case.sample(0)
    drain_playback(case.manager)
    case.sample(1, visible=False)
    case.sample(2, allowed={1})
    assert case.manager._queue.empty()
    assert case.horn.play.call_count == 1


def test_fence_horn_repeat_does_not_overwrite_failed_identity_patch(backend, monkeypatch):
    case = fence_playback(backend, monkeypatch)
    case.sample(0)
    event = next(iter(case.runtime.events.values()))
    event.person = event.person.model_copy(update={"identity": "pending", "person_id": None,
                                                 "bbox": [1., 1., 50., 100.]})
    case.dispatcher.violation_writer.enqueue_metadata_patch.side_effect = [False, True]
    drain_playback(case.manager)
    case.sample(.1)
    assert event.person.identity == "pending"
    assert event.person.bbox == [1., 1., 50., 100.]
    drain_playback(case.manager)
    case.sample(.2)
    assert event.person.identity == "unauthorized"
    assert event.person.bbox == [1., 1., 50., 100.]
    assert case.dispatcher.violation_writer.enqueue_metadata_patch.call_count == 2
    assert case.dispatcher.violation_writer.save_now.call_count == 1


def test_horn_tracked_coalescing_requires_same_queued_audio_and_is_bounded(backend, monkeypatch):
    monkeypatch.setattr(backend.settings.alarm, "horn_queue_size", 2)
    manager = backend.runtime_manager.HornRuntimeManager()
    horn = Mock()
    horn.play.return_value = True
    manager._active = True
    manager._entries[1] = ({}, horn)
    first, second, other = Mock(), Mock(), Mock()
    assert manager.enqueue_play(1, 2, on_complete=first)
    assert manager.enqueue_play(1, 2, on_complete=second)
    assert not manager.enqueue_play(1, 3, on_complete=other)
    assert not manager.enqueue_play(1, 2, on_complete=other)
    drain_playback(manager)
    horn.play.assert_called_once()
    first.assert_called_once_with(True)
    second.assert_called_once_with(True)
    other.assert_not_called()


def test_horn_started_playback_rejects_late_tracking_until_next_real_play(backend):
    manager = backend.runtime_manager.HornRuntimeManager()
    horn = Mock()
    manager._active = True
    manager._entries[1] = ({}, horn)
    first, late = Mock(), Mock()
    accepted = []

    def play(*args, **kwargs):
        # 不能把已经播放一半的音频当成新事件的完整播报。
        accepted.append(manager.enqueue_play(1, 2, on_complete=late))
        return True

    horn.play.side_effect = play
    assert manager.enqueue_play(1, 2, on_complete=first)
    drain_playback(manager)
    assert accepted == [False]
    first.assert_called_once_with(True)
    late.assert_not_called()
    horn.play.side_effect = None
    horn.play.return_value = True
    assert manager.enqueue_play(1, 2, on_complete=late)
    drain_playback(manager)
    late.assert_called_once_with(True)
    assert horn.play.call_count == 2


@pytest.mark.parametrize("result", ["success", "false", "exception", "expired"])
def test_horn_completion_reports_actual_worker_result_and_expiration(backend, monkeypatch, result):
    _, _, clock = make_dispatcher(monkeypatch)
    manager = backend.runtime_manager.HornRuntimeManager()
    horn = Mock()
    horn.play.return_value = result == "success"
    if result == "exception":
        horn.play.side_effect = RuntimeError("offline")
    manager._active = True
    manager._entries[1] = ({}, horn)
    callback = Mock()
    assert manager.enqueue_play(1, 2, on_complete=callback)
    if result == "expired":
        clock.now = backend.settings.alarm.horn_queue_ttl_seconds + .1
    drain_playback(manager)
    callback.assert_called_once_with(result == "success")
    assert horn.play.call_count == (0 if result == "expired" else 1)
    assert manager._queue.empty()
    assert not manager._pending


@pytest.mark.parametrize("path", ["worker", "retire", "stop"])
def test_horn_completion_is_once_outside_locks_and_old_jobs_do_not_play(backend, monkeypatch, path):
    manager = backend.runtime_manager.HornRuntimeManager(config_loader=lambda *_: [])
    horn = Mock()
    horn.play.return_value = True
    horn.snapshot.return_value = {"state": "stopped"}
    manager._active = True
    manager._entries[1] = ({}, horn)
    monkeypatch.setattr(backend.runtime_manager, "horn_sip_service", SimpleNamespace(server=Mock()))
    completed = []

    def callback(success):
        free = threading.Event()

        def acquire():
            with manager._sync_lock, manager._lock:
                free.set()

        thread = threading.Thread(target=acquire)
        thread.start()
        thread.join(timeout=1)
        completed.append((success, free.is_set()))

    assert manager.enqueue_play(1, 2, on_complete=callback)
    if path == "retire":
        manager.sync()
    elif path == "stop":
        manager.stop()
    drain_playback(manager)
    assert completed == [(path == "worker", True)]
    assert horn.play.call_count == (1 if path == "worker" else 0)
    assert not manager._pending


def test_horn_retired_job_cannot_clear_or_complete_new_device_job(backend, monkeypatch):
    config = {"id": 1, "enable": True, "url": "http://127.0.0.2",
              "username": "test", "password": "new", "sip": None}
    old, new = Mock(), Mock()
    for horn in (old, new):
        horn.play.return_value = True
        horn.snapshot.return_value = {"state": "stopped"}
    manager = backend.runtime_manager.HornRuntimeManager(
        config_loader=lambda *_: [config], horn_factory=lambda *args, **kwargs: new,
    )
    monkeypatch.setattr(backend.runtime_manager, "horn_sip_service", SimpleNamespace(server=Mock()))
    manager._active = True
    manager._entries[1] = ({**config, "password": "old"}, old)
    before, after = Mock(), Mock()
    assert manager.enqueue_play(1, 2, on_complete=before)
    old_job = manager._pending[1]
    manager.sync(1)
    before.assert_called_once_with(False)
    assert manager.enqueue_play(1, 2, on_complete=after)
    new_job = manager._pending[1]
    manager._finish_playback(old_job, True)
    assert manager._pending[1] is new_job
    after.assert_not_called()
    drain_playback(manager)
    old.play.assert_not_called()
    new.play.assert_called_once()
    before.assert_called_once_with(False)
    after.assert_called_once_with(True)


@pytest.mark.parametrize("success", [False, True])
def test_horn_dispatch_cooldown_uses_successful_trigger_time_only(backend, monkeypatch, success):
    module, dispatcher, clock = make_dispatcher(monkeypatch)
    callback = Mock()
    request = alarm_request(backend, module, horn=10)
    request.on_horn_complete = callback
    assert dispatcher.maybe_dispatch(request, channels={"horn"})
    complete = dispatcher.horn_runtime_manager.enqueue_play.call_args.kwargs["on_complete"]
    clock.now = 6
    complete(success)
    callback.assert_called_once_with(success)
    key = ("camera", "1", 5, "horn")
    assert not dispatcher._horn_attempts
    if success:
        assert dispatcher._last_alarm[key] == 0
        clock.now = 9.9
        assert not dispatcher.maybe_dispatch(request, channels={"horn"})
        clock.now = 10
    else:
        assert key not in dispatcher._last_alarm
    assert dispatcher.maybe_dispatch(request, channels={"horn"})
    assert dispatcher.horn_runtime_manager.enqueue_play.call_count == 2


def test_horn_old_completion_cannot_restore_reset_cooldown(backend, monkeypatch):
    module, dispatcher, clock = make_dispatcher(monkeypatch)
    callback = Mock()
    request = alarm_request(backend, module, horn=10)
    request.on_horn_complete = callback
    assert dispatcher.maybe_dispatch(request)
    complete = dispatcher.horn_runtime_manager.enqueue_play.call_args.kwargs["on_complete"]
    dispatcher.reset_cooldown(1, 5)
    clock.now = 5
    complete(True)
    complete(True)
    callback.assert_called_once_with(True)
    assert not dispatcher._last_alarm
    assert not dispatcher._horn_attempts


def test_horn_old_completion_does_not_override_new_attempt_after_reset(backend, monkeypatch):
    module, dispatcher, clock = make_dispatcher(monkeypatch)
    first = alarm_request(backend, module, horn=10)
    first.on_horn_complete = Mock()
    assert dispatcher.maybe_dispatch(first, channels={"horn"})
    old_complete = dispatcher.horn_runtime_manager.enqueue_play.call_args.kwargs["on_complete"]
    dispatcher.reset_cooldown(1, 5)
    clock.now = 1
    current = alarm_request(backend, module, horn=10)
    current.on_horn_complete = Mock()
    assert dispatcher.maybe_dispatch(current, channels={"horn"})
    current_complete = dispatcher.horn_runtime_manager.enqueue_play.call_args.kwargs["on_complete"]
    key = ("camera", "1", 5, "horn")
    clock.now = 2
    old_complete(True)
    assert key not in dispatcher._last_alarm
    assert key in dispatcher._horn_attempts
    clock.now = 3
    current_complete(True)
    assert dispatcher._last_alarm[key] == 1
    assert not dispatcher._horn_attempts
    old_complete(False)
    first.on_horn_complete.assert_called_once_with(True)
    current.on_horn_complete.assert_called_once_with(True)


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
