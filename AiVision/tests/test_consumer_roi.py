# 文件说明：包含视频帧消费与检测、感兴趣区域的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from types import SimpleNamespace

import numpy as np

from AiVision.features._base.consumer import BaseFunctionConsumer


# 功能：定义 `RoiConsumer` 类，封装视频帧消费与检测、感兴趣区域相关的状态、约束与操作
# 参数：无。
# 返回：RoiConsumer；返回新建的 `RoiConsumer` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_consumer_roi.py` 的 `_consumer` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class RoiConsumer(BaseFunctionConsumer):
    # 功能：处理 `_process` 对应的视频帧消费与检测、感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
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

    # 功能：处理 `post_process` 对应的视频帧消费与检测、感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
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


# 功能：实现 `_consumer` 对应的视频帧消费与检测、感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：RoiConsumer；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`RoiConsumer`、`SimpleNamespace`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _consumer() -> RoiConsumer:
    return RoiConsumer(
        spec=SimpleNamespace(name="roi-test"),
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _name: True,
    )


# 功能：更新或保存 `_set_roi` 对应的视频帧消费与检测、感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `consumer`（RoiConsumer）：`consumer` 对应的业务输入值
#   - `camera_id`（int）：摄像头唯一标识
#   - `points`（list[list[int]]）：`points` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_consumer_roi.py` 的 `test_roi_outside_camera_frame_is_clipped_before_masking`
#         调用本符号；`AiVision/tests/test_consumer_roi.py` 的 `test_roi_mask_is_rebuilt_when_same_camera_frame_shape_changes`
#         调用本符号；`AiVision/tests/test_consumer_roi.py` 的 `test_roi_masks_are_isolated_by_camera_frame_shape` 调用本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _set_roi(consumer: RoiConsumer, camera_id: int, points: list[list[int]]) -> None:
    consumer.config_cache[camera_id] = {"value": {"roi_pos": [points]}}


# 功能：验证 `test_roi_outside_camera_frame_is_clipped_before_masking` 对应的视频帧消费与检测、感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_consumer`、`_set_roi`、`np.full`、`consumer._get_roi`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_roi_outside_camera_frame_is_clipped_before_masking():
    consumer = _consumer()
    _set_roi(
        consumer,
        camera_id=1,
        points=[[650, 500], [800, 500], [800, 700], [650, 700]],
    )
    frame = np.full((576, 704, 3), 127, dtype=np.uint8)

    roi_list = consumer._get_roi(1, frame)

    assert len(roi_list) == 1
    assert roi_list[0].shape == (76, 54, 3)
    assert consumer._masks[1][0][0].shape == roi_list[0].shape[:2]


# 功能：验证 `test_roi_mask_is_rebuilt_when_same_camera_frame_shape_changes` 对应的视频帧消费与检测、感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_consumer`、`_set_roi`、`consumer._get_roi`、`np.zeros`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_roi_mask_is_rebuilt_when_same_camera_frame_shape_changes():
    consumer = _consumer()
    _set_roi(
        consumer,
        camera_id=1,
        points=[[600, 400], [1000, 400], [1000, 700], [600, 700]],
    )

    large_roi = consumer._get_roi(1, np.zeros((720, 1280, 3), dtype=np.uint8))
    small_roi = consumer._get_roi(1, np.zeros((576, 704, 3), dtype=np.uint8))

    assert large_roi[0].shape == (300, 400, 3)
    assert small_roi[0].shape == (176, 104, 3)
    assert consumer._masks_frame_shape[1] == (576, 704)
    assert consumer._masks[1][0][0].shape == small_roi[0].shape[:2]


# 功能：验证 `test_roi_masks_are_isolated_by_camera_frame_shape` 对应的视频帧消费与检测、感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_consumer`、`_set_roi`、`consumer._get_roi`、`np.zeros`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_roi_masks_are_isolated_by_camera_frame_shape():
    consumer = _consumer()
    points = [[100, 100], [900, 100], [900, 650], [100, 650]]
    _set_roi(consumer, camera_id=1, points=points)
    _set_roi(consumer, camera_id=2, points=points)

    first_camera_roi = consumer._get_roi(1, np.zeros((576, 704, 3), dtype=np.uint8))
    second_camera_roi = consumer._get_roi(2, np.zeros((720, 1280, 3), dtype=np.uint8))

    assert first_camera_roi[0].shape == (476, 604, 3)
    assert second_camera_roi[0].shape == (550, 800, 3)
    assert consumer._masks_frame_shape == {1: (576, 704), 2: (720, 1280)}
