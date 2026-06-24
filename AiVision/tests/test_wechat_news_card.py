from types import SimpleNamespace

import numpy as np

from core.alarm.dispatcher import AlarmDispatcher, AlarmRequest
from core.alarm.wechat import WeChatNotifier


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_wechat_alarm_uses_single_news_card(monkeypatch):
    posts = []
    notifier = WeChatNotifier(corp_id="corp", corp_secret="secret", agent_id=100)
    monkeypatch.setattr(notifier, "_get_token", lambda: "token")
    monkeypatch.setattr(
        "core.alarm.wechat.requests.post",
        lambda *args, **kwargs: posts.append(kwargs["json"]) or FakeResponse({"errcode": 0}),
    )

    notifier.send(
        feature_name="blocks",
        camera_name="后大门",
        image_jpeg_bytes=b"unused-for-news",
        recipients="zhangsan",
        image_url="https://aicv.fudar.com/api/aivision/alarms/42/image",
        detail_url="https://aicv.fudar.com/?page=alarms&alarmId=aivision%3A42",
    )

    assert len(posts) == 1
    payload = posts[0]
    assert payload["msgtype"] == "news"
    assert payload["touser"] == "zhangsan"
    assert payload["agentid"] == 100
    article = payload["news"]["articles"][0]
    assert article["title"] == "区域入侵告警"
    assert article["description"] == "后大门"
    assert article["url"] == "https://aicv.fudar.com/?page=alarms&alarmId=aivision%3A42"
    assert article["picurl"] == "https://aicv.fudar.com/api/aivision/alarms/42/image"


class FakeViolationWriter:
    def __init__(self):
        self.saved = []
        self.enqueued = []

    def save_now(self, *, frame, violation_type, camera_no):
        self.saved.append((violation_type, camera_no, frame.shape))
        return SimpleNamespace(id=42)

    def enqueue(self, *, frame, violation_type, camera_no):
        self.enqueued.append((violation_type, camera_no, frame.shape))


class FakeWeChat:
    def __init__(self):
        self.sent = []

    def send(self, **kwargs):
        self.sent.append(kwargs)


def test_dispatcher_saves_record_before_wechat_card():
    dispatcher = AlarmDispatcher()
    writer = FakeViolationWriter()
    wechat = FakeWeChat()
    dispatcher.horn_dict = {}
    dispatcher.wechat = wechat
    dispatcher.violation_writer = writer
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    dispatcher._execute(
        AlarmRequest(
            feature_name="blocks",
            camera_id=7,
            camera_name="后大门",
            frame=frame,
            violation_type=1,
            alarm_config={"wechat": {"enable": True, "parm": {"user": "zhangsan"}}},
            camera_key="gate_7",
        )
    )
    req, user, record = dispatcher._wechat_queue.get_nowait()

    assert writer.saved == [(1, "gate_7", (8, 8, 3))]
    assert user == "zhangsan"
    assert record.id == 42
    assert req.camera_name == "后大门"


def test_dispatcher_builds_public_image_and_detail_urls(monkeypatch):
    dispatcher = AlarmDispatcher()
    monkeypatch.setattr("core.alarm.dispatcher.settings.alarm.wechat_card_base_url", "https://aicv.fudar.com/")

    image_url, detail_url = dispatcher._alarm_card_urls(42)

    assert image_url == "https://aicv.fudar.com/api/public/aivision/alarms/42/image"
    assert detail_url == "https://aicv.fudar.com/?page=alarms&alarmId=aivision%3A42"


def test_dispatcher_keeps_async_writer_when_wechat_disabled():
    dispatcher = AlarmDispatcher()
    writer = FakeViolationWriter()
    dispatcher.horn_dict = {}
    dispatcher.wechat = FakeWeChat()
    dispatcher.violation_writer = writer
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    dispatcher._execute(
        AlarmRequest(
            feature_name="blocks",
            camera_id=7,
            camera_name="后大门",
            frame=frame,
            violation_type=1,
            alarm_config={"wechat": {"enable": False, "parm": {"user": "zhangsan"}}},
            camera_key="gate_7",
        )
    )

    assert writer.saved == []
    assert writer.enqueued == [(1, "gate_7", (8, 8, 3))]
