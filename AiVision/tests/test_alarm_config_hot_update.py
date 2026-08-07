from types import SimpleNamespace

import numpy as np

import features._base.consumer as consumer_module
from core.alarm.dispatcher import AlarmDispatcher, AlarmRequest
from features._base.consumer import BaseFunctionConsumer


class DummyConsumer(BaseFunctionConsumer):
    def _process(self, roi_list, camera_id):
        return []

    def post_process(self, camera_id, result):
        return None


class FakeConfigCache:
    def get_function_config(self, camera_id: int, feature_name: str):
        assert camera_id == 7
        assert feature_name == "detect_test"
        return {
            "camera_id": camera_id,
            "enable": True,
            "shm_name": "camera_7",
            "wechat_enable": True,
            "wechat_user": "zhangsan",
        }


class FakeAlarmDispatcher:
    def __init__(self):
        self.reset_calls = []

    def reset_cooldown(self, camera_id: int, feature_name: str):
        self.reset_calls.append((camera_id, feature_name))


def test_update_config_resets_alarm_cooldown(monkeypatch):
    dispatcher = FakeAlarmDispatcher()
    monkeypatch.setattr(consumer_module, "config_cache", FakeConfigCache())
    monkeypatch.setattr(consumer_module, "alarm_dispatcher", dispatcher)

    consumer = DummyConsumer(
        spec=SimpleNamespace(name="detect_test"),
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _name: True,
    )

    consumer.update_config(7)

    assert consumer.config_cache[7]["wechat_user"] == "zhangsan"
    assert dispatcher.reset_calls == [(7, "detect_test")]


def test_dispatcher_cooldown_uses_logistics_channel_subject(monkeypatch):
    dispatcher = AlarmDispatcher()
    executed = []
    monkeypatch.setattr(dispatcher, "_execute", lambda request: executed.append(request))
    monkeypatch.setattr("core.alarm.dispatcher.time.time", lambda: 100.0)

    def request(camera_id):
        return AlarmRequest(
            feature_name="detect_logistics_single_person",
            camera_id=camera_id,
            camera_name="物流通道一",
            frame=np.zeros((2, 2, 3), np.uint8),
            violation_type=6,
            alarm_config={},
            subject_type="logistics_channel",
            subject_id="3",
            subject_name="物流通道一",
        )

    assert dispatcher.maybe_dispatch(request(10), alarm_interval=5.0) is True
    assert dispatcher.maybe_dispatch(request(11), alarm_interval=5.0) is False
    dispatcher.reset_subject_cooldown(
        "logistics_channel",
        "3",
        "detect_logistics_single_person",
    )
    assert dispatcher.maybe_dispatch(request(11), alarm_interval=5.0) is True
    assert len(executed) == 2


def test_dispatcher_forwards_subject_metadata_to_violation_writer():
    calls = []

    class Writer:
        def enqueue(self, **kwargs):
            calls.append(kwargs)

    dispatcher = AlarmDispatcher()
    dispatcher.violation_writer = Writer()
    dispatcher._execute(
        AlarmRequest(
            feature_name="detect_logistics_single_person",
            camera_id=3,
            camera_name="物流通道一",
            frame=np.zeros((2, 2, 3), np.uint8),
            violation_type=6,
            alarm_config={},
            subject_type="logistics_channel",
            subject_id="3",
            subject_name="物流通道一",
            reason="empty",
            metadata={"camera_counts": {"10": 0}},
        )
    )

    assert calls[0]["subject_type"] == "logistics_channel"
    assert calls[0]["subject_id"] == "3"
    assert calls[0]["subject_name"] == "物流通道一"
    assert calls[0]["reason"] == "empty"
    assert calls[0]["event_metadata"] == {"camera_counts": {"10": 0}}


def test_dispatcher_respects_explicit_sql_channel_switch_and_keeps_legacy_default():
    calls = []

    class Writer:
        def enqueue(self, **kwargs):
            calls.append(kwargs)

    def request(alarm_config):
        return AlarmRequest(
            feature_name="detect_logistics_single_person",
            camera_id=3,
            camera_name="物流通道一",
            frame=np.zeros((2, 2, 3), np.uint8),
            violation_type=6,
            alarm_config=alarm_config,
        )

    dispatcher = AlarmDispatcher()
    dispatcher.violation_writer = Writer()
    dispatcher._execute(request({"sql": {"enable": False}}))
    assert calls == []

    dispatcher._execute(request({"sql": {"enable": True}}))
    dispatcher._execute(request({}))
    assert len(calls) == 2
