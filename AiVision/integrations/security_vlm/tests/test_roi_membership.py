# 文件说明：包含感兴趣区域的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import json
import math
import numpy as np
import pytest

try:
    from AiVision.integrations.security_vlm.src import roi_geometry
except ModuleNotFoundError:
    roi_geometry = None

from AiVision.integrations.security_vlm.src import main as security_main
from AiVision.integrations.security_vlm.src import session_worker


# 功能：验证 `test_roi_geometry_module_exists` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_roi_geometry_module_exists():
    assert roi_geometry is not None, "shared roi_geometry module is required"


def test_roi_requires_polygon_points():
    with pytest.raises(ValueError, match="坐标必须为"):
        roi_geometry.normalize_roi_points([100, 80, 20, 10])



# 功能：验证 `test_polygon_normalization_area_and_bounds` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.normalize_roi_points`、`roi_geometry.polygon_area`、`pytest.approx`、`roi_geometry.roi_bounds`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_polygon_normalization_area_and_bounds():
    polygon = [[0, 0], [80, 0], [100, 30], [40, 90], [0, 50]]

    normalized = roi_geometry.normalize_roi_points(polygon)

    assert normalized == [
        [0.0, 0.0],
        [80.0, 0.0],
        [100.0, 30.0],
        [40.0, 90.0],
        [0.0, 50.0],
    ]
    assert roi_geometry.polygon_area(normalized) == pytest.approx(6100.0)
    assert roi_geometry.roi_bounds(normalized) == [0.0, 0.0, 100.0, 90.0]


# 功能：验证 `test_roi_mapping_scales_between_per_camera_stream_dimensions` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.scale_roi_mapping`、`roi_geometry.roi_mapping_exceeds_bounds`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_roi_mapping_scales_between_per_camera_stream_dimensions():
    rois = {
        "工位": [[100, 200], [2100, 200], [2100, 1200], [100, 1200]],
    }

    assert roi_geometry.scale_roi_mapping(
        rois,
        source_width=2560,
        source_height=1440,
        target_width=768,
        target_height=432,
    ) == {
        "工位": [[30.0, 60.0], [630.0, 60.0], [630.0, 360.0], [30.0, 360.0]],
    }
    assert roi_geometry.roi_mapping_exceeds_bounds(rois, 768, 432) is True
    assert roi_geometry.roi_mapping_exceeds_bounds(rois, 2560, 1440) is False


# 功能：验证 `test_normalize_roi_points_rejects_malformed_values` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `values`（未显式标注）：`values` 对应的业务输入值
#   - `error`（未显式标注）：待报告、转换或判断的异常对象
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`roi_geometry.normalize_roi_points`、`pytest.mark.parametrize`、`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    "values, error",
    [
        ([[0, 0], [10, 0]], "至少 3 个点"),
        ([[0, 0], [10], [0, 10]], "坐标"),
        ([[0, 0], [float("nan"), 0], [0, 10]], "有限"),
        ([[0, 0], [float("inf"), 0], [0, 10]], "有限"),
    ],
)
def test_normalize_roi_points_rejects_malformed_values(values, error):
    with pytest.raises(ValueError, match=error):
        roi_geometry.normalize_roi_points(values)


# 功能：验证 `test_normalize_roi_points_only_accepts_finite_json_numbers` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（未显式标注）：待转换、校验或写入的值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`roi_geometry.normalize_roi_points`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("value", [True, "12.5", 10**400])
def test_normalize_roi_points_only_accepts_finite_json_numbers(value):
    with pytest.raises(ValueError, match="数字|有限"):
        roi_geometry.normalize_roi_points([[0, 0], [value, 0], [0, 20]])


# 功能：验证 `test_validate_rois_normalizes_and_rejects_invalid_geometry` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.validate_rois`、`float`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_validate_rois_normalizes_and_rejects_invalid_geometry():
    assert roi_geometry.validate_rois(
        {"工位 A": [[10, 20], [80, 20], [80, 70], [10, 70]]},
        width=100,
        height=80,
        min_area=100,
    ) == {
        "工位 A": [
            [10.0, 20.0],
            [80.0, 20.0],
            [80.0, 70.0],
            [10.0, 70.0],
        ]
    }

    invalid_cases = [
        ({"": [[0, 0], [20, 0], [0, 20]]}, "名称不能为空"),
        ({"少点": [[0, 0], [20, 0]]}, "少点.*至少 3 个点"),
        ({"非有限": [[0, 0], [float("nan"), 0], [0, 20]]}, "非有限.*有限"),
        ({"越界": [[0, 0], [101, 0], [0, 20]]}, "越界.*画面范围"),
        ({"太小": [[0, 0], [5, 0], [0, 5]]}, "太小.*面积"),
    ]
    for rois, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            roi_geometry.validate_rois(
                rois,
                width=100,
                height=80,
                min_area=100,
            )


# 功能：验证 `test_validate_rois_rejects_non_simple_or_rounded_duplicate_polygons` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `points`（未显式标注）：`points` 对应的业务输入值
#   - `message`（未显式标注）：用于展示、记录或发送的文本消息
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`roi_geometry.validate_rois`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    "points, message",
    [
        (
            [[0, 0], [50, 0], [50, 50], [0, 0]],
            "重复",
        ),
        (
            [[0, 0], [50, 50], [0, 50], [50, 0]],
            "自相交",
        ),
        (
            [[0, 0], [50, 0], [50, 50], [25, 0], [0, 50]],
            "自相交",
        ),
        (
            [[0, 0], [10, 0], [10.004, 0.004], [0, 10]],
            "重复",
        ),
        (
            [[0, 0], [10, 0], [5, 0]],
            "重叠",
        ),
        (
            [[0, 0], [0.004, 0], [0, 0.004]],
            "唯一",
        ),
    ],
)
def test_validate_rois_rejects_non_simple_or_rounded_duplicate_polygons(
    points,
    message,
):
    with pytest.raises(ValueError, match=message):
        roi_geometry.validate_rois(
            {"问题工位": points},
            width=100,
            height=100,
            min_area=0,
        )


# 功能：验证 `test_validate_rois_checks_area_after_rounding_final_coordinates` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`roi_geometry.validate_rois`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_validate_rois_checks_area_after_rounding_final_coordinates():
    with pytest.raises(ValueError, match="面积"):
        roi_geometry.validate_rois(
            {"舍入后太小": [[0, 0], [10.004, 0], [0, 10.004]]},
            width=100,
            height=100,
            min_area=50.02,
        )


# 功能：验证 `test_validate_rois_rejects_vertex_count_over_configured_limit` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`math.cos`、`math.sin`、`range`、`pytest.raises`、`roi_geometry.validate_rois`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_validate_rois_rejects_vertex_count_over_configured_limit():
    polygon = [
        [
            50 + 40 * math.cos(2 * math.pi * index / 65),
            50 + 40 * math.sin(2 * math.pi * index / 65),
        ]
        for index in range(65)
    ]

    with pytest.raises(ValueError, match="64"):
        roi_geometry.validate_rois(
            {"超限工位": polygon},
            width=100,
            height=100,
            min_area=0,
            max_vertices=64,
        )


# 功能：验证 `test_validate_rois_returns_rounded_persistence_points` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.validate_rois`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_validate_rois_returns_rounded_persistence_points():
    assert roi_geometry.validate_rois(
        {"工位": [[0.004, 0.004], [20.006, 0.004], [0.004, 20.006]]},
        width=100,
        height=100,
        min_area=1,
    ) == {
        "工位": [[0.0, 0.0], [20.01, 0.0], [0.0, 20.01]]
    }


# 功能：验证 `test_center_inside_counts_even_when_person_overlap_is_small` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.bbox_roi_overlap_ratio`、`pytest.approx`、`roi_geometry.bbox_belongs_to_roi`、`pytest.mark.skipif`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.skipif(roi_geometry is None, reason="roi_geometry is not implemented")
def test_center_inside_counts_even_when_person_overlap_is_small():
    person_box = [-950, 0, 1050, 100]
    roi = [[0, 0], [100, 0], [100, 100], [0, 100]]

    assert roi_geometry.bbox_roi_overlap_ratio(person_box, roi) == pytest.approx(0.05)
    assert roi_geometry.bbox_belongs_to_roi(person_box, roi, 0.30)


# 功能：验证 `test_partial_overlap_uses_person_box_area_for_entry` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.bbox_roi_overlap_ratio`、`pytest.approx`、`roi_geometry.bbox_belongs_to_roi`、`pytest.mark.skipif`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.skipif(roi_geometry is None, reason="roi_geometry is not implemented")
def test_partial_overlap_uses_person_box_area_for_entry():
    person_box = [70, 0, 170, 100]
    roi = [[0, 0], [100, 0], [100, 100], [0, 100]]

    assert roi_geometry.bbox_roi_overlap_ratio(person_box, roi) == pytest.approx(0.30)
    assert roi_geometry.bbox_belongs_to_roi(person_box, roi, 0.30)


# 功能：验证 `test_hold_threshold_keeps_edge_person_without_allowing_new_entry` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.bbox_roi_overlap_ratio`、`pytest.approx`、`roi_geometry.bbox_belongs_to_roi`、`pytest.mark.skipif`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.skipif(roi_geometry is None, reason="roi_geometry is not implemented")
def test_hold_threshold_keeps_edge_person_without_allowing_new_entry():
    person_box = [85, 0, 185, 100]
    roi = [[0, 0], [100, 0], [100, 100], [0, 100]]

    assert roi_geometry.bbox_roi_overlap_ratio(person_box, roi) == pytest.approx(0.15)
    assert not roi_geometry.bbox_belongs_to_roi(person_box, roi, 0.30)
    assert roi_geometry.bbox_belongs_to_roi(person_box, roi, 0.10)


# 功能：验证 `test_disjoint_and_invalid_person_boxes_are_outside` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.bbox_belongs_to_roi`、`roi_geometry.bbox_roi_overlap_ratio`、`pytest.mark.skipif`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.skipif(roi_geometry is None, reason="roi_geometry is not implemented")
def test_disjoint_and_invalid_person_boxes_are_outside():
    roi = [[0, 0], [100, 0], [100, 100], [0, 100]]

    assert not roi_geometry.bbox_belongs_to_roi([101, 0, 201, 100], roi, 0.10)
    assert roi_geometry.bbox_roi_overlap_ratio([10, 10, 10, 30], roi) == 0.0
    assert not roi_geometry.bbox_belongs_to_roi([10, 10, 10, 30], roi, 0.0)


# 功能：验证 `test_reversed_coordinates_are_normalized` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.bbox_roi_overlap_ratio`、`pytest.approx`、`roi_geometry.bbox_belongs_to_roi`、`pytest.mark.skipif`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.skipif(roi_geometry is None, reason="roi_geometry is not implemented")
def test_reversed_coordinates_are_normalized():
    person_box = [170, 100, 70, 0]
    roi = [[100, 100], [0, 100], [0, 0], [100, 0]]

    assert roi_geometry.bbox_roi_overlap_ratio(person_box, roi) == pytest.approx(0.30)
    assert roi_geometry.bbox_belongs_to_roi(person_box, roi, 0.30)


# 功能：验证 `test_convex_polygon_membership_does_not_use_its_bounding_rectangle` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.point_in_polygon`、`roi_geometry.bbox_belongs_to_roi`、`roi_geometry.bbox_roi_overlap_ratio`、`pytest.approx`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_convex_polygon_membership_does_not_use_its_bounding_rectangle():
    triangle = [[0, 0], [100, 0], [0, 100]]

    assert roi_geometry.point_in_polygon([50, 50], triangle)
    assert roi_geometry.point_in_polygon([100, 0], triangle)
    assert not roi_geometry.bbox_belongs_to_roi(
        [70, 70, 90, 90],
        triangle,
        0.01,
    )
    assert roi_geometry.bbox_roi_overlap_ratio(
        [80, 0, 120, 40],
        triangle,
    ) == pytest.approx(0.125)
    assert roi_geometry.bbox_belongs_to_roi(
        [80, 0, 120, 40],
        triangle,
        0.125,
    )


# 功能：验证 `test_concave_polygon_membership_and_overlap_are_exact` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`roi_geometry.point_in_polygon`、`roi_geometry.bbox_belongs_to_roi`、`roi_geometry.bbox_roi_overlap_ratio`、`pytest.approx`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_concave_polygon_membership_and_overlap_are_exact():
    concave = [[0, 0], [100, 0], [100, 40], [40, 40], [40, 100], [0, 100]]

    assert roi_geometry.point_in_polygon([40, 70], concave)
    assert not roi_geometry.point_in_polygon([70, 70], concave)
    assert not roi_geometry.bbox_belongs_to_roi(
        [50, 50, 90, 90],
        concave,
        0.01,
    )
    assert roi_geometry.bbox_roi_overlap_ratio(
        [30, 50, 70, 90],
        concave,
    ) == pytest.approx(0.25)


# 功能：验证 `test_session_manager_uses_looser_overlap_for_active_session` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`session_worker.PairSessionManager`、`manager._tracks_for_roi`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_session_manager_uses_looser_overlap_for_active_session(tmp_path):
    manager = session_worker.PairSessionManager(
        {
            "data": {"department": "fulida_company", "video_id": "camera-a"},
            "session": {
                "roi_enter_overlap_ratio": 0.30,
                "roi_hold_overlap_ratio": 0.10,
            },
        },
        tmp_path,
    )
    edge_track = {
        "track_id": 7,
        "x1": 85,
        "y1": 0,
        "x2": 185,
        "y2": 100,
    }
    roi = [[0, 0], [100, 0], [100, 100], [0, 100]]

    assert manager._tracks_for_roi([edge_track], roi, active=False) == []
    assert manager._tracks_for_roi([edge_track], roi, active=True) == [edge_track]


# 功能：验证 `test_session_worker_reload_preserves_all_polygon_vertices` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`path.write_text`、`json.dumps`、`session_worker.reload_rois`、`float`、`path.stat`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_session_worker_reload_preserves_all_polygon_vertices(tmp_path):
    path = tmp_path / "camera_staff_rois.json"
    polygon = [[1, 2], [90, 3], [80, 70], [20, 90], [3, 50]]
    path.write_text(
        json.dumps({"staff_rois": {"多边形工位": polygon}}),
        encoding="utf-8",
    )

    rois, mtime = session_worker.reload_rois(path, {}, 0.0)

    assert rois == {
        "多边形工位": [[float(x), float(y)] for x, y in polygon]
    }
    assert mtime == path.stat().st_mtime


# 功能：验证 `test_session_worker_reload_scales_roi_to_actual_frame_dimensions` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`path.write_text`、`json.dumps`、`session_worker.reload_rois`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_session_worker_reload_scales_roi_to_actual_frame_dimensions(tmp_path):
    path = tmp_path / "camera_staff_rois.json"
    path.write_text(
        json.dumps({
            "source_width": 2560,
            "source_height": 1440,
            "staff_rois": {
                "子码流工位": [[100, 200], [2100, 200], [2100, 1200], [100, 1200]],
            },
        }),
        encoding="utf-8",
    )

    rois, _mtime = session_worker.reload_rois(
        path,
        {},
        0.0,
        frame_width=768,
        frame_height=432,
    )

    assert rois == {
        "子码流工位": [[30.0, 60.0], [630.0, 60.0], [630.0, 360.0], [30.0, 360.0]],
    }


# 功能：验证 `test_session_worker_does_not_rescale_last_known_good_roi_twice` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`path.write_text`、`json.dumps`、`session_worker.reload_rois`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_session_worker_does_not_rescale_last_known_good_roi_twice(tmp_path):
    path = tmp_path / "camera_staff_rois.json"
    path.write_text(
        json.dumps({
            "source_width": 200,
            "source_height": 100,
            "staff_rois": {
                "保留": [[0, 0], [True, 10], [10, 0]],
                "更新": [[20, 20], [100, 20], [20, 80]],
            },
        }),
        encoding="utf-8",
    )
    previous = {
        "保留": [[5.0, 5.0], [30.0, 5.0], [5.0, 30.0]],
    }

    rois, _mtime = session_worker.reload_rois(
        path,
        previous,
        0.0,
        frame_width=100,
        frame_height=50,
    )

    assert rois == {
        "保留": previous["保留"],
        "更新": [[10.0, 10.0], [50.0, 10.0], [10.0, 40.0]],
    }


# 功能：验证 `test_session_worker_reload_updates_valid_rois_and_keeps_only_named_lkg` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `capsys`（未显式标注）：`capsys` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`path.write_text`、`json.dumps`、`session_worker.reload_rois`、`path.stat`、`capsys.readouterr`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_session_worker_reload_updates_valid_rois_and_keeps_only_named_lkg(
    tmp_path,
    capsys,
):
    path = tmp_path / "camera_staff_rois.json"
    old_kept = [[1.0, 1.0], [40.0, 1.0], [1.0, 40.0]]
    old_deleted = [[50.0, 50.0], [90.0, 50.0], [50.0, 90.0]]
    path.write_text(
        json.dumps(
            {
                "staff_rois": {
                    "保留旧值": [[0, 0], [True, 10], [10, 0]],
                    "合法新值": [[2, 2], [60, 2], [2, 60]],
                    "新增坏值": [[0, 0], [10, 0]],
                }
            }
        ),
        encoding="utf-8",
    )

    rois, mtime = session_worker.reload_rois(
        path,
        {"保留旧值": old_kept, "已删除": old_deleted},
        0.0,
    )

    assert rois == {
        "保留旧值": old_kept,
        "合法新值": [[2.0, 2.0], [60.0, 2.0], [2.0, 60.0]],
    }
    assert mtime == path.stat().st_mtime
    assert "保留旧值" in capsys.readouterr().out


# 功能：验证 `test_session_worker_default_roi_normalization_ignores_only_bad_items` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `capsys`（未显式标注）：`capsys` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`session_worker._normalize_roi_mapping`、`capsys.readouterr`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_session_worker_default_roi_normalization_ignores_only_bad_items(capsys):
    rois = session_worker._normalize_roi_mapping(
        {
            "合法": [[0, 0], [20, 0], [20, 20], [0, 20]],
            "坏值": [[0, 0], [10, 0]],
            "超大": [[0, 0], [10**400, 0], [0, 10]],
        }
    )

    assert rois == {
        "合法": [[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]
    }
    output = capsys.readouterr().out
    assert "坏值" in output
    assert "超大" in output


# 功能：验证 `test_session_worker_reload_keeps_whole_cache_for_invalid_json_structure` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `capsys`（未显式标注）：`capsys` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`path.write_text`、`session_worker.reload_rois`、`capsys.readouterr`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_session_worker_reload_keeps_whole_cache_for_invalid_json_structure(
    tmp_path,
    capsys,
):
    path = tmp_path / "camera_staff_rois.json"
    path.write_text("[]", encoding="utf-8")
    cached = {"稳定工位": [[0.0, 0.0], [20.0, 0.0], [0.0, 20.0]]}

    rois, mtime = session_worker.reload_rois(path, cached, 0.0)

    assert rois == cached
    assert mtime == 0.0
    assert "热加载失败" in capsys.readouterr().out


# 功能：验证 `test_new_pair_session_keeps_polygon_bounds_as_roi_box` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`session_worker.PairSessionManager`、`monkeypatch.setattr`、`manager.step`、`np.zeros`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_new_pair_session_keeps_polygon_bounds_as_roi_box(tmp_path, monkeypatch):
    manager = session_worker.PairSessionManager(
        {
            "data": {"department": "fulida_company", "video_id": "camera-a"},
            "session": {
                "pair_start_hold_frames": 1,
                "roi_enter_overlap_ratio": 0.30,
                "roi_hold_overlap_ratio": 0.10,
            },
        },
        tmp_path,
    )
    monkeypatch.setattr(
        manager,
        "_find_interacting_pair",
        lambda _state, _tracks: (1, 2),
    )
    polygon = [[5, 5], [90, 10], [75, 95], [10, 70]]
    tracks = [
        {"track_id": 1, "x1": 10, "y1": 10, "x2": 30, "y2": 50},
        {"track_id": 2, "x1": 35, "y1": 10, "x2": 55, "y2": 50},
    ]

    manager.step(np.zeros((100, 100, 3), dtype=np.uint8), tracks, {"A": polygon})

    assert manager.roi_states["A"].active is not None
    assert manager.roi_states["A"].active.roi_box == [5.0, 5.0, 90.0, 95.0]


# 功能：验证 `test_deleted_roi_cancels_active_session_without_pending_task` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `capsys`（未显式标注）：`capsys` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`session_worker.PairSessionManager`、`monkeypatch.setattr`、`np.zeros`、`manager.step`、`manager.roi_states['会删除'].active.keyframes.extend`、`list`、`tmp_path.iterdir`、`capsys.readouterr`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_deleted_roi_cancels_active_session_without_pending_task(
    tmp_path,
    monkeypatch,
    capsys,
):
    manager = session_worker.PairSessionManager(
        {
            "data": {"department": "fulida_company", "video_id": "camera-a"},
            "session": {
                "pair_start_hold_frames": 1,
                "roi_enter_overlap_ratio": 0.30,
                "roi_hold_overlap_ratio": 0.10,
            },
        },
        tmp_path,
    )
    monkeypatch.setattr(
        manager,
        "_find_interacting_pair",
        lambda _state, _tracks: (1, 2),
    )
    tracks = [
        {"track_id": 1, "x1": 10, "y1": 10, "x2": 30, "y2": 50},
        {"track_id": 2, "x1": 35, "y1": 10, "x2": 55, "y2": 50},
    ]
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    manager.step(frame, tracks, {"会删除": [[0, 0], [80, 0], [80, 80], [0, 80]]})
    manager.roi_states["会删除"].active.keyframes.extend([frame, frame])

    manager.step(frame, tracks, {})

    assert "会删除" not in manager.roi_states
    assert list(tmp_path.iterdir()) == []
    assert "取消" in capsys.readouterr().out


# 功能：验证 `test_session_manager_rejects_hold_threshold_above_enter_threshold` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`session_worker.PairSessionManager`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_session_manager_rejects_hold_threshold_above_enter_threshold(tmp_path):
    with pytest.raises(ValueError, match="roi_hold_overlap_ratio"):
        session_worker.PairSessionManager(
            {
                "data": {"department": "fulida_company", "video_id": "camera-a"},
                "session": {
                    "roi_enter_overlap_ratio": 0.20,
                    "roi_hold_overlap_ratio": 0.30,
                },
            },
            tmp_path,
        )


# 功能：验证 `test_rule_overlay_colors_roi_members_green_and_outside_tracks_gray` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`security_main._overlay_on_frame`、`np.zeros`、`FakeService`、`polygon.tolist`、`len`、`rectangle_colors.count`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_rule_overlay_colors_roi_members_green_and_outside_tracks_gray(monkeypatch):
    # 功能：定义 `FakeStore` 类，封装感兴趣区域相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeStore；返回新建的 `FakeStore` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_roi_membership.py` 的
    #         `test_rule_overlay_colors_roi_members_green_and_outside_tracks_gray::FakeService` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeStore:
        values = {
            "session_latest": {},
            "tracker_latest": {
                "frame_meta": {"width": 200, "height": 100},
                "tracks": [
                    {
                        "track_id": 1,
                        "x1": 20,
                        "y1": 20,
                        "x2": 80,
                        "y2": 80,
                    },
                    {
                        "track_id": 2,
                        "x1": 120,
                        "y1": 0,
                        "x2": 180,
                        "y2": 100,
                    },
                ],
            },
            "vlm_latest_stats": {},
        }

        # 功能：读取或查询 `read` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `key`（未显式标注）：用于查询、分组或缓存的键
        #   - `default`（未显式标注）：`default` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self.values.get`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def read(self, key, default):
            return self.values.get(key, default)

    # 功能：定义 `FakeService` 类，封装感兴趣区域相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeService；返回新建的 `FakeService` 实例。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`FakeStore`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeService:
        cfg = {"session": {"roi_enter_overlap_ratio": 0.30}}
        @staticmethod
        def camera_store(camera_id, department):
            assert camera_id == "camera-a" and department == "fulida_company"
            return FakeStore()

        @staticmethod
        def workspace(department):
            from types import SimpleNamespace
            assert department == "fulida_company"
            return SimpleNamespace(result_store=FakeStore())

        # 功能：读取或查询 `get_rois_cached` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        @staticmethod
        def get_rois_cached(camera_id, department):
            return {
                "security_staff_1": [
                    [0, 0],
                    [100, 0],
                    [0, 100],
                ],
                "security_staff_2": [
                    [190, 90],
                    [200, 90],
                    [200, 100],
                ],
            }

    rectangle_colors = []
    filled_polygons = []
    outlined_polygons = []
    blend_calls = []

    # 功能：实现 `record_rectangle` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `image`（未显式标注）：待处理的图像数据
    #   - `point1`（未显式标注）：`point1` 对应的业务输入值
    #   - `point2`（未显式标注）：`point2` 对应的业务输入值
    #   - `color`（未显式标注）：`color` 对应的业务输入值
    #   - `thickness`（未显式标注）：`thickness` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`rectangle_colors.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def record_rectangle(image, point1, point2, color, thickness):
        del point1, point2, thickness
        rectangle_colors.append(color)
        return image

    # 功能：实现 `record_fill_poly` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `image`（未显式标注）：待处理的图像数据
    #   - `polygons`（未显式标注）：`polygons` 对应的业务输入值
    #   - `color`（未显式标注）：`color` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`filled_polygons.extend`、`polygon.copy`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def record_fill_poly(image, polygons, color):
        del color
        filled_polygons.extend(polygon.copy() for polygon in polygons)
        return image

    # 功能：实现 `record_polylines` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `image`（未显式标注）：待处理的图像数据
    #   - `polygons`（未显式标注）：`polygons` 对应的业务输入值
    #   - `closed`（未显式标注）：`closed` 对应的业务输入值
    #   - `color`（未显式标注）：`color` 对应的业务输入值
    #   - `thickness`（未显式标注）：`thickness` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`outlined_polygons.extend`、`polygon.copy`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def record_polylines(image, polygons, closed, color, thickness):
        del closed, color, thickness
        outlined_polygons.extend(polygon.copy() for polygon in polygons)
        return image

    # 功能：创建或构建 `record_add_weighted` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `source1`（未显式标注）：`source1` 对应的业务输入值
    #   - `alpha`（未显式标注）：`alpha` 对应的业务输入值
    #   - `source2`（未显式标注）：`source2` 对应的业务输入值
    #   - `beta`（未显式标注）：`beta` 对应的业务输入值
    #   - `gamma`（未显式标注）：`gamma` 对应的业务输入值
    #   - `destination`（未显式标注）：`destination` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`blend_calls.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def record_add_weighted(source1, alpha, source2, beta, gamma, destination):
        del source1, alpha, source2, beta, gamma
        blend_calls.append(destination)
        return destination

    monkeypatch.setattr(security_main.cv2, "rectangle", record_rectangle)
    monkeypatch.setattr(security_main.cv2, "fillPoly", record_fill_poly)
    monkeypatch.setattr(security_main.cv2, "polylines", record_polylines)
    monkeypatch.setattr(security_main.cv2, "addWeighted", record_add_weighted)

    security_main._overlay_on_frame(
        np.zeros((100, 200, 3), dtype=np.uint8),
        FakeService(), "camera-a", "fulida_company",
    )

    assert [polygon.tolist() for polygon in filled_polygons] == [
        [[0, 0], [100, 0], [0, 100]],
        [[190, 90], [200, 90], [200, 100]],
    ]
    assert [polygon.tolist() for polygon in outlined_polygons] == [
        [[0, 0], [100, 0], [0, 100]],
        [[190, 90], [200, 90], [200, 100]],
    ]
    assert len(blend_calls) == 1
    assert rectangle_colors.count((0, 255, 0)) == 1
    assert rectangle_colors.count((128, 128, 128)) == 1
