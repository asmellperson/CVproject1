# 文件说明：包含告警、配置的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

import AiVision.features._shared.consumer as consumer_module
from AiVision.alarms.dispatcher import AlarmDispatcher, AlarmEvidenceRequest, AlarmRequest
from AiVision.features._shared.consumer import BaseFunctionConsumer


# 功能：定义 `DummyConsumer` 类，封装告警、配置相关的状态、约束与操作
# 参数：无。
# 返回：DummyConsumer；返回新建的 `DummyConsumer` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_alarm_config_hot_update.py` 的 `test_update_config_resets_alarm_cooldown` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DummyConsumer(BaseFunctionConsumer):
    # 功能：处理 `_process` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `roi_list`（未显式标注）：`roi_list` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process(self, roi_list, camera_id):
        return []

    # 功能：处理 `post_process` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `result`（未显式标注）：`result` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def post_process(self, camera_id, result):
        return None


# 功能：定义 `FakeConfigCache` 类，封装告警、配置相关的状态、约束与操作
# 参数：无。
# 返回：FakeConfigCache；返回新建的 `FakeConfigCache` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_alarm_config_hot_update.py` 的 `test_update_config_resets_alarm_cooldown` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeConfigCache:
    # 功能：读取或查询 `get_function_config` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：定义 `FakeAlarmDispatcher` 类，封装告警、配置相关的状态、约束与操作
# 参数：无。
# 返回：FakeAlarmDispatcher；返回新建的 `FakeAlarmDispatcher` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_alarm_config_hot_update.py` 的 `test_update_config_resets_alarm_cooldown` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeAlarmDispatcher:
    # 功能：初始化或配置 `__init__` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.reset_calls = []

    # 功能：实现 `reset_cooldown` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `violation_type`（int）：正式报警类型
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.reset_calls.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def reset_cooldown(self, camera_id: int, violation_type: int):
        self.reset_calls.append((camera_id, violation_type))


def cooldown_request(**changes):
    values = dict(
        feature_name="blocks", violation_type=1, department="research_institute",
        camera_id=7, camera_name="camera", frame=np.zeros((2, 2, 3), np.uint8), alarm_config={},
        cooldown_subject_type="camera", cooldown_subject_id="7",
    )
    return AlarmRequest(**(values | changes))


@pytest.fixture
def cooldown_dispatcher(monkeypatch):
    dispatcher = AlarmDispatcher()
    dispatched = []
    monkeypatch.setattr(dispatcher, "_execute", dispatched.append)
    monkeypatch.setattr("AiVision.alarms.dispatcher.time.time", lambda: 100.0)
    return dispatcher, dispatched


@pytest.mark.parametrize("scope_type", ["camera", "logistics_channel", "test_site"])
def test_cooldown_isolates_alarm_types_and_explicit_scopes(monkeypatch, cooldown_dispatcher, scope_type):
    from AiVision.features import registry
    spec = replace(registry.get_spec("blocks"), name="composite", alarm_types=(1, 2))
    monkeypatch.setattr(registry, "_REGISTRY", registry._build_registry((spec,)))
    dispatcher, dispatched = cooldown_dispatcher
    first = cooldown_request(feature_name=spec.name, cooldown_subject_type=scope_type,
                             subject_type="face_person", subject_id="same-person")
    other_type = replace(first, violation_type=2)
    other_id = replace(first, cooldown_subject_id="8")
    other_scope = replace(first, cooldown_subject_type="other_scope")
    for req in (first, other_type, other_id, other_scope):
        assert dispatcher.maybe_dispatch(req, alarm_interval=5)
        assert not dispatcher.maybe_dispatch(req, alarm_interval=5)
    assert len(dispatched) == 4
    monkeypatch.setattr("AiVision.alarms.dispatcher.time.time", lambda: 105.0)
    assert dispatcher.maybe_dispatch(first, alarm_interval=5)


def test_cooldown_does_not_infer_scope_from_business_subject_or_camera(cooldown_dispatcher):
    dispatcher, dispatched = cooldown_dispatcher
    first = cooldown_request(subject_type="face_person", subject_id="17")
    assert dispatcher.maybe_dispatch(first)
    unknown = replace(first, subject_type="unknown_face", subject_id="", camera_id=999)
    assert dispatcher._cooldown_key(unknown) == ("camera", "7", 1)
    assert not dispatcher.maybe_dispatch(unknown)
    assert dispatcher.maybe_dispatch(replace(first, cooldown_subject_id="8"))
    assert len(dispatched) == 2


@pytest.mark.parametrize("field", ["cooldown_subject_type", "cooldown_subject_id"])
@pytest.mark.parametrize("value", [None, "", " ", " camera ", 7, True, [], {}])
def test_invalid_cooldown_scope_is_rejected_without_inference(cooldown_dispatcher, field, value):
    dispatcher, dispatched = cooldown_dispatcher
    with pytest.raises(ValueError, match=field):
        cooldown_request(**{field: value})
    req = cooldown_request()
    setattr(req, field, value)
    with pytest.raises(ValueError, match=field):
        dispatcher.maybe_dispatch(req)
    with pytest.raises(ValueError, match=field):
        dispatcher.reset_subject_cooldown(req.cooldown_subject_type, req.cooldown_subject_id, 1)
    assert not dispatched and not dispatcher._last_alarm


@pytest.mark.parametrize("field", ["cooldown_subject_type", "cooldown_subject_id"])
def test_cooldown_scope_is_required(field):
    values = vars(cooldown_request()).copy()
    del values[field]
    with pytest.raises(TypeError, match=field):
        AlarmRequest(**values)


@pytest.mark.parametrize("scope_type", ["camera", "logistics_channel", "test_site"])
def test_reset_clears_only_requested_scope_and_alarm_type(cooldown_dispatcher, scope_type):
    dispatcher, dispatched = cooldown_dispatcher
    first = cooldown_request(cooldown_subject_type=scope_type)
    other_type = replace(first, violation_type=2, feature_name="detect_door")
    other_id = replace(first, cooldown_subject_id="8")
    other_scope = replace(first, cooldown_subject_type="other_scope")
    for req in (first, other_type, other_id, other_scope):
        assert dispatcher.maybe_dispatch(req)
    if scope_type == "camera":
        dispatcher.reset_cooldown(7, 1)
    else:
        dispatcher.reset_subject_cooldown(scope_type, "7", 1)
    assert dispatcher.maybe_dispatch(first)
    for req in (other_type, other_id, other_scope):
        assert not dispatcher.maybe_dispatch(req)
    assert len(dispatched) == 5


@pytest.mark.parametrize("value", ["blocks", True, 1.0, 0, 8])
def test_reset_requires_formal_alarm_type(cooldown_dispatcher, value):
    dispatcher, _ = cooldown_dispatcher
    assert dispatcher.maybe_dispatch(cooldown_request())
    with pytest.raises(ValueError, match="violation_type"):
        dispatcher.reset_cooldown(7, value)
    with pytest.raises(ValueError, match="violation_type"):
        dispatcher.reset_subject_cooldown("camera", "7", value)
    assert not dispatcher.maybe_dispatch(cooldown_request())


@pytest.mark.parametrize("action", ["update_config", "remove_camera"])
@pytest.mark.parametrize("alarm_types", [(1,), (1, 2)])
def test_consumer_resets_only_its_declared_alarm_types(monkeypatch, cooldown_dispatcher, action, alarm_types):
    from AiVision.features.registry import get_spec
    dispatcher, _ = cooldown_dispatcher
    monkeypatch.setattr(consumer_module, "alarm_dispatcher", dispatcher)
    monkeypatch.setattr(consumer_module.config_cache, "get_function_config",
                        lambda *_: {"enable": True, "shm_name": "camera"})
    consumer = DummyConsumer(spec=replace(get_spec("blocks"), alarm_types=alarm_types),
        infer_dict={}, result_queue=None, latest_frames={}, is_camera_active=lambda _: True)
    requests = [cooldown_request(), cooldown_request(feature_name="detect_door", violation_type=2),
                cooldown_request(feature_name="detect_phone", violation_type=3)]
    for req in requests:
        assert dispatcher.maybe_dispatch(req)
    getattr(consumer, action)(7)
    for req in requests:
        assert dispatcher.maybe_dispatch(req) is (req.violation_type in alarm_types)


# 功能：验证 `test_update_config_resets_alarm_cooldown` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FakeAlarmDispatcher`、`monkeypatch.setattr`、`FakeConfigCache`、`DummyConsumer`、`SimpleNamespace`、`consumer.update_config`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_update_config_resets_alarm_cooldown(monkeypatch):
    dispatcher = FakeAlarmDispatcher()
    monkeypatch.setattr(consumer_module, "config_cache", FakeConfigCache())
    monkeypatch.setattr(consumer_module, "alarm_dispatcher", dispatcher)

    consumer = DummyConsumer(
        spec=SimpleNamespace(name="detect_test", alarm_types=(1,)),
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _name: True,
    )

    consumer.update_config(7)

    assert consumer.config_cache[7]["wechat_user"] == "zhangsan"
    assert dispatcher.reset_calls == [(7, 1)]


def test_update_config_does_not_readd_disabled_camera(monkeypatch):
    monkeypatch.setattr(
        consumer_module,
        "config_cache",
        SimpleNamespace(
            get_function_config=lambda _camera_id, _feature_name: {
                "camera_id": 7,
                "enable": False,
                "shm_name": "camera_7",
            }
        ),
    )

    consumer = DummyConsumer(
        spec=SimpleNamespace(name="detect_test", alarm_types=(1,)),
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _name: True,
    )
    consumer.config_cache[7] = {
        "camera_id": 7,
        "enable": True,
        "shm_name": "camera_7",
    }
    consumer.result_dict["camera_7"] = np.zeros((2, 2, 3), np.uint8)
    consumer.result_updated_at["camera_7"] = 1.0

    consumer.update_config(7)

    assert 7 not in consumer.config_cache
    assert "camera_7" not in consumer.result_dict
    assert "camera_7" not in consumer.result_updated_at


# 功能：验证 `test_dispatcher_cooldown_uses_logistics_channel_subject` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AlarmDispatcher`、`monkeypatch.setattr`、`executed.append`、`dispatcher.maybe_dispatch`、`request`、`dispatcher.reset_subject_cooldown`、`len`。
# 副作用/注意事项：可能读取或修改数据库事务。
def test_dispatcher_cooldown_uses_logistics_channel_subject(monkeypatch):
    dispatcher = AlarmDispatcher()
    executed = []
    monkeypatch.setattr(dispatcher, "_execute", lambda request: executed.append(request))
    monkeypatch.setattr("AiVision.alarms.dispatcher.time.time", lambda: 100.0)

    # 功能：实现 `request` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`AlarmRequest`、`np.zeros`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def request(camera_id):
        return AlarmRequest(
            feature_name="detect_logistics_single_person",
            camera_id=camera_id,
            camera_name="物流通道一",
            frame=np.zeros((2, 2, 3), np.uint8),
            violation_type=6,
            alarm_config={},
            department="general_electric",
            subject_type="logistics_channel",
            cooldown_subject_type="logistics_channel",
            cooldown_subject_id="3",
            subject_id="3",
            subject_name="物流通道一",
        )

    assert dispatcher.maybe_dispatch(request(10), alarm_interval=5.0) is True
    assert dispatcher.maybe_dispatch(request(11), alarm_interval=5.0) is False
    dispatcher.reset_subject_cooldown(
        "logistics_channel",
        "3",
        6,
    )
    assert dispatcher.maybe_dispatch(request(11), alarm_interval=5.0) is True
    assert len(executed) == 2


# 功能：验证 `test_dispatcher_forwards_subject_metadata_to_violation_writer` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AlarmDispatcher`、`Writer`、`dispatcher._execute`、`AlarmRequest`、`np.zeros`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能读取或修改数据库事务。
def test_dispatcher_forwards_subject_metadata_to_violation_writer():
    calls = []

    # 功能：定义 `Writer` 类，封装告警、配置相关的状态、约束与操作
    # 参数：无。
    # 返回：Writer；返回新建的 `Writer` 实例。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class Writer:
        # 功能：实现 `enqueue` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`calls.append`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
            department="general_electric",
            subject_type="logistics_channel",
            cooldown_subject_type="logistics_channel",
            cooldown_subject_id="3",
            subject_id="3",
            subject_name="物流通道一",
            reason="empty",
            metadata={"camera_counts": {"10": 0}},
        )
    )

    assert calls[0]["subject_type"] == "logistics_channel"
    assert calls[0]["subject_id"] == "3"
    assert calls[0]["subject_name"] == "物流通道一"
    assert calls[0]["camera_no"] is None
    assert calls[0]["feature_name"] == "detect_logistics_single_person"
    assert calls[0]["department"] == "general_electric"
    assert calls[0]["reason"] == "empty"
    assert calls[0]["event_metadata"] == {"camera_counts": {"10": 0}}


# 功能：验证 `test_dispatcher_attaches_pending_shared_evidence_video` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AlarmDispatcher`、`Writer`、`Recorder`、`dispatcher._execute`、`AlarmRequest`、`np.zeros`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能读取或修改数据库事务。
def test_dispatcher_attaches_pending_shared_evidence_video():
    calls = []

    # 功能：定义 `Writer` 类，封装告警、配置相关的状态、约束与操作
    # 参数：无。
    # 返回：Writer；返回新建的 `Writer` 实例。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class Writer:
        # 功能：实现 `enqueue` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`calls.append`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def enqueue(self, **kwargs):
            calls.append(kwargs)

    # 功能：定义 `Recorder` 类，封装告警、配置相关的状态、约束与操作
    # 参数：无。
    # 返回：Recorder；返回新建的 `Recorder` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_alarm_config_hot_update.py` 的 `test_dispatcher_attaches_pending_shared_evidence_video` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class Recorder:
        # 功能：启动或执行 `start_alarm` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `source_key`（未显式标注）：`source_key` 对应的业务输入值
        #   - `frame`（未显式标注）：待处理的视频图像帧
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def start_alarm(self, source_key, frame):
            assert source_key == "camera_7"
            assert frame.shape == (2, 2, 3)
            return "/tmp/alarm.mp4"

    dispatcher = AlarmDispatcher()
    dispatcher.violation_writer = Writer()
    dispatcher.evidence_recorder = Recorder()
    dispatcher._execute(
        AlarmRequest(
            feature_name="blocks", department='research_institute',
            cooldown_subject_type="camera", cooldown_subject_id="7",
            camera_id=7,
            camera_name="后大门",
            frame=np.zeros((2, 2, 3), np.uint8),
            violation_type=1,
            alarm_config={},
            camera_key="camera_7",
        )
    )

    assert calls[0]["video_path"] == "/tmp/alarm.mp4"
    assert calls[0]["video_status"] == "pending"
    assert calls[0]["camera_no"] == "camera_7"
    assert calls[0]["feature_name"] == "blocks"


# 功能：验证 `test_dispatcher_respects_explicit_sql_channel_switch_and_keeps_legacy_default` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AlarmDispatcher`、`Writer`、`dispatcher._execute`、`request`、`len`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能读取或修改数据库事务。
def test_dispatcher_respects_explicit_sql_channel_switch_and_keeps_legacy_default():
    calls = []

    # 功能：定义 `Writer` 类，封装告警、配置相关的状态、约束与操作
    # 参数：无。
    # 返回：Writer；返回新建的 `Writer` 实例。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class Writer:
        # 功能：实现 `enqueue` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`calls.append`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def enqueue(self, **kwargs):
            calls.append(kwargs)

    # 功能：实现 `request` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `alarm_config`（未显式标注）：`alarm_config` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`AlarmRequest`、`np.zeros`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def request(alarm_config):
        return AlarmRequest(
            feature_name="detect_logistics_single_person", department='general_electric',
            cooldown_subject_type="logistics_channel", cooldown_subject_id="3",
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


def test_camera_department_reaches_alarm_from_camera_ownership(monkeypatch):
    from AiVision.core.cache import ConfigCache
    from AiVision.cameras.orm import AiCameraConfig

    cache = ConfigCache()
    camera = AiCameraConfig(id=7, name="camera", shm_name="camera_7", enable=True, department="research_institute")
    cache._camera_cache[7] = cache._orm_to_dict(camera)
    cfg = cache._enrich_function_config({
        "camera_id": 7, "enable": True, "alarm_interval": 5.0,
        "sql_enable": True,
    })
    assert cfg["department"] == "research_institute"
    consumer = DummyConsumer(
        spec=SimpleNamespace(name="blocks", alarm_types=(1,)),
        infer_dict={}, result_queue=None, latest_frames={}, is_camera_active=lambda _key: True,
    )
    consumer.config_cache[7] = cfg
    requests = []
    monkeypatch.setattr(consumer_module.alarm_dispatcher, "maybe_dispatch", lambda request, **_kwargs: requests.append(request))
    consumer._handle_alarm(7, [(True, {})], None)
    assert requests[0].department == "research_institute"


@pytest.mark.parametrize(("mode", "token", "expected_action"), [
    ("clip", None, ("clip", "production-line/1")),
    ("episode", "event-1", ("finish", "event-1")),
    ("episode", None, None),
])
def test_explicit_evidence_does_not_change_physical_camera_identity(mode, token, expected_action):
    calls, writes = [], []
    dispatcher = AlarmDispatcher()
    dispatcher.evidence_recorder = SimpleNamespace(
        start_alarm=lambda source, frame: calls.append(("clip", source)) or "/evidence/clip.mp4",
        finish_episode=lambda value: calls.append(("finish", value)) or "/evidence/episode.mp4",
        cancel_episode=lambda value: calls.append(("cancel", value)),
    )
    dispatcher.violation_writer = SimpleNamespace(enqueue=lambda **values: writes.append(values))
    request = AlarmRequest(
        feature_name="blocks", violation_type=1, department="general_electric",
        camera_id=1, camera_name="Camera 1", camera_key="physical-camera-1",
        cooldown_subject_type="production_line", cooldown_subject_id="1",
        frame=np.zeros((2, 2, 3), np.uint8), alarm_config={"sql": {"enable": True}},
        evidence=AlarmEvidenceRequest("production-line/1", mode, token),
    )
    assert dispatcher.maybe_dispatch(request)
    assert calls == ([] if expected_action is None else [expected_action])
    assert writes[0]["camera_no"] == "physical-camera-1"
    assert writes[0]["video_status"] == ("pending" if expected_action else None)


def test_episode_evidence_is_cancelled_when_cooldown_or_channels_reject_it():
    cancelled, finished = [], []
    dispatcher = AlarmDispatcher()
    dispatcher.evidence_recorder = SimpleNamespace(
        finish_episode=lambda token: finished.append(token) or "/evidence/event.mp4",
        cancel_episode=lambda token: cancelled.append(token),
    )
    request = AlarmRequest(
        feature_name="blocks", violation_type=1, department="general_electric",
        camera_id=1, camera_name="Camera 1", frame=np.zeros((2, 2, 3), np.uint8),
        cooldown_subject_type="production_line", cooldown_subject_id="1",
        alarm_config={"sql": {"enable": True}}, evidence=AlarmEvidenceRequest("line", "episode", "first"),
    )
    assert dispatcher.maybe_dispatch(request, alarm_interval=60)
    rejected = replace(request, evidence=AlarmEvidenceRequest("line", "episode", "second"))
    assert not dispatcher.maybe_dispatch(rejected, alarm_interval=60)
    muted = replace(request, cooldown_subject_id="2", alarm_config={"sql": {"enable": False}},
                    evidence=AlarmEvidenceRequest("line", "episode", "muted"))
    assert dispatcher.maybe_dispatch(muted)
    assert finished == ["first"] and cancelled == ["second", "muted"]
