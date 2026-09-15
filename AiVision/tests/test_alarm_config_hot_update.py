# 文件说明：包含告警、配置的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from types import SimpleNamespace

import numpy as np

import AiVision.features._base.consumer as consumer_module
from AiVision.core.alarm.dispatcher import AlarmDispatcher, AlarmRequest
from AiVision.features._base.consumer import BaseFunctionConsumer


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
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.reset_calls.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def reset_cooldown(self, camera_id: int, feature_name: str):
        self.reset_calls.append((camera_id, feature_name))


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
        spec=SimpleNamespace(name="detect_test"),
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _name: True,
    )

    consumer.update_config(7)

    assert consumer.config_cache[7]["wechat_user"] == "zhangsan"
    assert dispatcher.reset_calls == [(7, "detect_test")]


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
        spec=SimpleNamespace(name="detect_test"),
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
    monkeypatch.setattr("AiVision.core.alarm.dispatcher.time.time", lambda: 100.0)

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


def test_camera_department_reaches_alarm_without_changing_feature_scope(monkeypatch):
    from AiVision.core.cache import ConfigCache
    from AiVision.cameras.orm import AiCameraConfig

    cache = ConfigCache()
    camera = AiCameraConfig(id=7, name="camera", shm_name="camera_7", enable=True, department="research_institute")
    cache._camera_cache[7] = cache._orm_to_dict(camera)
    cfg = cache._enrich_function_config({
        "camera_id": 7, "enable": True, "departments": ["research", "general"], "alarm_interval": 5.0,
        "sql_enable": True,
    })
    assert cfg["departments"] == ["research", "general"]
    consumer = DummyConsumer(
        spec=SimpleNamespace(name="blocks", violation_type=1, departments=("research_institute",)),
        infer_dict={}, result_queue=None, latest_frames={}, is_camera_active=lambda _key: True,
    )
    consumer.config_cache[7] = cfg
    requests = []
    monkeypatch.setattr(consumer_module.alarm_dispatcher, "maybe_dispatch", lambda request, **_kwargs: requests.append(request))
    consumer._handle_alarm(7, [(True, {})], None)
    assert requests[0].department == "research_institute"
