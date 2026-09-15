"""新通知路径仍服务于 API 和运行调度的系统异常通知；全部模拟发送。"""
from queue import Queue
from types import SimpleNamespace

import pytest

from AiVision.alarms.notifications.wechat import WeChatNotifier
from AiVision.alarms.notifications import wechat
from AiVision.api import app as api_app
from AiVision.platform import orchestrator


@pytest.fixture
def system_notifications(monkeypatch):
    messages = []
    clock = [1_000_000.]
    config = {"wechat_enable": True, "wechat_user": " test-recipient ", "repeat_interval_minutes": 5}
    monkeypatch.setattr(wechat.settings.alarm, "wechat_enable", True)
    monkeypatch.setattr(WeChatNotifier, "_get_token", lambda self: "test-notification-token")
    monkeypatch.setattr(wechat.time, "time", lambda: clock[0])
    monkeypatch.setattr(wechat.time, "strftime", lambda *_args: "2026-09-15 12:00:00")
    monkeypatch.setattr(api_app.system_config_service, "get_exception_alert", lambda: config)

    def post(url, **kwargs):
        assert url == "https://qyapi.weixin.qq.com/cgi-bin/message/send"
        messages.append(kwargs["json"])
        return SimpleNamespace(status_code=200, json=lambda: {"errcode": 0})

    monkeypatch.setattr(wechat.requests, "post", post)
    return SimpleNamespace(messages=messages, clock=clock, config=config)


def test_api_exception_keeps_markdown_recipients_and_cooldown(system_notifications, monkeypatch):
    captured = system_notifications
    started = []

    class InlineThread:
        def __init__(self, *, target, daemon, name):
            self.target, self.daemon, self.name = target, daemon, name

        def start(self):
            started.append((self.name, self.daemon))
            self.target()

    monkeypatch.setattr(api_app.threading, "Thread", InlineThread)
    monkeypatch.setattr(api_app, "_api_exception_alerts", {})
    api_app._send_api_exception_alert("/api/test", "test failure")
    api_app._send_api_exception_alert("/api/test", "repeat failure")
    assert started == [("api-exception-alert", True)]
    assert len(captured.messages) == 1
    message = captured.messages[0]
    assert message["msgtype"] == "markdown" and message["touser"] == "test-recipient"
    assert message["markdown"]["content"] == (
        "AiVision 系统异常\n**对象**: API\n**标识**: /api/test\n"
        "**类型**: API 未处理异常\n**详情**: test failure\n**时间**: 2026-09-15 12:00:00\n"
    )
    captured.clock[0] += 300
    api_app._send_api_exception_alert("/api/test", "after cooldown")
    assert len(captured.messages) == 2
    captured.config["wechat_enable"] = False
    captured.clock[0] += 300
    api_app._send_api_exception_alert("/api/test", "disabled")
    assert len(captured.messages) == 2


def test_runtime_exception_keeps_grouped_cooldown_and_separate_targets(system_notifications):
    captured = system_notifications
    runtime = orchestrator.Orchestrator(mp_manager=SimpleNamespace(Queue=Queue))
    runtime._wechat = WeChatNotifier(corp_id="test-corp", corp_secret="test-secret", agent_id=1)
    runtime._send_system_exception_alert("camera one", "camera-1", "视频流异常", "frame missing")
    runtime._send_system_exception_alert("camera one", "camera-1", "画面停更 30s", "same group")
    assert len(captured.messages) == 1
    message = captured.messages[0]
    assert message["msgtype"] == "markdown" and message["touser"] == "test-recipient"
    assert message["markdown"]["content"] == (
        "AiVision 系统异常\n**对象**: camera one\n**标识**: camera-1\n"
        "**类型**: 视频流异常\n**详情**: frame missing\n**时间**: 2026-09-15 12:00:00\n"
    )
    runtime._send_system_exception_alert("camera two", "camera-2", "视频流异常", "independent")
    assert len(captured.messages) == 2
    captured.clock[0] += 300
    runtime._send_system_exception_alert("camera one", "camera-1", "视频流异常", "after cooldown")
    assert len(captured.messages) == 3
    captured.config["wechat_user"] = " "
    runtime._send_system_exception_alert("camera three", "camera-3", "视频流异常", "no recipient")
    assert len(captured.messages) == 3
