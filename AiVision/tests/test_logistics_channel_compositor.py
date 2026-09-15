# 文件说明：包含`test_logistics_channel_compositor` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

import AiVision.features.logistics_channel.compositor as compositor
from AiVision.features.logistics_channel.compositor import (
    CameraTile,
    compose_channel_frame,
    layout_for_count,
    letterbox,
    render_placeholder,
)


# 功能：验证 `test_layout_for_count_uses_defined_channel_grid` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `count`（未显式标注）：`count` 对应的数量或大小
#   - `expected`（未显式标注）：`expected` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`layout_for_count`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, (1, 1)), (2, (1, 2)), (3, (2, 2)), (4, (2, 2)), (5, (3, 3)), (9, (3, 3))],
)
def test_layout_for_count_uses_defined_channel_grid(count, expected):
    assert layout_for_count(count) == expected


# 功能：验证 `test_layout_for_count_rejects_out_of_range_counts` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `count`（未显式标注）：`count` 对应的数量或大小
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`layout_for_count`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("count", [0, 10])
def test_layout_for_count_rejects_out_of_range_counts(count):
    with pytest.raises(ValueError):
        layout_for_count(count)


# 功能：验证 `test_camera_tile_is_immutable` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`CameraTile`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_tile_is_immutable():
    tile = CameraTile(1, "入口", None, "waiting", None, False)

    with pytest.raises(FrozenInstanceError):
        tile.camera_name = "changed"


# 功能：验证 `test_letterbox_preserves_landscape_content_ratio_and_input` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`np.full`、`frame.copy`、`letterbox`、`np.array_equal`、`np.all`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_letterbox_preserves_landscape_content_ratio_and_input():
    frame = np.full((20, 80, 3), (12, 34, 56), dtype=np.uint8)
    original = frame.copy()

    result = letterbox(frame, target_size=(100, 100), fill_color=(1, 2, 3))

    assert result.shape == (100, 100, 3)
    assert np.array_equal(frame, original)
    assert np.all(result[:37] == (1, 2, 3))
    assert np.all(result[37:62] == (12, 34, 56))
    assert np.all(result[62:] == (1, 2, 3))


# 功能：验证 `test_letterbox_preserves_portrait_content_ratio` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`np.full`、`letterbox`、`np.all`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_letterbox_preserves_portrait_content_ratio():
    frame = np.full((80, 20, 3), 99, dtype=np.uint8)

    result = letterbox(frame, target_size=(100, 100), fill_color=(0, 0, 0))

    assert np.all(result[:, :37] == 0)
    assert np.all(result[:, 37:62] == 99)
    assert np.all(result[:, 62:] == 0)


# 功能：验证 `test_letterbox_rejects_missing_or_invalid_frames` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `frame`（未显式标注）：待处理的视频图像帧
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`letterbox`、`pytest.mark.parametrize`、`np.empty`、`np.ones`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    "frame",
    [None, np.empty((0, 0, 3), dtype=np.uint8), np.ones((4, 4, 3), dtype=np.float32)],
)
def test_letterbox_rejects_missing_or_invalid_frames(frame):
    with pytest.raises(ValueError):
        letterbox(frame)


# 功能：验证 `test_render_placeholder_is_nonempty_bgr_for_unicode_text` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`render_placeholder`、`np.any`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_render_placeholder_is_nonempty_bgr_for_unicode_text():
    result = render_placeholder("东门摄像头", "等待视频流", (120, 60))

    assert result.shape == (60, 120, 3)
    assert result.dtype == np.uint8
    assert result.flags.c_contiguous
    assert np.any(result)


# 功能：验证 `test_compose_channel_frame_uses_expected_grid_shapes` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `count`（未显式标注）：`count` 对应的数量或大小
#   - `expected_shape`（未显式标注）：`expected_shape` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`CameraTile`、`np.full`、`range`、`compose_channel_frame`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    ("count", "expected_shape"),
    [
        (1, (30, 40, 3)),
        (2, (30, 80, 3)),
        (3, (60, 80, 3)),
        (4, (60, 80, 3)),
        (5, (90, 120, 3)),
        (9, (90, 120, 3)),
    ],
)
def test_compose_channel_frame_uses_expected_grid_shapes(count, expected_shape):
    tiles = [CameraTile(i, f"cam-{i}", np.full((10, 10, 3), i, np.uint8), "normal", 1, True) for i in range(count)]

    result = compose_channel_frame(tiles, tile_size=(40, 30))

    assert result.shape == expected_shape
    assert result.dtype == np.uint8
    assert result.flags.c_contiguous


# 功能：验证 `test_compose_channel_frame_rejects_empty_or_too_many_tiles` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tiles`（未显式标注）：`tiles` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`compose_channel_frame`、`pytest.mark.parametrize`、`CameraTile`、`str`、`range`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("tiles", [[], [CameraTile(i, str(i), None, "waiting", None, False) for i in range(10)]])
def test_compose_channel_frame_rejects_empty_or_too_many_tiles(tiles):
    with pytest.raises(ValueError):
        compose_channel_frame(tiles)


# 功能：验证 `test_compose_channel_frame_places_tiles_in_input_order` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`CameraTile`、`str`、`np.full`、`enumerate`、`compose_channel_frame`、`tuple`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_compose_channel_frame_places_tiles_in_input_order():
    colors = [(10, 20, 30), (40, 50, 60)]
    tiles = [CameraTile(index, str(index), np.full((20, 20, 3), color, np.uint8), "normal", 1, True) for index, color in enumerate(colors)]

    result = compose_channel_frame(tiles, tile_size=(40, 30))

    assert tuple(result[25, 20]) == colors[0]
    assert tuple(result[25, 60]) == colors[1]


# 功能：验证 `test_live_camera_frame_top_pixels_are_not_covered_by_status_banner` 对应的`test_logistics_channel_compositor`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `reason`（未显式标注）：`reason` 对应的业务输入值
#   - `person_count`（未显式标注）：`person_count` 对应的数量或大小
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`np.full`、`CameraTile`、`compose_channel_frame`、`np.all`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    ("reason", "person_count"),
    [("normal", 1), ("empty", 0), ("multiple", 2)],
)
def test_live_camera_frame_top_pixels_are_not_covered_by_status_banner(reason, person_count):
    color = (17, 83, 149)
    frame = np.full((30, 40, 3), color, dtype=np.uint8)
    tile = CameraTile(1, "cam", frame, reason, person_count, True)

    result = compose_channel_frame([tile], tile_size=(40, 30))

    assert np.all(result[0] == color)


# 功能：验证 `test_compose_channel_frame_replaces_invalid_frame_without_losing_other_tile` 对应的`test_logistics_channel_compositor`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`np.full`、`CameraTile`、`compose_channel_frame`、`np.any`、`tuple`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_compose_channel_frame_replaces_invalid_frame_without_losing_other_tile():
    valid = np.full((20, 20, 3), (7, 8, 9), np.uint8)
    tiles = [
        CameraTile(1, "坏帧", None, "offline", None, False, "network disconnected"),
        CameraTile(2, "正常", valid, "normal", 1, True),
    ]

    result = compose_channel_frame(tiles, tile_size=(40, 30))

    assert np.any(result[:, :40])
    assert tuple(result[25, 60]) == (7, 8, 9)


# 功能：验证 `test_compose_channel_frame_accepts_grayscale_and_bgra_frames` 对应的`test_logistics_channel_compositor`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `frame`（未显式标注）：待处理的视频图像帧
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`compose_channel_frame`、`CameraTile`、`pytest.mark.parametrize`、`np.full`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("frame", [np.full((8, 8), 128, np.uint8), np.full((8, 8, 4), 128, np.uint8)])
def test_compose_channel_frame_accepts_grayscale_and_bgra_frames(frame):
    result = compose_channel_frame([CameraTile(1, "very-long-camera-name-" * 20, frame, "unknown", None, True, "detail-" * 100)], tile_size=(40, 30))

    assert result.shape == (30, 40, 3)
    assert result.dtype == np.uint8


# 功能：验证 `test_compose_channel_frame_rejects_invalid_tile_size` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tile_size`（未显式标注）：`tile_size` 对应的数量或大小
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`compose_channel_frame`、`CameraTile`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("tile_size", [(0, 10), (10, 0), (4097, 10), (10, 4097), (10,), "bad"])
def test_compose_channel_frame_rejects_invalid_tile_size(tile_size):
    with pytest.raises(ValueError):
        compose_channel_frame([CameraTile(1, "cam", None, "waiting", None, False)], tile_size=tile_size)


# 功能：验证 `test_placeholder_preserves_unicode_camera_name_and_actual_reason_in_text_renderer` 对应的`test_logistics_channel_compositor`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`render_placeholder`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_placeholder_preserves_unicode_camera_name_and_actual_reason_in_text_renderer(monkeypatch):
    rendered_text = []

    # 功能：实现 `record_text` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `image`（未显式标注）：待处理的图像数据
    #   - `text`（未显式标注）：`text` 对应的业务输入值
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`rendered_text.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def record_text(image, text, *args, **kwargs):
        rendered_text.append(text)
        return image

    monkeypatch.setattr(compositor, "_draw_text", record_text, raising=False)

    render_placeholder("一号物流通道摄像头", "离线/等待画面", (240, 100))

    assert "一号物流通道摄像头" in rendered_text
    assert "离线/等待画面" in rendered_text


# 功能：验证 `test_text_renderer_survives_missing_explicit_font` 对应的`test_logistics_channel_compositor` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`np.zeros`、`compositor._draw_text`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_text_renderer_survives_missing_explicit_font():
    image = np.zeros((80, 240, 3), dtype=np.uint8)

    result = compositor._draw_text(
        image,
        "一号物流通道摄像头",
        (5, 25),
        (255, 255, 255),
        font_path="/definitely/missing/font.ttf",
    )

    assert result.shape == image.shape
    assert result.dtype == np.uint8
    assert result.flags.c_contiguous


# 功能：验证 `test_offline_tile_hides_valid_cached_frame_and_keeps_placeholder` 对应的`test_logistics_channel_compositor`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`np.full`、`CameraTile`、`compose_channel_frame`、`tuple`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_offline_tile_hides_valid_cached_frame_and_keeps_placeholder(monkeypatch):
    monkeypatch.setattr(compositor, "_draw_text", lambda image, *args, **kwargs: image)
    cached_frame = np.full((20, 20, 3), (7, 8, 9), dtype=np.uint8)
    tile = CameraTile(1, "cam", cached_frame, "normal", 1, False, "stream disconnected")

    result = compose_channel_frame([tile], tile_size=(120, 100))

    assert tuple(result[75, 60]) == (45, 45, 45)
    assert tuple(result[0, 0]) == (100, 100, 100)
