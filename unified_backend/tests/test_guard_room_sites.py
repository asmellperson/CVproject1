import pytest
from AiVision.departments.department_registry import DEPARTMENT_SPECS
# 文件说明：包含`test_guard_room_sites` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from unified_backend.app import (
    _allowed_event_types_for_user,
    _can_access_security_vlm,
    _can_mutate_security_vlm,
    _guard_alarm_paths,
    _guard_departments_for_user,
    _normalize_guard_alarm,
    _normalize_security_vlm_alarm,
    _security_vlm_departments_for_user,
    _visual_service_url,
    create_app,
)


def test_formal_resource_proxies_are_registered_before_aivision_proxy():
    paths = [route.path for route in create_app().routes]
    assert paths.index("/api/guard-room/{path:path}") < paths.index("/api/{path:path}")
    assert paths.index("/api/security-vlm/departments/{department}/{path:path}") < paths.index("/api/{path:path}")


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
    viewer = {"role": "viewer", "departments": ["electronics_electrician"]}
    admin = {"role": "admin"}
    path = (
        "/api/security-vlm/departments/electronics_electrician/"
        "cameras/camera-a/credentials"
    )

    assert _can_access_security_vlm(viewer, "GET", path) is False
    assert _can_access_security_vlm(viewer, "GET", f"{path}/") is False
    assert _can_access_security_vlm(admin, "GET", path) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/api/security-vlm/departments/electronics_electrician/cameras",
    ) is True


# 功能：验证 `test_security_vlm_viewer_can_only_read_own_department` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_can_access_security_vlm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_security_vlm_viewer_can_only_read_own_department():
    viewer = {"role": "viewer", "departments": ["electronics_electrician"]}

    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/api/security-vlm/departments/electronics_electrician/history",
    ) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/api/security-vlm/departments/electrical_components/history",
    ) is False
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/api/security-vlm/history",
    ) is False
    assert _can_access_security_vlm(
        viewer,
        "POST",
        "/api/security-vlm/departments/electronics_electrician/cameras",
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
        "departments": ["general_electric", "electronics_electrician"],
    }

    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/api/security-vlm/departments/general_electric/history",
    ) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/api/security-vlm/departments/electronics_electrician/history",
    ) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/api/security-vlm/departments/electrical_components/history",
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
        "/api/security-vlm/history",
    ) is False


# 功能：验证 `test_security_vlm_alarm_sources_are_department_scoped` 对应的`test_guard_room_sites` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_security_vlm_departments_for_user`、`_normalize_security_vlm_alarm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_security_vlm_alarm_sources_are_department_scoped():
    viewer = {"role": "viewer", "departments": ["electrical_components"]}
    admin = {"role": "admin", "departments": ["all"]}

    assert _security_vlm_departments_for_user(viewer) == [
        "electrical_components"
    ]
    assert _security_vlm_departments_for_user(admin) == list(DEPARTMENT_SPECS)
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
        "department": "haoda_company",
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
    assert normalized["image_url"] == "/api/guard-room/sites/7/alarms/abc/image?department=haoda_company"
    assert normalized["video_url"] == "/api/guard-room/sites/7/alarms/abc/video?department=haoda_company"

    assert normalized["department"] == "haoda_company"


def test_guard_alarm_paths_requires_explicit_department():
    sites = {"items": [{"id": 1}, {"id": 2}]}

    with pytest.raises(TypeError):
        _guard_alarm_paths(sites, 100)
    for invalid in (None, "", "ge", "通用电气"):
        with pytest.raises(ValueError):
            _guard_alarm_paths(sites, 100, department=invalid)


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


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_security_and_guard_accept_all_registered_departments(department):
    viewer = {"role": "viewer", "departments": [department]}
    assert _security_vlm_departments_for_user(viewer) == [department]
    assert _guard_departments_for_user(viewer) == [department]
    for requested in DEPARTMENT_SPECS:
        assert _can_access_security_vlm(viewer, "GET", f"/api/security-vlm/departments/{requested}/cameras") is (requested == department)


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_overview_alarms_query_department_before_limiting(monkeypatch, department):
    import importlib
    from types import SimpleNamespace
    from fastapi import HTTPException
    backend = importlib.import_module("unified_backend.app")
    calls = []
    foreign = next(value for value in DEPARTMENT_SPECS if value != department)
    def upstream(base, path, request):
        calls.append((base, path))
        if base == "ai":
            return {"items": [
                {"id": 1, "feature_name": "recognize_face", "event_type": "recognize_face", "violation_type": 7,
                 "department": department, "created_at": "2026-09-01"},
                {"id": 2, "feature_name": "recognize_face", "event_type": "recognize_face", "violation_type": 7,
                 "department": foreign, "created_at": "2026-09-02"},
            ]}
        return {}
    monkeypatch.setattr(backend, "_get_upstream_json", upstream)
    args = dict(request=None, user={"role": "viewer", "departments": [department]},
                guard_room_url="guard", aivision_url="ai", security_vlm_url="security",
                disposition_store=SimpleNamespace(get_many=lambda ids: {}), limit=1)
    rows = backend._collect_alarms(**args, department=department)
    assert len(rows) == 1 and rows[0]["department"] == department
    assert ("ai", f"/api/alarms?limit=100&department={department}") in calls
    assert ("guard", f"/api/sites?department={department}") in calls
    assert ("security", f"/api/departments/{department}/history?limit=100") in calls
    calls.clear()
    with pytest.raises(HTTPException) as caught:
        backend._collect_alarms(**args, department=foreign)
    assert caught.value.status_code == 403
    assert calls == []


def test_removed_security_probe_does_not_bypass_business_authorization(tmp_path, monkeypatch):
    import asyncio
    import importlib
    import httpx
    from fastapi.responses import JSONResponse
    from auth.auth import AuthError

    backend = importlib.import_module("unified_backend.app")
    forwarded = []

    async def proxy(request, base_url, upstream_path):
        forwarded.append(upstream_path)
        return JSONResponse({"status": "ok", "ready": True})

    def unauthenticated(_request):
        raise AuthError("authentication required")

    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(backend, "_proxy", proxy)
    monkeypatch.setattr(backend, "get_current_user_from_request", unauthenticated)
    app = backend.create_app()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/security-vlm/health")
            assert response.status_code == 404
            assert (await client.get("/api/security-vlm/departments/fulida_company/health")).status_code == 401
        assert forwarded == []

    asyncio.run(scenario())
