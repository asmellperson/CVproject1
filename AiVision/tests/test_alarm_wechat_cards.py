"""企业微信卡片覆盖全部报警类型，并与独立通道冷却组合验证。"""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest


@pytest.fixture
def alarm_modules(monkeypatch, tmp_path):
    # 使用本地占位配置，测试不读取部署凭据，也不连接数据库或企业微信。
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1",
        "MYSQL_DB_USER": "alarm_test",
        "MYSQL_DB_PASSWORD": "alarm_test",
        "MYSQL_DB_NAME": "alarm_test",
        "DATA_PATH": str(tmp_path),
        "AUTH_SECRET": "alarm-card-test-signing-key-00000000",
    }.items():
        monkeypatch.setenv(name, value)

    from AiVision.alarms import dispatcher
    from AiVision.alarms.notifications import wechat
    from AiVision.features.registry import all_specs

    monkeypatch.setattr(dispatcher.settings.alarm, "wechat_card_base_url", "https://alarm.example.test")
    features = {alarm_type: spec.name for spec in all_specs().values() for alarm_type in spec.alarm_types}
    return dispatcher, wechat, features


def make_request(alarm_modules, violation_type=3, *, sql_enabled=True, wechat_interval=10, **kwargs):
    dispatcher, _, features = alarm_modules
    return dispatcher.AlarmRequest(
        feature_name=features[violation_type],
        camera_id=1,
        camera_name="测试摄像头",
        camera_key="camera_1",
        frame=np.zeros((4, 4, 3), dtype=np.uint8),
        violation_type=violation_type,
        department="general_electric",
        cooldown_subject_type="camera",
        cooldown_subject_id="1",
        alarm_config={
            "sql": {"enable": sql_enabled},
            "wechat": {"enable": True, "interval": wechat_interval, "parm": {"user": "test-user"}},
        },
        **kwargs,
    )


def make_dispatcher(alarm_modules):
    dispatcher_module, wechat_module, _ = alarm_modules
    dispatcher = dispatcher_module.AlarmDispatcher()
    dispatcher.wechat = wechat_module.WeChatNotifier(corp_id="test-corp", corp_secret="test-secret", agent_id=1)
    dispatcher.wechat._get_token = Mock(return_value="test-token")
    dispatcher.violation_writer = SimpleNamespace(
        save_now=Mock(return_value=SimpleNamespace(id=101)),
        enqueue=Mock(return_value=True),
    )
    dispatcher.evidence_recorder = Mock()
    dispatcher.evidence_recorder.start_alarm.return_value = "/test/alarm.mp4"
    return dispatcher


def send_one(dispatcher, alarm_modules, monkeypatch):
    _, wechat, _ = alarm_modules

    def post(*args, **kwargs):
        dispatcher._wechat_stop_event.set()
        return SimpleNamespace(status_code=200, json=lambda: {"errcode": 0})

    request = Mock(side_effect=post)
    monkeypatch.setattr(wechat.requests, "post", request)
    dispatcher._wechat_stop_event.clear()
    dispatcher._wechat_loop()
    request.assert_called_once()
    return request.call_args.kwargs["json"]


@pytest.mark.parametrize("violation_type", range(1, 18))
@pytest.mark.parametrize("sql_enabled", [True, False])
def test_each_alarm_push_links_to_its_current_record(alarm_modules, monkeypatch, violation_type, sql_enabled):
    from AiVision.alarms.types import VIOLATION_TYPE_META

    dispatcher = make_dispatcher(alarm_modules)
    request = make_request(alarm_modules, violation_type, sql_enabled=sql_enabled)

    assert dispatcher.maybe_dispatch(request)
    payload = send_one(dispatcher, alarm_modules, monkeypatch)

    assert payload["msgtype"] == "news"
    assert payload["touser"] == "test-user"
    article, = payload["news"]["articles"]
    assert article["title"] == f"{VIOLATION_TYPE_META[violation_type]['label']}告警"
    assert article["url"] == "https://alarm.example.test/?page=alarms&alarmId=101"
    assert article["picurl"].startswith("https://alarm.example.test/api/public/alarms/101/image")
    if request.feature_name == "detect_human":
        assert "?thumbnail_token=" in article["picurl"]
    dispatcher.violation_writer.save_now.assert_called_once()
    assert dispatcher.violation_writer.save_now.call_args.kwargs["frame"] is request.frame
    dispatcher.violation_writer.enqueue.assert_not_called()


def test_wechat_due_during_record_cooldown_uses_new_record(alarm_modules, monkeypatch):
    dispatcher_module, _, _ = alarm_modules
    dispatcher = make_dispatcher(alarm_modules)
    dispatcher.violation_writer.save_now.side_effect = [SimpleNamespace(id=101), SimpleNamespace(id=102)]
    request = make_request(alarm_modules)
    monkeypatch.setattr(dispatcher_module.time, "monotonic", lambda: 100)
    assert dispatcher.maybe_dispatch(request, alarm_interval=3600)
    send_one(dispatcher, alarm_modules, monkeypatch)

    monkeypatch.setattr(dispatcher_module.time, "monotonic", lambda: 110)
    assert dispatcher.maybe_dispatch(request, alarm_interval=3600)
    payload = send_one(dispatcher, alarm_modules, monkeypatch)

    article, = payload["news"]["articles"]
    assert article["url"].endswith("alarmId=102")
    assert "/102/image" in article["picurl"]
    assert dispatcher._last_alarm[("camera", "1", 3, "sql")] == 100
    assert dispatcher._last_alarm[("camera", "1", 3, "wechat")] == 110


def test_horn_only_does_not_create_card_records(alarm_modules):
    dispatcher = make_dispatcher(alarm_modules)
    dispatcher.horn_runtime_manager = Mock()
    request = make_request(alarm_modules)
    request.alarm_config["horn"] = {"enable": True, "parm": {"horn_id": 1, "horn_event_id": 1}}

    assert dispatcher.maybe_dispatch(request, channels={"horn"})

    dispatcher.horn_runtime_manager.enqueue_play.assert_called_once_with(1, 1)
    dispatcher.violation_writer.save_now.assert_not_called()
    dispatcher.violation_writer.enqueue.assert_not_called()
    dispatcher.evidence_recorder.start_alarm.assert_not_called()
    assert dispatcher._wechat_queue.empty()


def test_record_only_remains_asynchronous(alarm_modules):
    dispatcher = make_dispatcher(alarm_modules)
    request = make_request(alarm_modules)

    assert dispatcher.maybe_dispatch(request, channels={"sql"})

    dispatcher.violation_writer.enqueue.assert_called_once()
    dispatcher.violation_writer.save_now.assert_not_called()
    assert dispatcher._wechat_queue.empty()


@pytest.mark.parametrize("save_result", [None, RuntimeError("test storage unavailable")])
def test_card_storage_failure_does_not_break_horn(alarm_modules, monkeypatch, save_result):
    dispatcher = make_dispatcher(alarm_modules)
    dispatcher.horn_runtime_manager = Mock()
    if isinstance(save_result, Exception):
        dispatcher.violation_writer.save_now.side_effect = save_result
    else:
        dispatcher.violation_writer.save_now.return_value = save_result
    request = make_request(alarm_modules)
    request.alarm_config["horn"] = {"enable": True, "parm": {"horn_id": 1, "horn_event_id": 1}}

    assert dispatcher.maybe_dispatch(request)
    payload = send_one(dispatcher, alarm_modules, monkeypatch)

    dispatcher.horn_runtime_manager.enqueue_play.assert_called_once_with(1, 1)
    assert payload["msgtype"] == "markdown"
    assert "测试摄像头" in payload["markdown"]["content"]


def test_fence_camera_cooldown_survives_event_changes(alarm_modules, monkeypatch):
    dispatcher_module, _, _ = alarm_modules
    dispatcher = make_dispatcher(alarm_modules)
    callback = Mock()
    request = make_request(alarm_modules, 16, notification_cooldown_subject=("fence_camera", "general_electric:1"),
                           on_notification_enqueued=callback)
    monkeypatch.setattr(dispatcher_module.time, "monotonic", lambda: 100)
    assert dispatcher.maybe_dispatch(request, alarm_interval=3600)
    send_one(dispatcher, alarm_modules, monkeypatch)

    request.cooldown_subject_id = "another-event"
    monkeypatch.setattr(dispatcher_module.time, "monotonic", lambda: 101)
    assert not dispatcher.maybe_dispatch(request, alarm_interval=3600)
    dispatcher.violation_writer.save_now.assert_called_once()
    assert [call.args[0] for call in callback.call_args_list] == ["sql", "wechat"]
