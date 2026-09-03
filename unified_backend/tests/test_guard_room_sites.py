# 文件说明：包含`test_guard_room_sites` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from unified_backend.app import (
    _allowed_event_types_for_user,
    _can_access_security_vlm,
    _can_mutate_security_vlm,
    _count_guard_site_cameras,
    _guard_alarm_paths,
    _guard_departments_for_user,
    _guard_site_runtime_summary,
    _is_guard_room_api_path,
    _normalize_guard_alarm,
    _normalize_security_vlm_alarm,
    _security_vlm_departments_for_user,
    _visual_service_url,
    create_app,
)


def test_guard_room_site_paths_are_selected_before_generic_aivision_proxy():
    assert _is_guard_room_api_path("sites") is True
    assert _is_guard_room_api_path("sites/7/frame.jpg") is True
    assert _is_guard_room_api_path("cameras") is False
    assert _is_guard_room_api_path("features/detect_human") is False
    catch_all_routes = [
        route for route in create_app().routes
        if getattr(route, "path", None) == "/api/{path:path}"
    ]
    assert len(catch_all_routes) == 1


# 功能：验证 `test_managed_visual_services_are_routed_to_aivision` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_visual_service_url`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_managed_visual_services_are_routed_to_aivision():
    aivision_url = "http://127.0.0.1:7862/"

    assert _visual_service_url(aivision_url, "guard-room") == (
        "http://127.0.0.1:7862/api/integrations/guard-room"
    )
    assert _visual_service_url(aivision_url, "security-vlm") == (
        "http://127.0.0.1:7862/api/integrations/security-vlm"
    )


# 功能：验证 `test_security_vlm_viewer_can_read_but_cannot_mutate` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_can_mutate_security_vlm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_security_vlm_viewer_can_read_but_cannot_mutate():
    viewer = {"role": "viewer"}
    admin = {"role": "admin"}

    assert _can_mutate_security_vlm(viewer, "GET") is True
    assert _can_mutate_security_vlm(viewer, "POST") is False
    assert _can_mutate_security_vlm(viewer, "DELETE") is False
    assert _can_mutate_security_vlm(admin, "POST") is True


# 功能：验证 `test_security_vlm_credentials_are_admin_only` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_can_access_security_vlm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_security_vlm_credentials_are_admin_only():
    viewer = {"role": "viewer", "department": "electronics_electrician"}
    admin = {"role": "admin"}
    path = (
        "/security-vlm/api/departments/electronics_electrician/"
        "cameras/camera-a/credentials"
    )

    assert _can_access_security_vlm(viewer, "GET", path) is False
    assert _can_access_security_vlm(viewer, "GET", f"{path}/") is False
    assert _can_access_security_vlm(admin, "GET", path) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/departments/electronics_electrician/cameras",
    ) is True


# 功能：验证 `test_security_vlm_viewer_can_only_read_own_department` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_can_access_security_vlm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_security_vlm_viewer_can_only_read_own_department():
    viewer = {"role": "viewer", "department": "electronics_electrician"}

    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/departments/electronics_electrician/history",
    ) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/departments/electrical_components/history",
    ) is False
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/history",
    ) is False
    assert _can_access_security_vlm(
        viewer,
        "POST",
        "/security-vlm/api/departments/electronics_electrician/cameras",
    ) is False


# 功能：验证 `test_multi_department_viewer_receives_union_of_scoped_permissions` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_can_access_security_vlm`、`_guard_departments_for_user`、`_allowed_event_types_for_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_multi_department_viewer_receives_union_of_scoped_permissions():
    viewer = {
        "role": "viewer",
        "department": "general_electric",
        "departments": ["general_electric", "electronics_electrician"],
    }

    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/departments/general_electric/history",
    ) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/departments/electronics_electrician/history",
    ) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/departments/electrical_components/history",
    ) is False
    assert _guard_departments_for_user(viewer) == [
        "general_electric",
        "electronics_electrician",
    ]
    allowed_event_types = _allowed_event_types_for_user(viewer)
    assert allowed_event_types is not None
    assert "detect_human" in allowed_event_types
    assert "detect_logistics_single_person" in allowed_event_types
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/history",
    ) is True


# 功能：验证 `test_security_vlm_alarm_sources_are_department_scoped` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_security_vlm_departments_for_user`、`_normalize_security_vlm_alarm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_security_vlm_alarm_sources_are_department_scoped():
    viewer = {"role": "viewer", "department": "electrical_components"}
    admin = {"role": "admin", "department": "all"}

    assert _security_vlm_departments_for_user(viewer) == [
        "electrical_components"
    ]
    assert _security_vlm_departments_for_user(admin) == [
        "general_electric",
        "electronics_electrician",
        "electrical_components",
        "precious_metal_recycling",
    ]
    alarm = _normalize_security_vlm_alarm(
        {
            "session_id": "same-session",
            "status": "non_compliant",
            "camera_id": "same-camera",
        },
        "electrical_components",
    )
    assert alarm is not None
    assert alarm["id"] == (
        "security_vlm:electrical_components:same-session"
    )
    assert alarm["department"] == "electrical_components"


# 功能：验证 `test_count_guard_site_cameras_counts_nested_site_cameras` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_count_guard_site_cameras`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：验证 `test_normalize_guard_alarm_keeps_site_metadata_and_site_asset_urls` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_normalize_guard_alarm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
    assert normalized["subject_type"] == "guard_room_site"
    assert normalized["subject_id"] == "7"
    assert normalized["subject_name"] == "一厂区南门保安室"
    assert normalized["camera_no"] is None
    assert normalized["camera_name"] is None
    assert normalized["image_url"] == "/api/sites/7/alarms/abc/image"
    assert normalized["video_url"] == "/api/sites/7/alarms/abc/video"


# 功能：验证 `test_guard_site_runtime_summary_counts_running_site_cameras` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_guard_site_runtime_summary`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：验证 `test_guard_site_runtime_summary_exposes_site_status_errors` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_guard_site_runtime_summary`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：验证 `test_guard_alarm_paths_prefers_site_scoped_alarm_endpoints` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_guard_alarm_paths`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_guard_alarm_paths_prefers_site_scoped_alarm_endpoints():
    sites = {"items": [{"id": 1}, {"id": 2}]}

    assert _guard_alarm_paths(sites, 100) == [
        "/api/sites/1/alarms?limit=100",
        "/api/sites/2/alarms?limit=100",
    ]


# 功能：验证 `test_guard_alarm_paths_can_scope_site_endpoints_by_department` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_guard_alarm_paths`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_guard_alarm_paths_can_scope_site_endpoints_by_department():
    sites = {"items": [{"id": 1}, {"id": 2}]}

    assert _guard_alarm_paths(sites, 100, department="electronics_electrician") == [
        "/api/sites/1/alarms?limit=100&department=electronics_electrician",
        "/api/sites/2/alarms?limit=100&department=electronics_electrician",
    ]
