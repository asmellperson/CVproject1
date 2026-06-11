from types import SimpleNamespace

import features._base.consumer as consumer_module
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
