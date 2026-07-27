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

import session_worker
import main as security_main


def test_roi_geometry_module_exists():
    assert roi_geometry is not None, "shared roi_geometry module is required"


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
                        "x1": 70,
                        "y1": 0,
                        "x2": 170,
                        "y2": 100,
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
            return {"security_staff_1": [0, 0, 100, 100]}

    rectangle_colors = []

    def record_rectangle(image, point1, point2, color, thickness):
        del point1, point2, thickness
        rectangle_colors.append(color)
        return image

    monkeypatch.setattr(security_main.cv2, "rectangle", record_rectangle)

    security_main._overlay_on_frame(
        np.zeros((100, 200, 3), dtype=np.uint8),
        FakeService(),
    )

    assert rectangle_colors.count((0, 255, 0)) == 1
    assert rectangle_colors.count((128, 128, 128)) == 1
