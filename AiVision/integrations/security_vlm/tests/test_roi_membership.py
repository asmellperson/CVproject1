import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

try:
    import roi_geometry
except ModuleNotFoundError:
    roi_geometry = None

import session_worker  # noqa: E402
import main as security_main  # noqa: E402


def test_roi_geometry_module_exists():
    assert roi_geometry is not None, "shared roi_geometry module is required"


def test_legacy_rectangle_is_normalized_to_four_polygon_points():
    assert roi_geometry.normalize_roi_points([100, 80, 20, 10]) == [
        [20.0, 10.0],
        [100.0, 10.0],
        [100.0, 80.0],
        [20.0, 80.0],
    ]


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


@pytest.mark.parametrize("value", [True, "12.5", 10**400])
def test_normalize_roi_points_only_accepts_finite_json_numbers(value):
    with pytest.raises(ValueError, match="数字|有限"):
        roi_geometry.normalize_roi_points([[0, 0], [value, 0], [0, 20]])


def test_validate_rois_normalizes_and_rejects_invalid_geometry():
    assert roi_geometry.validate_rois(
        {"工位 A": [10, 20, 80, 70]},
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


def test_validate_rois_checks_area_after_rounding_final_coordinates():
    with pytest.raises(ValueError, match="面积"):
        roi_geometry.validate_rois(
            {"舍入后太小": [[0, 0], [10.004, 0], [0, 10.004]]},
            width=100,
            height=100,
            min_area=50.02,
        )


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


def test_validate_rois_returns_rounded_persistence_points():
    assert roi_geometry.validate_rois(
        {"工位": [[0.004, 0.004], [20.006, 0.004], [0.004, 20.006]]},
        width=100,
        height=100,
        min_area=1,
    ) == {
        "工位": [[0.0, 0.0], [20.01, 0.0], [0.0, 20.01]]
    }


@pytest.mark.skipif(roi_geometry is None, reason="roi_geometry is not implemented")
def test_center_inside_counts_even_when_person_overlap_is_small():
    person_box = [-950, 0, 1050, 100]
    roi = [0, 0, 100, 100]

    assert roi_geometry.bbox_roi_overlap_ratio(person_box, roi) == pytest.approx(0.05)
    assert roi_geometry.bbox_belongs_to_roi(person_box, roi, 0.30)


@pytest.mark.skipif(roi_geometry is None, reason="roi_geometry is not implemented")
def test_partial_overlap_uses_person_box_area_for_entry():
    person_box = [70, 0, 170, 100]
    roi = [0, 0, 100, 100]

    assert roi_geometry.bbox_roi_overlap_ratio(person_box, roi) == pytest.approx(0.30)
    assert roi_geometry.bbox_belongs_to_roi(person_box, roi, 0.30)


@pytest.mark.skipif(roi_geometry is None, reason="roi_geometry is not implemented")
def test_hold_threshold_keeps_edge_person_without_allowing_new_entry():
    person_box = [85, 0, 185, 100]
    roi = [0, 0, 100, 100]

    assert roi_geometry.bbox_roi_overlap_ratio(person_box, roi) == pytest.approx(0.15)
    assert not roi_geometry.bbox_belongs_to_roi(person_box, roi, 0.30)
    assert roi_geometry.bbox_belongs_to_roi(person_box, roi, 0.10)


@pytest.mark.skipif(roi_geometry is None, reason="roi_geometry is not implemented")
def test_disjoint_and_invalid_person_boxes_are_outside():
    roi = [0, 0, 100, 100]

    assert not roi_geometry.bbox_belongs_to_roi([101, 0, 201, 100], roi, 0.10)
    assert roi_geometry.bbox_roi_overlap_ratio([10, 10, 10, 30], roi) == 0.0
    assert not roi_geometry.bbox_belongs_to_roi([10, 10, 10, 30], roi, 0.0)


@pytest.mark.skipif(roi_geometry is None, reason="roi_geometry is not implemented")
def test_reversed_coordinates_are_normalized():
    person_box = [170, 100, 70, 0]
    roi = [100, 100, 0, 0]

    assert roi_geometry.bbox_roi_overlap_ratio(person_box, roi) == pytest.approx(0.30)
    assert roi_geometry.bbox_belongs_to_roi(person_box, roi, 0.30)


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


def test_session_manager_uses_looser_overlap_for_active_session(tmp_path):
    manager = session_worker.PairSessionManager(
        {
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
    roi = [0, 0, 100, 100]

    assert manager._tracks_for_roi([edge_track], roi, active=False) == []
    assert manager._tracks_for_roi([edge_track], roi, active=True) == [edge_track]


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


def test_session_worker_default_roi_normalization_ignores_only_bad_items(capsys):
    rois = session_worker._normalize_roi_mapping(
        {
            "合法": [0, 0, 20, 20],
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


def test_new_pair_session_keeps_polygon_bounds_as_roi_box(tmp_path, monkeypatch):
    manager = session_worker.PairSessionManager(
        {
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


def test_deleted_roi_cancels_active_session_without_pending_task(
    tmp_path,
    monkeypatch,
    capsys,
):
    manager = session_worker.PairSessionManager(
        {
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
    manager.step(frame, tracks, {"会删除": [0, 0, 80, 80]})
    manager.roi_states["会删除"].active.keyframes.extend([frame, frame])

    manager.step(frame, tracks, {})

    assert "会删除" not in manager.roi_states
    assert list(tmp_path.iterdir()) == []
    assert "取消" in capsys.readouterr().out


def test_session_manager_rejects_hold_threshold_above_enter_threshold(tmp_path):
    with pytest.raises(ValueError, match="roi_hold_overlap_ratio"):
        session_worker.PairSessionManager(
            {
                "session": {
                    "roi_enter_overlap_ratio": 0.20,
                    "roi_hold_overlap_ratio": 0.30,
                },
            },
            tmp_path,
        )


def test_rule_overlay_colors_roi_members_green_and_outside_tracks_gray(monkeypatch):
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

        def read(self, key, default):
            return self.values.get(key, default)

    class FakeService:
        cfg = {"session": {"roi_enter_overlap_ratio": 0.30}}
        store = FakeStore()

        @staticmethod
        def get_rois_cached():
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

    def record_rectangle(image, point1, point2, color, thickness):
        del point1, point2, thickness
        rectangle_colors.append(color)
        return image

    def record_fill_poly(image, polygons, color):
        del color
        filled_polygons.extend(polygon.copy() for polygon in polygons)
        return image

    def record_polylines(image, polygons, closed, color, thickness):
        del closed, color, thickness
        outlined_polygons.extend(polygon.copy() for polygon in polygons)
        return image

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
        FakeService(),
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
