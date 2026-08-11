import importlib
import sys
import threading
from types import SimpleNamespace

from core.events import ConfigChangeEvent

sys.modules.pop("platform", None)
Orchestrator = importlib.import_module("platform.orchestrator").Orchestrator


def _orchestrator_without_init():
    orchestrator = object.__new__(Orchestrator)
    orchestrator.consumers = {}
    orchestrator._feature_states = {}
    orchestrator._feature_runtime_lock = threading.RLock()
    orchestrator.logistics_channel_runtime = SimpleNamespace(
        refresh_channel=lambda *_args: None,
        refresh_camera=lambda *_args: None,
        refresh_camera_all=lambda *_args: None,
    )
    return orchestrator


def test_camera_runtime_alert_types_share_one_repeat_interval(monkeypatch):
    orchestrator = _orchestrator_without_init()
    sent = []
    orchestrator._wechat = SimpleNamespace(
        send_text=lambda **kwargs: sent.append(kwargs)
    )
    orchestrator._last_system_exception_alerts = {}
    orchestrator._system_exception_alert_lock = threading.Lock()

    clock = SimpleNamespace(now=10_000.0)
    orchestrator_module = importlib.import_module("platform.orchestrator")
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: clock.now)
    monkeypatch.setattr(
        orchestrator_module.system_config_service,
        "get_exception_alert",
        lambda: {
            "wechat_enable": True,
            "wechat_user": "operator",
            "repeat_interval_minutes": 60,
        },
    )

    orchestrator._send_system_exception_alert(
        "进货口4", "camera-4", "视频流异常", "stream closed"
    )
    orchestrator._send_system_exception_alert(
        "进货口4", "camera-4", "启动失败", "ffprobe 探测超时"
    )
    orchestrator._send_system_exception_alert(
        "进货口5", "camera-5", "启动失败", "ffprobe 探测超时"
    )

    assert len(sent) == 2

    clock.now += 3601
    orchestrator._send_system_exception_alert(
        "进货口4", "camera-4", "启动失败", "ffprobe 探测超时"
    )
    assert len(sent) == 3


def test_camera_display_update_does_not_restart_runtime(monkeypatch):
    orchestrator = _orchestrator_without_init()
    restart_calls = []
    refresh_calls = []
    orchestrator.logistics_channel_runtime.refresh_camera_all = refresh_calls.append

    monkeypatch.setattr(
        orchestrator,
        "_restart_or_stop_camera",
        lambda key: restart_calls.append(key),
    )

    orchestrator._on_config_change(
        ConfigChangeEvent(
            change_type="camera_updated",
            camera_id=3,
            camera_name="3_mq7r35ho",
            old_value={
                "name": "物流通道旧",
                "department": "物流部",
                "url": "rtsp://camera/stream",
                "fps": 5,
                "max_restart": 10,
                "enabled": True,
            },
            new_value={
                "name": "物流通道3",
                "department": "物流部新",
                "url": "rtsp://camera/stream",
                "fps": 5,
                "max_restart": 10,
                "enabled": True,
            },
        )
    )

    assert restart_calls == []
    assert refresh_calls == [3]


def test_camera_runtime_update_restarts_runtime(monkeypatch):
    orchestrator = _orchestrator_without_init()
    restart_calls = []

    monkeypatch.setattr(
        orchestrator,
        "_restart_or_stop_camera",
        lambda key: restart_calls.append(key),
    )

    orchestrator._on_config_change(
        ConfigChangeEvent(
            change_type="camera_updated",
            camera_id=3,
            camera_name="3_mq7r35ho",
            old_value={
                "name": "物流通道3",
                "department": "物流部",
                "url": "rtsp://camera/stream",
                "fps": 5,
                "max_restart": 10,
                "enabled": True,
            },
            new_value={
                "name": "物流通道3",
                "department": "物流部",
                "url": "rtsp://camera/new-stream",
                "fps": 5,
                "max_restart": 10,
                "enabled": True,
            },
        )
    )

    assert restart_calls == ["3_mq7r35ho"]


def test_camera_remove_refreshes_logistics_runtime_before_removal(monkeypatch):
    orchestrator = _orchestrator_without_init()
    calls = []
    orchestrator.logistics_channel_runtime.refresh_camera_all = (
        lambda camera_id: calls.append(("refresh", camera_id))
    )
    orchestrator.camera_manager = SimpleNamespace(
        remove_camera_config=lambda name: calls.append(("remove", name))
    )

    orchestrator._on_config_change(
        ConfigChangeEvent(
            change_type="camera_removed",
            camera_id=3,
            camera_name="3_mq7r35ho",
        )
    )

    assert calls == [("refresh", 3), ("remove", "3_mq7r35ho")]


def test_prefixed_logistics_feature_event_reaches_exact_consumer(monkeypatch):
    orchestrator = _orchestrator_without_init()
    calls = []
    orchestrator.consumers = {
        "detect_logistics_single_person": SimpleNamespace(
            update_status=lambda camera_id, enabled: calls.append(
                ("base", camera_id, enabled)
            ),
            update_config=lambda camera_id: calls.append(("base-config", camera_id)),
        ),
        "detect_logistics_single_person_electrical_components": SimpleNamespace(
            update_status=lambda camera_id, enabled: calls.append(
                ("electrical-components", camera_id, enabled)
            ),
            update_config=lambda camera_id: calls.append(
                ("electrical-components-config", camera_id)
            ),
        ),
    }
    restart_calls = []
    monkeypatch.setattr(
        orchestrator,
        "_restart_or_stop_camera",
        lambda key: restart_calls.append(key),
    )

    orchestrator._on_config_change(
        ConfigChangeEvent(
            change_type="detect_logistics_single_person_electrical_components_enabled",
            camera_id=7,
            camera_name="7_logistics",
        )
    )

    assert calls == [("electrical-components", 7, True)]
    assert restart_calls == ["7_logistics"]


def test_logistics_service_feature_event_restarts_orchestrator_with_shm(monkeypatch):
    import platform.logistics_channel.service as service_module

    feature_name = "detect_logistics_single_person"
    orchestrator = _orchestrator_without_init()
    status_calls = []
    restart_calls = []
    orchestrator.consumers = {
        feature_name: SimpleNamespace(
            update_status=lambda camera_id, enabled: status_calls.append(
                (camera_id, enabled)
            ),
            update_config=lambda camera_id: None,
        )
    }
    monkeypatch.setattr(
        orchestrator,
        "_restart_or_stop_camera",
        lambda key: restart_calls.append(key),
    )
    monkeypatch.setattr(
        service_module,
        "config_cache",
        SimpleNamespace(reload=lambda: None),
    )
    monkeypatch.setattr(
        service_module,
        "config_event_bus",
        SimpleNamespace(publish=orchestrator._on_config_change),
    )

    service_module.LogisticsChannelService._notify_channel_changed(
        11,
        feature_name,
        camera_refs=(service_module._CameraRef(7, "7_logistics"),),
        feature_action="enabled",
    )

    assert status_calls == [(7, True)]
    assert restart_calls == ["7_logistics"]


def test_logistics_channel_event_refreshes_runtime():
    orchestrator = _orchestrator_without_init()
    calls = []
    orchestrator.logistics_channel_runtime = SimpleNamespace(
        refresh_channel=lambda feature, channel_id: calls.append((feature, channel_id))
    )

    orchestrator._on_config_change(
        ConfigChangeEvent(
            change_type="logistics_channel_updated",
            new_value={
                "feature_name": "detect_logistics_single_person",
                "channel_id": 12,
            },
        )
    )

    assert calls == [("detect_logistics_single_person", 12)]


def test_logistics_camera_config_event_clears_channel_runtime_state(monkeypatch):
    orchestrator = _orchestrator_without_init()
    calls = []
    feature = "detect_logistics_single_person"
    orchestrator.consumers = {
        feature: SimpleNamespace(update_config=lambda camera_id: calls.append(("consumer", camera_id)))
    }
    orchestrator.logistics_channel_runtime = SimpleNamespace(
        refresh_channel=lambda *_args: None,
        refresh_camera=lambda feature_name, camera_id: calls.append(
            (feature_name, camera_id)
        ),
    )

    orchestrator._on_config_change(
        ConfigChangeEvent(
            change_type=f"{feature}_config_updated",
            camera_id=7,
            camera_name="camera_7",
        )
    )

    assert calls == [(feature, 7), ("consumer", 7)]


def test_start_consumers_injects_runtime_only_into_logistics_features(monkeypatch):
    import platform.orchestrator as orchestrator_module

    created = {}

    class FakeConsumer:
        def __init__(self, **kwargs):
            created[kwargs["spec"].name] = kwargs

        def start(self):
            pass

    logistics = SimpleNamespace(
        name="detect_logistics_single_person",
        required_models=(),
        consumer_cls=FakeConsumer,
    )
    ordinary = SimpleNamespace(
        name="blocks",
        required_models=(),
        consumer_cls=FakeConsumer,
    )
    orchestrator = _orchestrator_without_init()
    orchestrator.logistics_channel_runtime = object()
    orchestrator._send_system_exception_alert = lambda **_kwargs: None
    monkeypatch.setattr(orchestrator_module, "all_specs", lambda: {
        logistics.name: logistics,
        ordinary.name: ordinary,
    })
    monkeypatch.setattr(orchestrator_module.inference_manager, "list_running", lambda: [])
    monkeypatch.setattr(orchestrator_module.inference_manager, "infer_queues", {})
    monkeypatch.setattr(
        orchestrator_module.inference_manager,
        "result_queues",
        {logistics.name: None, ordinary.name: None},
    )

    orchestrator._start_consumers()

    assert created[logistics.name]["logistics_runtime"] is orchestrator.logistics_channel_runtime
    assert "logistics_runtime" not in created[ordinary.name]


def test_start_consumers_skips_persistently_disabled_ordinary_feature(monkeypatch):
    import platform.orchestrator as orchestrator_module

    started = []

    class FakeConsumer:
        def __init__(self, **kwargs):
            self.feature_name = kwargs["spec"].name

        def start(self):
            self.running = True
            started.append(self.feature_name)

    ordinary = SimpleNamespace(
        name="blocks",
        required_models=(),
        consumer_cls=FakeConsumer,
    )
    orchestrator = _orchestrator_without_init()
    orchestrator._feature_states = {ordinary.name: False}
    monkeypatch.setattr(orchestrator_module, "all_specs", lambda: {ordinary.name: ordinary})
    monkeypatch.setattr(orchestrator_module.inference_manager, "list_running", lambda: [])
    monkeypatch.setattr(orchestrator_module.inference_manager, "infer_queues", {})
    monkeypatch.setattr(orchestrator_module.inference_manager, "result_queues", {ordinary.name: None})

    orchestrator._start_consumers()

    assert started == []
    assert orchestrator.consumers == {}


def test_feature_stop_persists_state_and_keeps_shared_camera_running(monkeypatch):
    import platform.orchestrator as orchestrator_module

    stopped = []
    persisted = []
    camera_calls = []
    blocks = SimpleNamespace(name="blocks", display_name="区域入侵检测")
    face = SimpleNamespace(name="detect_face", display_name="人脸检测")
    orchestrator = _orchestrator_without_init()
    orchestrator._feature_states = {"blocks": True, "detect_face": True}
    orchestrator.consumers = {
        "blocks": SimpleNamespace(running=True, stop=lambda: stopped.append("blocks")),
        "detect_face": SimpleNamespace(running=True),
    }
    orchestrator.camera_manager = SimpleNamespace(
        update_camera_config=lambda name, cfg: camera_calls.append(("update", name, cfg["enable"])),
        is_running=lambda _name: True,
        start_camera=lambda name: camera_calls.append(("start", name)),
        stop_camera=lambda name: camera_calls.append(("stop", name)),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "all_specs",
        lambda: {"blocks": blocks, "detect_face": face},
    )
    monkeypatch.setattr(
        orchestrator_module.system_config_service,
        "save_feature_runtime_state",
        lambda name, enabled: persisted.append((name, enabled)),
    )
    monkeypatch.setattr(
        orchestrator_module.camera_service,
        "list_cameras",
        lambda: [{
            "shm_name": "camera_1",
            "enabled": True,
            "functions": {"blocks": True, "detect_face": True},
        }],
    )
    monkeypatch.setattr(
        orchestrator,
        "_camera_runtime_config",
        lambda _key: {"shm_name": "camera_1", "enable": True},
    )

    result = orchestrator.set_feature_enabled("blocks", False)

    assert result["state"] == "stopped"
    assert stopped == ["blocks"]
    assert persisted == [("blocks", False)]
    assert camera_calls == [("update", "camera_1", True)]


def test_logistics_feature_cannot_use_global_runtime_switch():
    orchestrator = _orchestrator_without_init()

    try:
        orchestrator.set_feature_enabled("detect_logistics_single_person", False)
    except ValueError as exc:
        assert "通道管理" in str(exc)
    else:
        raise AssertionError("物流检测不应允许使用全局能力开关")


def test_stop_continues_all_cleanup_after_logistics_runtime_failure(monkeypatch, caplog):
    import core.db as db_module
    import platform.orchestrator as orchestrator_module

    calls = []
    orchestrator = _orchestrator_without_init()
    orchestrator._started = True
    orchestrator.consumers = {
        "detect_test": SimpleNamespace(stop=lambda: calls.append("consumer"))
    }

    def fail_logistics_stop():
        calls.append("logistics")
        raise RuntimeError("巡检线程停止超时")

    orchestrator.logistics_channel_runtime = SimpleNamespace(stop=fail_logistics_stop)
    orchestrator._horn_dict = {
        1: SimpleNamespace(stop_heartbeat=lambda: calls.append("horn"))
    }
    orchestrator.camera_manager = SimpleNamespace(stop_all=lambda: calls.append("camera"))
    monkeypatch.setattr(
        orchestrator_module.inference_manager,
        "stop_all",
        lambda: calls.append("inference"),
    )
    monkeypatch.setattr(
        orchestrator_module.violation_writer,
        "stop",
        lambda: calls.append("violation"),
    )
    monkeypatch.setattr(
        orchestrator_module.frame_reader_registry,
        "stop_all",
        lambda: calls.append("frame_reader"),
    )
    monkeypatch.setattr(db_module, "dispose", lambda: calls.append("db"))

    orchestrator.stop()

    assert calls == [
        "consumer",
        "logistics",
        "inference",
        "horn",
        "violation",
        "frame_reader",
        "camera",
        "db",
    ]
    assert orchestrator.consumers == {}
    assert orchestrator._horn_dict == {}
    assert orchestrator._started is False
    assert "停止物流通道运行时失败，将继续清理其余资源" in caplog.text
    assert "巡检线程停止超时" in caplog.text
