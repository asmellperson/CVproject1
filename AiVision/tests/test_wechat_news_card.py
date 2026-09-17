# 文件说明：包含企业微信通知的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import logging
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from AiVision.alarms.dispatcher import AlarmDispatcher, AlarmRequest
from AiVision.alarms.notifications import wechat as wechat_module
from AiVision.alarms.notifications.wechat import WeChatNotifier, _EVENT_DISPLAY


# 功能：定义 `FakeResponse` 类，封装企业微信通知相关的状态、约束与操作
# 参数：
#   - `payload`（未显式标注）：接口或事件携带的业务数据
# 返回：FakeResponse；返回新建的 `FakeResponse` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_wechat_news_card.py` 的 `test_wechat_alarm_uses_single_news_card` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeResponse:
    # 功能：初始化或配置 `__init__` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `payload`（未显式标注）：接口或事件携带的业务数据
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    # 功能：实现 `json` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/alarms/devices/horn.py` 的 `Horn::connect` 调用本符号；`AiVision/alarms/notifications/wechat.py` 的 `WeChatNotifier::_get_token`
    #         调用本符号；`AiVision/alarms/notifications/wechat.py` 的 `WeChatNotifier::_upload_image` 调用本符号；`AiVision/alarms/notifications/wechat.py` 的
    #         `WeChatNotifier::_send_news_card` 调用本符号；另有 8 处静态调用
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def json(self):
        return self._payload


# 功能：验证 `test_wechat_human_alarm_uses_personnel_violation_dwell_name` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_wechat_human_alarm_uses_personnel_violation_dwell_name():
    assert _EVENT_DISPLAY["detect_human"] == "人员违规逗留检测"


# 功能：验证 `test_wechat_alarm_uses_single_news_card` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`WeChatNotifier`、`monkeypatch.setattr`、`posts.append`、`FakeResponse`、`notifier.send`、`len`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
def test_wechat_alarm_uses_single_news_card(monkeypatch):
    posts = []
    notifier = WeChatNotifier(corp_id="corp", corp_secret="secret", agent_id=100)
    monkeypatch.setattr(notifier, "_get_token", lambda: "token")
    monkeypatch.setattr(
        "AiVision.alarms.notifications.wechat.requests.post",
        lambda *args, **kwargs: posts.append(kwargs["json"]) or FakeResponse({"errcode": 0}),
    )

    sent = notifier.send(
        feature_name="blocks",
        camera_name="后大门",
        recipients="zhangsan",
        image_url="https://aicv.fudar.com/api/alarms/42/image",
        detail_url="https://aicv.fudar.com/?page=alarms&alarmId=aivision%3A42",
    )

    assert sent is True
    assert len(posts) == 1
    payload = posts[0]
    assert payload["msgtype"] == "news"
    assert payload["touser"] == "zhangsan"
    assert payload["agentid"] == 100
    article = payload["news"]["articles"][0]
    assert article["title"] == "区域入侵告警"
    assert article["description"] == "后大门"
    assert article["url"] == "https://aicv.fudar.com/?page=alarms&alarmId=aivision%3A42"
    assert article["picurl"] == "https://aicv.fudar.com/api/alarms/42/image"


def test_wechat_alarm_skips_when_card_urls_are_missing(monkeypatch, caplog):
    notifier = WeChatNotifier(corp_id="corp", corp_secret="secret", agent_id=100)
    monkeypatch.setattr(
        notifier,
        "_get_token",
        lambda: pytest.fail("missing card URLs should skip before requesting a token"),
    )

    with caplog.at_level(logging.WARNING):
        sent = notifier.send(
            feature_name="blocks",
            camera_name="后大门",
            recipients="zhangsan",
            image_url="",
            detail_url="",
        )

    assert sent is False
    assert "image_url, detail_url" in caplog.text


def test_wechat_alarm_reports_news_send_failure(monkeypatch, caplog):
    notifier = WeChatNotifier(corp_id="corp", corp_secret="secret", agent_id=100)
    monkeypatch.setattr(notifier, "_get_token", lambda: "token")
    monkeypatch.setattr(
        wechat_module.requests,
        "post",
        lambda *_args, **_kwargs: FakeResponse({}, status_code=500),
    )

    with caplog.at_level(logging.WARNING):
        sent = notifier.send(
            feature_name="blocks",
            camera_name="后大门",
            recipients="zhangsan",
            image_url="https://aicv.fudar.com/api/alarms/42/image",
            detail_url="https://aicv.fudar.com/?page=alarms&alarmId=aivision%3A42",
        )

    assert sent is False
    assert "发送图文 HTTP 失败" in caplog.text


def test_wechat_send_text_remains_available_for_system_notifications(monkeypatch):
    posts = []
    notifier = WeChatNotifier(corp_id="corp", corp_secret="secret", agent_id=100)
    monkeypatch.setattr(notifier, "_get_token", lambda: "token")
    monkeypatch.setattr(
        wechat_module.requests,
        "post",
        lambda *_args, **kwargs: posts.append(kwargs["json"]) or FakeResponse({"errcode": 0}),
    )

    notifier.send_text("系统异常", "zhangsan")

    assert len(posts) == 1
    assert posts[0]["msgtype"] == "markdown"
    assert posts[0]["markdown"]["content"] == "系统异常"


def test_wechat_token_cache_uses_expiry_and_refresh_margin(monkeypatch):
    notifier = WeChatNotifier(corp_id="corp", corp_secret="secret", agent_id=100)
    now = [100.0]
    responses = iter(
        (
            FakeResponse({"errcode": 0, "access_token": "token-1", "expires_in": 7200}),
            FakeResponse({"errcode": 0, "access_token": "token-2", "expires_in": 7200}),
        )
    )
    calls = []
    monkeypatch.setattr(wechat_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        wechat_module.requests,
        "get",
        lambda *args, **kwargs: calls.append((args, kwargs)) or next(responses),
    )

    assert notifier._get_token() == "token-1"
    now[0] = 7239.0
    assert notifier._get_token() == "token-1"
    now[0] = 7240.0
    assert notifier._get_token() == "token-2"
    assert len(calls) == 2


def test_wechat_token_cache_prevents_concurrent_refresh(monkeypatch):
    notifier = WeChatNotifier(corp_id="corp", corp_secret="secret", agent_id=100)
    request_started = threading.Event()
    release_request = threading.Event()
    calls = []
    results = []

    def fake_get(*_args, **_kwargs):
        calls.append("gettoken")
        request_started.set()
        assert release_request.wait(timeout=1)
        return FakeResponse({"errcode": 0, "access_token": "shared", "expires_in": 7200})

    monkeypatch.setattr(wechat_module.requests, "get", fake_get)
    first = threading.Thread(target=lambda: results.append(notifier._get_token()))
    second = threading.Thread(target=lambda: results.append(notifier._get_token()))
    first.start()
    assert request_started.wait(timeout=1)
    second.start()
    release_request.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert calls == ["gettoken"]
    assert results == ["shared", "shared"]


def test_wechat_token_failures_have_distinct_logs(monkeypatch, caplog):
    missing = WeChatNotifier(corp_id="corp", corp_secret="secret", agent_id=100)
    missing.corp_id = ""
    missing.corp_secret = ""
    with caplog.at_level(logging.WARNING):
        assert missing._get_token() is None
    assert "凭据未配置" in caplog.text

    caplog.clear()
    network = WeChatNotifier(corp_id="corp", corp_secret="secret", agent_id=100)
    monkeypatch.setattr(
        wechat_module.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            wechat_module.requests.ConnectionError("offline")
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert network._get_token() is None
    assert "网络失败" in caplog.text

    caplog.clear()
    business = WeChatNotifier(corp_id="corp", corp_secret="secret", agent_id=100)
    monkeypatch.setattr(
        wechat_module.requests,
        "get",
        lambda *_args, **_kwargs: FakeResponse({"errcode": 40013, "errmsg": "invalid corpid"}),
    )
    with caplog.at_level(logging.WARNING):
        assert business._get_token() is None
    assert "业务失败" in caplog.text


def test_dispatcher_wechat_thread_lifecycle_is_idempotent():
    dispatcher = AlarmDispatcher()
    dispatcher.configure(None, None, None)
    first_thread = dispatcher._wechat_thread

    dispatcher.configure(None, None, None)
    assert dispatcher._wechat_thread is first_thread
    assert first_thread is not None and first_thread.is_alive()

    dispatcher.stop()
    assert not first_thread.is_alive()

    dispatcher.configure(None, None, None)
    second_thread = dispatcher._wechat_thread
    assert second_thread is not None and second_thread is not first_thread
    assert second_thread.is_alive()
    dispatcher.stop()


# 功能：定义 `FakeViolationWriter` 类，封装企业微信通知相关的状态、约束与操作
# 参数：无。
# 返回：FakeViolationWriter；返回新建的 `FakeViolationWriter` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_wechat_news_card.py` 的 `test_dispatcher_saves_record_before_wechat_card`
#         实例化本符号；`AiVision/tests/test_wechat_news_card.py` 的 `test_dispatcher_persists_card_record_when_sql_is_disabled`
#         实例化本符号；`AiVision/tests/test_wechat_news_card.py` 的 `test_dispatcher_keeps_async_writer_when_wechat_disabled` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeViolationWriter:
    # 功能：初始化或配置 `__init__` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.saved = []
        self.enqueued = []

    # 功能：更新或保存 `save_now` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame`（未显式标注）：待处理的视频图像帧
    #   - `violation_type`（未显式标注）：`violation_type` 对应的业务输入值
    #   - `camera_no`（未显式标注）：`camera_no` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.saved.append`、`SimpleNamespace`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def save_now(self, *, frame, violation_type, camera_no):
        self.saved.append((violation_type, camera_no, frame.shape))
        return SimpleNamespace(id=42)

    # 功能：实现 `enqueue` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame`（未显式标注）：待处理的视频图像帧
    #   - `violation_type`（未显式标注）：`violation_type` 对应的业务输入值
    #   - `camera_no`（未显式标注）：`camera_no` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.enqueued.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def enqueue(self, *, frame, violation_type, camera_no):
        self.enqueued.append((violation_type, camera_no, frame.shape))


# 功能：定义 `FakeWeChat` 类，封装企业微信通知相关的状态、约束与操作
# 参数：无。
# 返回：FakeWeChat；返回新建的 `FakeWeChat` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_wechat_news_card.py` 的 `test_dispatcher_saves_record_before_wechat_card`
#         实例化本符号；`AiVision/tests/test_wechat_news_card.py` 的 `test_dispatcher_persists_card_record_when_sql_is_disabled`
#         实例化本符号；`AiVision/tests/test_wechat_news_card.py` 的 `test_dispatcher_keeps_async_writer_when_wechat_disabled` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeWeChat:
    # 功能：初始化或配置 `__init__` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.sent = []

    # 功能：发送或分发 `send` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.sent.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def send(self, **kwargs):
        self.sent.append(kwargs)


# 功能：验证 `test_dispatcher_saves_record_before_wechat_card` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AlarmDispatcher`、`FakeViolationWriter`、`FakeWeChat`、`np.zeros`、`dispatcher._execute`、`AlarmRequest`、`dispatcher._wechat_queue.get_nowait`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息；可能读取或修改数据库事务。
def test_dispatcher_saves_record_before_wechat_card():
    dispatcher = AlarmDispatcher()
    writer = FakeViolationWriter()
    wechat = FakeWeChat()
    dispatcher.horn_runtime_manager = None
    dispatcher.wechat = wechat
    dispatcher.violation_writer = writer
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    dispatcher._execute(
        AlarmRequest(
            feature_name="blocks", department='research_institute',
            cooldown_subject_type="camera", cooldown_subject_id="7",
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


# 功能：验证 `test_dispatcher_persists_card_record_when_sql_is_disabled` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AlarmDispatcher`、`FakeViolationWriter`、`FakeWeChat`、`np.zeros`、`dispatcher._execute`、`AlarmRequest`、`dispatcher._wechat_queue.get_nowait`、`dispatcher._alarm_card_urls`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息；可能读取或修改数据库事务。
def test_dispatcher_persists_card_record_when_sql_is_disabled():
    dispatcher = AlarmDispatcher()
    writer = FakeViolationWriter()
    dispatcher.horn_runtime_manager = None
    dispatcher.wechat = FakeWeChat()
    dispatcher.violation_writer = writer
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    dispatcher._execute(
        AlarmRequest(
            feature_name="detect_human", department='general_electric',
            cooldown_subject_type="camera", cooldown_subject_id="7",
            camera_id=7,
            camera_name="后大门",
            frame=frame,
            violation_type=5,
            alarm_config={
                "sql": {"enable": False, "parm": {}},
                "wechat": {"enable": True, "parm": {"user": "zhangsan"}},
            },
            camera_key="gate_7",
        )
    )

    _request, user, record = dispatcher._wechat_queue.get_nowait()
    assert writer.saved == [(5, "gate_7", (8, 8, 3))]
    assert writer.enqueued == []
    assert user == "zhangsan"
    assert record.id == 42
    assert dispatcher._alarm_card_urls(record.id) == (
        "https://aicv.fudar.com/api/public/alarms/42/image",
        "https://aicv.fudar.com/?page=alarms&alarmId=aivision%3A42",
    )


# 功能：验证 `test_dispatcher_builds_public_image_and_detail_urls` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AlarmDispatcher`、`monkeypatch.setattr`、`dispatcher._alarm_card_urls`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_dispatcher_builds_public_image_and_detail_urls(monkeypatch):
    dispatcher = AlarmDispatcher()
    monkeypatch.setattr("AiVision.alarms.dispatcher.settings.alarm.wechat_card_base_url", "https://aicv.fudar.com/")

    image_url, detail_url = dispatcher._alarm_card_urls(42)

    assert image_url == "https://aicv.fudar.com/api/public/alarms/42/image"
    assert detail_url == "https://aicv.fudar.com/?page=alarms&alarmId=aivision%3A42"


# 功能：验证 `test_dispatcher_keeps_async_writer_when_wechat_disabled` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AlarmDispatcher`、`FakeViolationWriter`、`FakeWeChat`、`np.zeros`、`dispatcher._execute`、`AlarmRequest`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息；可能读取或修改数据库事务。
def test_dispatcher_keeps_async_writer_when_wechat_disabled():
    dispatcher = AlarmDispatcher()
    writer = FakeViolationWriter()
    dispatcher.horn_runtime_manager = None
    dispatcher.wechat = FakeWeChat()
    dispatcher.violation_writer = writer
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    dispatcher._execute(
        AlarmRequest(
            feature_name="blocks", department='research_institute',
            cooldown_subject_type="camera", cooldown_subject_id="7",
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
