import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unified_backend.app import (
    _can_access_security_vlm,
    _can_mutate_security_vlm,
    _count_guard_site_cameras,
    _guard_alarm_paths,
    _guard_site_runtime_summary,
    _normalize_guard_alarm,
)


def test_security_vlm_viewer_can_read_but_cannot_mutate():
    viewer = {"role": "viewer"}
    admin = {"role": "admin"}

    assert _can_mutate_security_vlm(viewer, "GET") is True
    assert _can_mutate_security_vlm(viewer, "POST") is False
    assert _can_mutate_security_vlm(viewer, "DELETE") is False
    assert _can_mutate_security_vlm(admin, "POST") is True


def test_security_vlm_credentials_are_admin_only():
    viewer = {"role": "viewer"}
    admin = {"role": "admin"}
    path = "/security-vlm/api/cameras/camera-a/credentials"

    assert _can_access_security_vlm(viewer, "GET", path) is False
    assert _can_access_security_vlm(viewer, "GET", f"{path}/") is False
    assert _can_access_security_vlm(admin, "GET", path) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/cameras",
    ) is True


def test_count_guard_site_cameras_counts_nested_site_cameras():
    sites = {
        "items": [
            {
                "id": 1,
                "camera_count": 3,
                "enabled_camera_count": 2,
                "cameras": [{"id": 1}, {"id": 2}, {"id": 3}],
            },
            {
                "id": 2,
                "camera_count": 1,
                "enabled_camera_count": 1,
                "cameras": [{"id": 4}],
            },
        ]
    }

    assert _count_guard_site_cameras(sites) == (4, 3)


def test_normalize_guard_alarm_keeps_site_metadata_and_site_asset_urls():
    alarm = {
        "id": "abc",
        "site_id": 7,
        "site_name": "一厂区南门保安室",
        "event_type": "absent",
        "reason": "离岗",
        "confidence": 0.9,
        "video_status": "ready",
    }

    normalized = _normalize_guard_alarm(alarm)

    assert normalized["id"] == "guard:7:abc"
    assert normalized["site_id"] == 7
    assert normalized["site_name"] == "一厂区南门保安室"
    assert normalized["camera_no"] == "guard_room_site_7"
    assert normalized["camera_name"] == "一厂区南门保安室"
    assert normalized["image_url"] == "/api/sites/7/alarms/abc/image"
    assert normalized["video_url"] == "/api/sites/7/alarms/abc/video"


def test_guard_site_runtime_summary_counts_running_site_cameras():
    sites = {
        "items": [
            {"id": 1, "enabled_camera_count": 2},
            {"id": 2, "enabled_camera_count": 3},
        ]
    }
    statuses = {
        1: {"running": True, "fps": 8.5, "frame_count": 10, "updated_at": "2026-06-12T10:00:00", "pose_enabled": True},
        2: {"running": False, "fps": 0, "frame_count": 0, "updated_at": "2026-06-12T09:00:00", "pose_enabled": False},
    }

    summary = _guard_site_runtime_summary(sites, statuses)

    assert summary["running"] is True
    assert summary["running_sites"] == [1]
    assert summary["online_camera_count"] == 2
    assert summary["offline_camera_count"] == 3
    assert summary["fps"] == 8.5
    assert summary["frame_count"] == 10
    assert summary["updated_at"] == "2026-06-12T10:00:00"
    assert summary["pose_enabled"] is True


def test_guard_site_runtime_summary_exposes_site_status_errors():
    sites = {"items": [{"id": 1, "enabled_camera_count": 2}]}

    summary = _guard_site_runtime_summary(
        sites,
        {},
        status_errors={1: "401 Unauthorized"},
    )

    assert summary["running"] is False
    assert summary["status_errors"] == {1: "401 Unauthorized"}
    assert summary["status_error"] == "1 个保安室运行状态获取失败: 1: 401 Unauthorized"


def test_guard_alarm_paths_prefers_site_scoped_alarm_endpoints():
    sites = {"items": [{"id": 1}, {"id": 2}]}

    assert _guard_alarm_paths(sites, 100) == [
        "/api/sites/1/alarms?limit=100",
        "/api/sites/2/alarms?limit=100",
    ]


def test_guard_alarm_paths_can_scope_site_endpoints_by_department():
    sites = {"items": [{"id": 1}, {"id": 2}]}

    assert _guard_alarm_paths(sites, 100, department="electronics_electrician") == [
        "/api/sites/1/alarms?limit=100&department=electronics_electrician",
        "/api/sites/2/alarms?limit=100&department=electronics_electrician",
    ]
