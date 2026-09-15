# 文件说明：包含视频帧消费与检测、感兴趣区域的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from AiVision.features._shared.consumer import BaseFunctionConsumer


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
    def _process(self, roi, camera_id):
        return False, {}

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
    consumer = RoiConsumer(
        spec=SimpleNamespace(name="roi-test"),
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _name: True,
    )
    consumer.config_cache[1] = {"roi_pos": []}
    return consumer


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
    consumer.config_cache[camera_id] = {"roi_pos": points}


# 功能：验证 `test_roi_outside_camera_frame_is_clipped_before_masking` 对应的视频帧消费与检测、感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_consumer`、`_set_roi`、`np.full`、`consumer._get_roi`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_single_polygon_mask_and_crop_share_original_frame_coordinates():
    consumer = _consumer()
    _set_roi(consumer, 1, [[0.25, 0.25], [0.75, 0.25], [0.25, 0.75]])
    frame = np.full((100, 200, 3), 127, dtype=np.uint8)
    roi = consumer._get_roi(1, frame)
    assert roi.shape == (50, 100, 3)
    assert consumer._get_roi_offset(1) == (50, 25)
    assert consumer._masks[1][0].shape == roi.shape[:2]
    assert (roi[1, 1] == 127).all()
    assert (roi[-1, -1] == 0).all()


# 功能：验证 `test_roi_mask_is_rebuilt_when_same_camera_frame_shape_changes` 对应的视频帧消费与检测、感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_consumer`、`_set_roi`、`consumer._get_roi`、`np.zeros`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_roi_mask_is_rebuilt_when_same_camera_frame_shape_changes():
    consumer = _consumer()
    _set_roi(consumer, 1, [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]])
    large_roi = consumer._get_roi(1, np.zeros((720, 1280, 3), dtype=np.uint8))
    small_roi = consumer._get_roi(1, np.zeros((360, 640, 3), dtype=np.uint8))
    assert large_roi.shape == (360, 640, 3)
    assert small_roi.shape == (180, 320, 3)
    assert consumer._get_roi_offset(1) == (160, 90)
    assert consumer._masks_frame_shape[1] == (360, 640)
    assert consumer._masks[1][0].shape == small_roi.shape[:2]


# 功能：验证 `test_roi_masks_are_isolated_by_camera_frame_shape` 对应的视频帧消费与检测、感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_consumer`、`_set_roi`、`consumer._get_roi`、`np.zeros`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_roi_masks_are_isolated_by_camera_frame_shape():
    consumer = _consumer()
    points = [[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5]]
    _set_roi(consumer, 1, points)
    _set_roi(consumer, 2, points)
    first = consumer._get_roi(1, np.zeros((360, 640, 3), dtype=np.uint8))
    second = consumer._get_roi(2, np.zeros((720, 1280, 3), dtype=np.uint8))
    assert first.shape == (180, 320, 3)
    assert second.shape == (360, 640, 3)
    assert consumer._masks_frame_shape == {1: (360, 640), 2: (720, 1280)}


@pytest.mark.parametrize("invalid", [
    [[10, 10], [100, 10], [100, 100]],
    [[[0, 0], [1, 0], [1, 1]]],
    [0, 0, 1, 1], [[0, 0], [1, 1]], [[0, 0], [0.5, 0.5], [1, 1]],
    [[-0.1, 0], [1, 0], [1, 1]], [[True, 0], [1, 0], [1, 1]], None,
])
def test_invalid_roi_is_rejected_without_guessing_a_format(invalid):
    consumer = _consumer()
    consumer.config_cache[1] = {"roi_pos": invalid}
    with pytest.raises(ValidationError):
        consumer._get_roi(1, np.zeros((100, 200, 3), np.uint8))


def test_empty_roi_means_full_frame_and_annotation_does_not_mutate_source():
    consumer = _consumer()
    frame = np.zeros((100, 200, 3), np.uint8)
    frame.setflags(write=False)
    consumer.frame_cache[1] = frame
    roi = consumer._get_roi(1, frame)
    annotated = consumer._annotated_frame(1)
    assert roi.shape == frame.shape
    assert consumer._get_roi_offset(1) == (0, 0)
    assert (annotated[0, 0] == consumer.ROI_COLOR).all()
    assert (annotated[-1, -1] == consumer.ROI_COLOR).all()
    assert not frame.any()


def test_roi_edit_rebuilds_mask_and_resets_frame_difference_state():
    consumer = _consumer()
    frame = np.zeros((100, 200, 3), np.uint8)
    consumer._frame_changed(1, consumer._get_roi(1, frame))
    _set_roi(consumer, 1, [[0.5, 0.5], [1, 0.5], [1, 1], [0.5, 1]])
    assert consumer._get_roi(1, frame).shape == (50, 100, 3)
    assert consumer._get_roi_offset(1) == (100, 50)
    assert 1 not in consumer.frame_change_samples


ORDINARY_FEATURES = (
    "blocks", "detect_door", "detect_face", "detect_human",
    "detect_phone", "detect_logistics_single_person",
)


def _spec(feature):
    from AiVision.features.registry import get_spec
    spec = get_spec(feature)
    assert spec is not None
    return spec


@pytest.mark.parametrize("feature", ORDINARY_FEATURES)
def test_all_feature_schemas_accept_only_one_normalized_roi(feature):
    schema = _spec(feature).config_schema
    polygon = [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]]
    assert schema(value={"roi_pos": polygon}).value.roi_pos == polygon
    assert schema().value.roi_pos == []
    for roi in ([[100, 100], [500, 100], [500, 500]], [polygon], None):
        with pytest.raises(ValidationError):
            schema(value={"roi_pos": roi})
    with pytest.raises(ValidationError):
        schema(value={"roi_pos": polygon, "region": [100, 100, 500, 500]})


@pytest.mark.parametrize("feature", ORDINARY_FEATURES)
def test_new_camera_configuration_persists_empty_normalized_roi(feature):
    from sqlalchemy import create_engine, select
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.alarms.devices.orm import AiHornConfig
    assert AiCameraConfig.__table__.name == "ai_camera_config"
    assert AiHornConfig.__table__.name == "ai_horn_config"
    table = _spec(feature).orm_class.__table__
    engine = create_engine("sqlite://")
    try:
        table.create(engine)
        with engine.begin() as connection:
            connection.execute(table.insert(), [{"camera_id": 1}, {"camera_id": 2}])
            assert connection.execute(select(table.c.roi_pos)).scalars().all() == [[], []]
            if feature == "blocks":
                assert connection.execute(select(table.c.line_points)).scalars().all() == [[], []]
    finally:
        engine.dispose()


@pytest.mark.parametrize("feature", ORDINARY_FEATURES)
def test_each_feature_crops_infers_and_draws_in_current_frame_coordinates(feature):
    spec = _spec(feature)
    snapshots = []
    runtime = SimpleNamespace(
        person_confidence_threshold=lambda *_args: 0.3,
        update_camera_snapshot=lambda *args: snapshots.append(args),
    )
    kwargs = {"logistics_runtime": runtime} if feature == "detect_logistics_single_person" else {}
    consumer = spec.consumer_cls(
        spec=spec, infer_dict={}, result_queue=None, latest_frames={},
        is_camera_active=lambda _name: True, **kwargs,
    )
    value = spec.config_schema().value.model_dump()
    value.update(roi_pos=[[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]])
    overrides = dict(MIN_BOX_AREA=0, ASPECT_RATIO_RANGE=[0, 10], MAX_TIME=100,
                     REQUIRE_PERSON_ASSOCIATION=False, MIN_CONSECUTIVE_HITS=1, MIN_CONFIRM_SECONDS=0)
    value.update({key: val for key, val in overrides.items() if key in value})
    if feature == "blocks":
        value["line_points"] = [[0, 0.5], [1, 0.5]]
    consumer.config_cache[1] = {**value, "name": "test", "shm_name": "test"}
    calls = []

    def infer(camera_id, model, roi, **_kwargs):
        calls.append((camera_id, model, roi.copy()))
        kind = "face" if feature == "detect_face" else "phone" if feature == "detect_phone" else "person"
        return {"status": "ok", "detections": [{"type": kind, "bbox": [10, 10, 30, 40], "confidence": 0.9, "class_id": 0}]}

    consumer.dispatch_inference_sync = infer
    for height, width in [(100, 200), (200, 400)]:
        frame = np.full((height, width, 3), 20, np.uint8)
        frame.setflags(write=False)
        consumer.frame_cache[1] = frame
        roi = consumer._get_roi(1, frame)
        consumer._frame_changed(1, roi)
        result = consumer._process(roi, 1)
        annotated = consumer.post_process(1, result)
        assert annotated.shape == frame.shape
        assert (frame == 20).all()
        ox, oy = width // 4, height // 4
        assert (annotated[oy, ox] == consumer.ROI_COLOR).all()
        if feature == "detect_door":
            assert result[0] is False
            assert consumer._bg_gray[1].shape == (height // 2, width // 2)
        else:
            assert calls[-1][0] == 1
            assert calls[-1][2].shape == (height // 2, width // 2, 3)
            # 检测框左边缘必须恢复裁剪偏移，位于原始帧坐标。
            assert (annotated[oy + 25, ox + 10] != 20).any()
            if feature == "blocks":
                assert result[1]["detections"][0]["bbox"] == [ox + 10, oy + 10, ox + 30, oy + 40]
                assert result[1]["line_points"] == [[0, height / 2], [width, height / 2]]
    if feature == "detect_logistics_single_person":
        assert [args[1].count for args in snapshots] == [1, 1]
