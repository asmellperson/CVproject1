# 文件说明：包含企业微信通知的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from types import SimpleNamespace

import numpy as np

from core.alarm.dispatcher import AlarmDispatcher, AlarmRequest
from core.alarm.wechat import WeChatNotifier, _EVENT_DISPLAY


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
    def __init__(self, payload):
        self._payload = payload

    # 功能：实现 `json` 对应的企业微信通知逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/alarm/horn.py` 的 `Horn::connect` 调用本符号；`AiVision/core/alarm/wechat.py` 的 `WeChatNotifier::_get_token`
    #         调用本符号；`AiVision/core/alarm/wechat.py` 的 `WeChatNotifier::_upload_image` 调用本符号；`AiVision/core/alarm/wechat.py` 的
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
    assert _EVENT_DISPLAY["detect_human_haoda"] == "人员违规逗留检测（皓达公司）"


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
        "core.alarm.wechat.requests.post",
        lambda *args, **kwargs: posts.append(kwargs["json"]) or FakeResponse({"errcode": 0}),
    )

    notifier.send(
        feature_name="blocks",
        camera_name="后大门",
        image_jpeg_bytes=b"unused-for-news",
        recipients="zhangsan",
        image_url="https://aicv.fudar.com/api/alarms/42/image",
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
    assert article["picurl"] == "https://aicv.fudar.com/api/alarms/42/image"


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
    dispatcher.horn_dict = {}
    dispatcher.wechat = FakeWeChat()
    dispatcher.violation_writer = writer
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    dispatcher._execute(
        AlarmRequest(
            feature_name="detect_human",
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
    monkeypatch.setattr("core.alarm.dispatcher.settings.alarm.wechat_card_base_url", "https://aicv.fudar.com/")

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
