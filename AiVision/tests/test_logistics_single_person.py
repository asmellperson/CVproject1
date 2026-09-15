# 文件说明：包含`test_logistics_single_person` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from types import SimpleNamespace

import numpy as np
import pytest

from AiVision.features.registry import all_specs
from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.features.logistics_channel.consumer import (
    LogisticsSinglePersonConsumer,
    build_monitor_snapshot,
)
from AiVision.features.logistics_channel.spec import SPEC as LOGISTICS_SPEC

LOGISTICS_CONSUMER_CLASSES = (LogisticsSinglePersonConsumer,)
LOGISTICS_FEATURE_NAMES = ("detect_logistics_single_person",)


def test_logistics_features_share_canonical_violation_type():
    specs = all_specs()
    assert {specs[name].violation_type for name in LOGISTICS_FEATURE_NAMES} == {6}


# 功能：定义 `RuntimeSpy` 类，封装`test_logistics_single_person` 模块相关的状态、约束与操作
# 参数：
#   - `should_run`（未显式标注）：`should_run` 对应的业务输入值；默认值为 `True`
#   - `confidence_threshold`（未显式标注）：`confidence_threshold` 对应的业务输入值；默认值为 `0.3`
# 返回：RuntimeSpy；返回新建的 `RuntimeSpy` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_single_person.py` 的 `test_process_uses_channel_person_confidence_threshold`
#         实例化本符号；`AiVision/tests/test_logistics_single_person.py` 的
#         `test_post_process_deduplicates_overlapping_rois_and_publishes_snapshot`
#         实例化本符号；`AiVision/tests/test_logistics_single_person.py` 的 `test_missing_roi_result_publishes_unknown_snapshot`
#         实例化本符号；`AiVision/tests/test_logistics_single_person.py` 的 `test_schedule_and_channel_evaluation_are_delegated_to_runtime`
#         实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class RuntimeSpy:
    # 功能：初始化或配置 `__init__` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `should_run`（未显式标注）：`should_run` 对应的业务输入值；默认值为 `True`
    #   - `confidence_threshold`（未显式标注）：`confidence_threshold` 对应的业务输入值；默认值为 `0.3`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, *, should_run=True, confidence_threshold=0.3):
        self.should_run = should_run
        self.confidence_threshold = confidence_threshold
        self.schedule_calls = []
        self.snapshot_calls = []
        self.evaluate_calls = []

    # 功能：启动或执行 `camera_should_run` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.schedule_calls.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def camera_should_run(self, feature_name, camera_id):
        self.schedule_calls.append((feature_name, camera_id))
        return self.should_run

    # 功能：实现 `person_confidence_threshold` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def person_confidence_threshold(self, feature_name, camera_id):
        return self.confidence_threshold

    # 功能：更新或保存 `update_camera_snapshot` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
    #   - `snapshot`（未显式标注）：`snapshot` 对应的业务输入值
    #   - `annotated_frame`（未显式标注）：`annotated_frame` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.snapshot_calls.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_camera_snapshot(self, feature_name, snapshot, annotated_frame):
        self.snapshot_calls.append((feature_name, snapshot, annotated_frame))

    # 功能：更新或保存 `evaluate_after_camera_update` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.evaluate_calls.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def evaluate_after_camera_update(self, feature_name, camera_id):
        self.evaluate_calls.append((feature_name, camera_id))


# 功能：创建或构建 `build_consumer` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `consumer_class`（未显式标注）：`consumer_class` 对应的业务输入值
#   - `runtime`（未显式标注）：`runtime` 对应的业务输入值；默认值为 `None`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_single_person.py` 的 `test_all_logistics_consumers_publish_details_without_camera_alarm`
#         调用本符号；`AiVision/tests/test_logistics_single_person.py` 的 `test_process_preserves_model_and_camera_filter_configuration`
#         调用本符号；`AiVision/tests/test_logistics_single_person.py` 的 `test_process_uses_channel_person_confidence_threshold`
#         调用本符号；`AiVision/tests/test_logistics_single_person.py` 的
#         `test_post_process_deduplicates_overlapping_rois_and_publishes_snapshot` 调用本符号；另有 2 处静态调用
#   - 内部调用：`object.__new__`、`SimpleNamespace`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def build_consumer(consumer_class, *, runtime=None):
    consumer = consumer_class(
        spec=SimpleNamespace(name="detect_logistics_single_person", required_models=("person-detector",)),
        infer_dict={}, result_queue=None, latest_frames={},
        is_camera_active=lambda _camera_key: True,
        logistics_runtime=runtime or RuntimeSpy(confidence_threshold=0.4),
    )
    consumer.config_cache = {7: {
        "name": "Camera 7", "shm_name": "cam-7",
        "IOU_THR": 0.3,
                  "MIN_BOX_AREA": 0, "ASPECT_RATIO_RANGE": [0, 10], "roi_pos": [],
    }}
    return consumer


# 功能：验证 `test_logistics_consumer_owns_detection_implementation` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `consumer_class`（未显式标注）：`consumer_class` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`issubclass`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("consumer_class", LOGISTICS_CONSUMER_CLASSES)
def test_logistics_consumer_owns_detection_implementation(consumer_class):
    assert consumer_class.__bases__ == (BaseFunctionConsumer,)
    assert "_process" in consumer_class.__dict__
    assert "post_process" in consumer_class.__dict__


# 功能：验证 `test_logistics_feature_supports_precious_metal_department` 对应的`test_logistics_single_person`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_logistics_feature_supports_precious_metal_department():
    assert LOGISTICS_SPEC.display_name == "物流通道单人检测"
    assert "precious_metal_recycling" in LOGISTICS_SPEC.departments


# 功能：验证 `test_all_logistics_consumers_publish_details_without_camera_alarm` 对应的`test_logistics_single_person`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `consumer_class`（未显式标注）：`consumer_class` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_consumer`、`consumer._process`、`np.zeros`、`all`、`sum`、`len`、`pytest.mark.parametrize`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
@pytest.mark.parametrize("consumer_class", LOGISTICS_CONSUMER_CLASSES)
def test_all_logistics_consumers_publish_details_without_camera_alarm(consumer_class):
    consumer = build_consumer(consumer_class)
    consumer.dispatch_inference_sync = lambda *_args, **_kwargs: {
            "status": "ok", "roi_id": 0,
            "detections": [
                {"type": "person", "bbox": [1, 2, 21, 62], "confidence": 0.9},
                {"type": "human", "bbox": [30, 2, 50, 62], "confidence": 0.8},
            ],
        }

    result = consumer._process(np.zeros((64, 64, 3), dtype=np.uint8), camera_id=7)

    assert result[0] is False
    assert len(result[1]["detections"]) == 2
    assert result[1]["reason"] == "multiple"
    assert result[1]["person_count"] == 2


# 功能：验证 `test_process_preserves_model_and_camera_filter_configuration` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_consumer`、`np.zeros`、`consumer._process`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_process_preserves_model_and_camera_filter_configuration():
    consumer = build_consumer(LogisticsSinglePersonConsumer)
    dispatched = {}

    # 功能：发送或分发 `dispatch` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `model_name`（未显式标注）：`model_name` 对应的业务输入值
    #   - `roi_list`（未显式标注）：`roi_list` 对应的业务输入值
    #   - `task_meta`（未显式标注）：`task_meta` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`dispatched.update`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def dispatch(camera_id, model_name, roi_list, task_meta):
        dispatched.update(
            camera_id=camera_id,
            model_name=model_name,
            roi_list=roi_list,
            task_meta=task_meta,
        )
        return {
                "status": "ok", "roi_id": 0,
                "detections": [
                    {"type": "vehicle", "bbox": [0, 0, 50, 50], "confidence": 0.9},
                    {"type": "person", "bbox": [0, 0, 1, 1], "confidence": 0.9},
                    {"type": "person", "bbox": [2, 2, 22, 62], "confidence": 0.8},
                ],
            }

    consumer.config_cache[7]["MIN_BOX_AREA"] = 100
    consumer.dispatch_inference_sync = dispatch
    roi = np.zeros((64, 64, 3), dtype=np.uint8)

    result = consumer._process(roi, camera_id=7)

    assert dispatched == {
        "camera_id": 7,
        "model_name": "person-detector",
        "roi_list": roi,
        "task_meta": {"conf": 0.4, "iou": 0.3},
    }
    assert [item["bbox"] for item in result[1]["detections"]] == [[2, 2, 22, 62]]


# 功能：验证 `test_process_uses_channel_person_confidence_threshold` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`RuntimeSpy`、`build_consumer`、`consumer._process`、`np.zeros`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_process_uses_channel_person_confidence_threshold():
    runtime = RuntimeSpy(confidence_threshold=0.72)
    consumer = build_consumer(LogisticsSinglePersonConsumer, runtime=runtime)
    dispatched = {}

    # 功能：发送或分发 `dispatch` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `_camera_id`（未显式标注）：`_camera_id` 对应业务对象的唯一标识
    #   - `_model_name`（未显式标注）：`_model_name` 对应的业务输入值
    #   - `_roi_list`（未显式标注）：`_roi_list` 对应的业务输入值
    #   - `task_meta`（未显式标注）：`task_meta` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`dispatched.update`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def dispatch(_camera_id, _model_name, _roi_list, task_meta):
        dispatched.update(task_meta)
        return {"status": "ok", "roi_id": 0, "detections": []}

    consumer.dispatch_inference_sync = dispatch
    consumer._process(np.zeros((16, 16, 3), dtype=np.uint8), camera_id=7)

    assert dispatched == {"conf": 0.72, "iou": 0.3}


# 功能：验证 `test_post_process_deduplicates_overlapping_rois_and_publishes_snapshot` 对应的`test_logistics_single_person`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`RuntimeSpy`、`build_consumer`、`np.zeros`、`consumer.post_process`、`np.any`、`len`、`consumer.get_monitor_status`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_post_process_restores_crop_offset_and_publishes_snapshot():
    runtime = RuntimeSpy()
    consumer = build_consumer(LogisticsSinglePersonConsumer, runtime=runtime)
    original = np.zeros((100, 100, 3), dtype=np.uint8)
    consumer.frame_cache[7] = original
    consumer.config_cache[7]["roi_pos"] = [[0.1, 0.1], [0.7, 0.1], [0.7, 1], [0.1, 1]]
    consumer._get_roi(7, original)
    result = (False, {
        "reason": "normal", "person_count": 1,
        "detections": [{"type": "person", "bbox": [10, 10, 40, 70], "confidence": 0.9}],
    })
    annotated = consumer.post_process(7, result)
    assert annotated.shape == original.shape
    assert np.any(annotated)
    assert not np.any(original)
    assert len(runtime.snapshot_calls) == 1
    feature_name, snapshot, published_frame = runtime.snapshot_calls[0]
    assert feature_name == consumer.feature_name
    assert snapshot.camera_id == 7
    assert snapshot.camera_name == "Camera 7"
    assert snapshot.count == 1
    assert (annotated[50, 20] == consumer.BBOX_COLOR_NORMAL).all()
    assert not annotated[50, 10].tolist() == list(consumer.BBOX_COLOR_NORMAL)
    assert snapshot.online is True
    assert snapshot.updated_at > 0
    assert published_frame is annotated
    assert consumer.get_monitor_status("cam-7")["count"] == 1


# 功能：验证 `test_missing_roi_result_publishes_unknown_snapshot` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`RuntimeSpy`、`build_consumer`、`np.zeros`、`consumer.post_process`、`consumer.get_monitor_status`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_failed_inference_publishes_unknown_snapshot():
    runtime = RuntimeSpy()
    consumer = build_consumer(LogisticsSinglePersonConsumer, runtime=runtime)
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    consumer.frame_cache[7] = frame
    roi = consumer._get_roi(7, frame)
    consumer.dispatch_inference_sync = lambda *_args, **_kwargs: {"status": "timeout", "detections": []}
    result = consumer._process(roi, 7)
    consumer.post_process(7, result)
    assert runtime.snapshot_calls[0][1].count is None
    assert consumer.get_monitor_status("cam-7")["reason"] == "unknown"


# 功能：验证 `test_schedule_and_channel_evaluation_are_delegated_to_runtime` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`RuntimeSpy`、`build_consumer`、`consumer._should_process_now`、`consumer._handle_alarm`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_schedule_and_channel_evaluation_are_delegated_to_runtime():
    runtime = RuntimeSpy(should_run=False)
    consumer = build_consumer(LogisticsSinglePersonConsumer, runtime=runtime)

    assert consumer._should_process_now(7, consumer.config_cache[7]) is False
    consumer._handle_alarm(7, [(False, {})], None)

    assert runtime.schedule_calls == [(consumer.feature_name, 7)]
    assert runtime.evaluate_calls == [(consumer.feature_name, 7)]


# 功能：验证 `test_all_logistics_consumers_require_channel_runtime` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `consumer_class`（未显式标注）：`consumer_class` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`SimpleNamespace`、`pytest.raises`、`consumer_class`、`str`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("consumer_class", LOGISTICS_CONSUMER_CLASSES)
def test_all_logistics_consumers_require_channel_runtime(consumer_class):
    spec = SimpleNamespace(
        name=f"test_{consumer_class.__name__}",
        required_models=("person-detector",),
    )

    with pytest.raises(RuntimeError, match=consumer_class.__name__) as raised:
        consumer_class(
            spec=spec,
            infer_dict={},
            result_queue=None,
            latest_frames={},
            is_camera_active=lambda _camera_key: True,
        )

    assert "LogisticsChannelRuntime" in str(raised.value)


# 功能：验证 `test_all_logistics_consumers_accept_injected_channel_runtime` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `consumer_class`（未显式标注）：`consumer_class` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`RuntimeSpy`、`SimpleNamespace`、`consumer_class`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("consumer_class", LOGISTICS_CONSUMER_CLASSES)
def test_all_logistics_consumers_accept_injected_channel_runtime(consumer_class):
    runtime = RuntimeSpy()
    spec = SimpleNamespace(
        name=f"test_{consumer_class.__name__}",
        required_models=("person-detector",),
    )

    consumer = consumer_class(
        spec=spec,
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _camera_key: True,
        logistics_runtime=runtime,
    )

    assert consumer.logistics_runtime is runtime


# 功能：验证 `test_monitor_snapshot_sums_known_roi_counts_and_preserves_alarm` 对应的`test_logistics_single_person` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_monitor_snapshot`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_monitor_snapshot_uses_single_roi_count_and_preserves_alarm():
    snapshot = build_monitor_snapshot(
        (True, {"reason": "multiple", "person_count": 2}), updated_at=100.0,
    )
    assert snapshot == {"count": 2, "alarm": True, "reason": "multiple", "updated_at_s": 100.0}
