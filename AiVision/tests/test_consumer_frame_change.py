# 文件说明：包含视频帧消费与检测、视频帧的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from types import SimpleNamespace

import cv2
import numpy as np

from features._base.consumer import BaseFunctionConsumer


# 功能：定义 `FrameChangeConsumer` 类，封装视频帧消费与检测、视频帧相关的状态、约束与操作
# 参数：无。
# 返回：FrameChangeConsumer；返回新建的 `FrameChangeConsumer` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_consumer_frame_change.py` 的 `_consumer` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FrameChangeConsumer(BaseFunctionConsumer):
    # 功能：处理 `_process` 对应的视频帧消费与检测、视频帧逻辑；输入由参数提供，处理结果见返回值说明
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

    # 功能：处理 `post_process` 对应的视频帧消费与检测、视频帧逻辑；输入由参数提供，处理结果见返回值说明
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


# 功能：实现 `_consumer` 对应的视频帧消费与检测、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：FrameChangeConsumer；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FrameChangeConsumer`、`SimpleNamespace`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _consumer() -> FrameChangeConsumer:
    return FrameChangeConsumer(
        spec=SimpleNamespace(name="frame-change-test"),
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _name: True,
    )


# 功能：实现 `_high_contrast_frame` 对应的视频帧消费与检测、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_consumer_frame_change.py` 的 `test_identical_high_contrast_frame_is_not_reported_as_changed`
#         调用本符号；`AiVision/tests/test_consumer_frame_change.py` 的 `test_unchanged_frame_only_blurs_downsampled_comparison_image`
#         调用本符号；`AiVision/tests/test_consumer_frame_change.py` 的 `test_visibly_changed_frame_refreshes_full_resolution_blur` 调用本符号
#   - 内部调用：`np.zeros`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _high_contrast_frame() -> np.ndarray:
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[:, 16:32] = 255
    frame[:, 48:64] = 255
    return frame


# 功能：验证 `test_identical_high_contrast_frame_is_not_reported_as_changed` 对应的视频帧消费与检测、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_consumer`、`_high_contrast_frame`、`consumer._frame_changed`、`frame.copy`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_identical_high_contrast_frame_is_not_reported_as_changed():
    consumer = _consumer()
    frame = _high_contrast_frame()

    assert consumer._frame_changed(1, [frame]) is True
    assert consumer._frame_changed(1, [frame.copy()]) is False


# 功能：验证 `test_unchanged_frame_only_blurs_downsampled_comparison_image` 对应的视频帧消费与检测、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_consumer`、`_high_contrast_frame`、`monkeypatch.setattr`、`consumer._frame_changed`、`blurred_shapes.count`、`frame.copy`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_unchanged_frame_only_blurs_downsampled_comparison_image(monkeypatch):
    consumer = _consumer()
    frame = _high_contrast_frame()
    blurred_shapes: list[tuple[int, ...]] = []
    real_gaussian_blur = cv2.GaussianBlur

    # 功能：实现 `recording_gaussian_blur` 对应的视频帧消费与检测、视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `image`（未显式标注）：待处理的图像数据
    #   - `kernel_size`（未显式标注）：`kernel_size` 对应的数量或大小
    #   - `sigma`（未显式标注）：`sigma` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`blurred_shapes.append`、`real_gaussian_blur`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def recording_gaussian_blur(image, kernel_size, sigma):
        blurred_shapes.append(image.shape)
        return real_gaussian_blur(image, kernel_size, sigma)

    monkeypatch.setattr(cv2, "GaussianBlur", recording_gaussian_blur)

    assert consumer._frame_changed(1, [frame]) is True
    full_resolution_blurs = blurred_shapes.count(frame.shape)
    assert consumer._frame_changed(1, [frame.copy()]) is False

    assert blurred_shapes.count(frame.shape) == full_resolution_blurs
    assert consumer.blur_roi[1][0].shape == frame.shape


# 功能：验证 `test_visibly_changed_frame_refreshes_full_resolution_blur` 对应的视频帧消费与检测、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_consumer`、`_high_contrast_frame`、`consumer._frame_changed`、`consumer.blur_roi[1][0].copy`、`np.array_equal`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_visibly_changed_frame_refreshes_full_resolution_blur():
    consumer = _consumer()
    frame = _high_contrast_frame()
    changed = 255 - frame

    assert consumer._frame_changed(1, [frame]) is True
    previous_blur = consumer.blur_roi[1][0].copy()

    assert consumer._frame_changed(1, [changed]) is True
    assert not np.array_equal(consumer.blur_roi[1][0], previous_blur)
