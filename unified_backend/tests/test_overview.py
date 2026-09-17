# 文件说明：包含`test_overview` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import threading
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from AiVision.departments.department_registry import DEPARTMENT_SPECS

import unified_backend.app as app_module


# 功能：验证 `test_get_json_concurrently_starts_upstream_requests_in_parallel` 对应的`test_overview`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`threading.Lock`、`monkeypatch.setattr`、`app_module._get_json_concurrently`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_get_json_concurrently_starts_upstream_requests_in_parallel(monkeypatch):
    lock = threading.Lock()
    active = 0
    max_active = 0

    # 功能：读取或查询 `fake_get_json` 对应的`test_overview` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `base_url`（未显式标注）：`base_url` 对应的业务输入值
    #   - `path`（未显式标注）：目标路径
    #   - `timeout`（未显式标注）：允许操作等待的最长秒数；默认值为 `2.0`
    #   - `request`（未显式标注）：当前 HTTP 请求及上下文；默认值为 `None`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`max`、`time.sleep`。
    # 副作用/注意事项：会修改全局或闭包状态。
    def fake_get_json(base_url, path, *, timeout=2.0, request=None):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return True, {"path": path}, 1.0, None

    monkeypatch.setattr(app_module, "_get_json", fake_get_json)

    results = app_module._get_json_concurrently({
        "one": ("http://one", "/health", None),
        "two": ("http://two", "/status", None),
        "three": ("http://three", "/cameras", None),
    })

    assert max_active >= 2
    assert results["one"][1] == {"path": "/health"}
    assert results["two"][1] == {"path": "/status"}
    assert results["three"][1] == {"path": "/cameras"}


def client_for(monkeypatch, tmp_path, user):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "get_current_user_from_request", lambda request: user)
    return TestClient(app_module.create_app())


def mock_overview_sources(monkeypatch):
    departments = list(DEPARTMENT_SPECS)
    calls = []

    def read(requests):
        results = {}
        for key, (_base, path, _request) in requests.items():
            calls.append(path)
            if key == "ai_status":
                payload = {"running_cameras": [f"camera_{i}" for i in range(7)],
                           "running_consumers": ["recognize_face"], "running_models": ["insightface"]}
            elif key == "features":
                payload = {"features": [{"name": "recognize_face", "required_models": ["insightface"]},
                                        {"name": "blocks", "required_models": ["yolo_human"]}]}
            elif key.split(":")[0].isdigit():
                index, resource = key.split(":")
                payload = ({"running": True, "camera_states": {index: "READY"}} if resource == "status" else
                           [{"camera_id": int(index), "member_enabled": True}])
            else:
                department, resource = key.split(":", 1)
                index = departments.index(department)
                other = departments[(index + 1) % len(departments)]
                camera = {"id": str(index), "camera_id": index, "name": f"测试{index}",
                          "shm_name": f"camera_{index}", "department": department, "enabled": True,
                          "sort_order": index, "functions": {"recognize_face": True}}
                if resource == "ai_cameras":
                    payload = [camera, {**camera, "camera_id": 100 + index, "department": other}]
                elif resource == "logistics":
                    payload = {"items": [{"camera_id": index, "department": department, "online": True, "memberships": [
                        {"feature_name": "detect_logistics_single_person", "channel_id": index,
                         "channel_name": "测试通道", "enabled": True, "online": True},
                    ]}]}
                elif resource == "guard_sites":
                    site = {"id": index, "name": "本部", "department": department, "enabled": True,
                            "cameras": [{"id": index, "name": "保安", "enabled": True}]}
                    payload = [site, {**site, "id": 100 + index, "department": other}]
                elif resource == "vlm_state":
                    payload = {"vlm": {"ok": True}, "cameras": [
                        {"camera_id": "scanner", "name": "安检", "running": True},
                        {"camera_id": "other", "name": "其他", "department": other, "running": True},
                    ]}
                else:
                    pytest.fail(f"意外的上游资源：{resource}")
            results[key] = (True, payload, 1.0, None)
        return results

    monkeypatch.setattr(app_module, "_get_json_concurrently", read)
    return calls


@pytest.mark.parametrize("failed_resource", ["status", "cameras"])
def test_guard_running_requires_native_site_evidence(monkeypatch, tmp_path, failed_resource):
    mock_overview_sources(monkeypatch)
    read = app_module._get_json_concurrently

    def fail_guard_resource(requests):
        results = read(requests)
        for key, (_base, path, _request) in requests.items():
            if key == "ai_status":
                results[key][1]["running_consumers"].append("guard_behavior")
            if key.endswith(":ai_cameras"):
                for camera in results[key][1]:
                    camera["functions"]["guard_behavior"] = True
            if path.startswith("/api/guard-behavior/sites/") and path.endswith("/" + failed_resource):
                results[key] = (False, None, None, "unavailable")
        return results

    monkeypatch.setattr(app_module, "_get_json_concurrently", fail_guard_resource)
    department = next(iter(DEPARTMENT_SPECS))
    client = client_for(monkeypatch, tmp_path, {"role": "viewer", "departments": [department]})
    response = client.get("/api/overview")
    assert response.status_code == 200
    result = response.json()
    assert result["summary"]["camera_total"] == 2
    assert not result["inventory_complete"]
    guard = next(item for item in result["capabilities"] if item["id"] == "guard-behavior")
    assert not guard["running"] and guard["online_camera_count"] == 0


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
@pytest.mark.parametrize("role", ["admin", "viewer"])
def test_overview_uses_account_scope_and_keeps_nine_capabilities(monkeypatch, tmp_path, department, role):
    calls = mock_overview_sources(monkeypatch)
    allowed = list(DEPARTMENT_SPECS) if role == "admin" else [department]
    client = client_for(monkeypatch, tmp_path, {"role": role, "departments": [department]})
    response = client.get("/api/overview")
    assert response.status_code == 200
    result = response.json()
    assert result["departments"] == allowed
    assert "department" not in result
    assert len(result["capabilities"]) == result["summary"]["capability_total"] == 9
    assert len(result["cameras"]) == result["summary"]["camera_total"] == 2 * len(allowed)
    assert {camera["department"] for camera in result["cameras"]} == set(allowed)
    assert len({camera["key"] for camera in result["cameras"]}) == len(result["cameras"])
    for camera in result["cameras"]:
        if camera["source"] == "aivision":
            assert camera["capabilities"] == ["face-recognition", "logistics-single-person", "guard-behavior"]
            assert len(camera["logistics_memberships"]) == 1
    for summary in result["department_summaries"].values():
        assert summary["capability_total"] == 9
        assert summary["camera_total"] == 2
    assert result["inventory_complete"] is True
    capabilities = {item["id"]: item for item in result["capabilities"]}
    assert capabilities["face-recognition"]["model_ready"] is True
    assert capabilities["intrusion-detection"]["model_ready"] is False
    assert calls.count("/api/runtime/status") == calls.count("/api/features") == 1
    assert not any("/sites/10" in path for path in calls)
    for scoped_department in DEPARTMENT_SPECS:
        assert (f"/api/departments/{scoped_department}/health" in calls) == (scoped_department in allowed)


@pytest.mark.parametrize("role", ["admin", "viewer"])
def test_browser_department_parameter_cannot_change_overview_scope(monkeypatch, tmp_path, role):
    mock_overview_sources(monkeypatch)
    assigned = ["electronics_electrician", "research_institute"]
    client = client_for(monkeypatch, tmp_path, {"role": role, "departments": assigned})
    baseline = client.get("/api/overview").json()
    for previous_department in [*DEPARTMENT_SPECS, "all", "unknown"]:
        result = client.get("/api/overview", params={"department": previous_department}).json()
        for key in ("departments", "department_summaries", "summary", "cameras", "capabilities"):
            assert result[key] == baseline[key]
    assert baseline["departments"] == (list(DEPARTMENT_SPECS) if role == "admin" else assigned)


@pytest.mark.parametrize("assigned", [[], ["all", "unknown"], ["electronics_electrician", "all", "electronics_electrician"]])
def test_viewer_overview_only_reads_explicit_formal_departments(monkeypatch, tmp_path, assigned):
    calls = mock_overview_sources(monkeypatch)
    allowed = ["electronics_electrician"] if "electronics_electrician" in assigned else []
    client = client_for(monkeypatch, tmp_path, {"role": "viewer", "departments": assigned})
    result = client.get("/api/overview").json()
    assert result["departments"] == allowed
    assert {camera["department"] for camera in result["cameras"]} == set(allowed)
    assert len(result["capabilities"]) == 9
    if not allowed:
        assert calls == []


def test_empty_platform_still_has_nine_capabilities_per_department(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "_get_json_concurrently", lambda requests: {
        key: (True, [] if key.endswith((":ai_cameras", ":guard_sites")) else {}, 1.0, None) for key in requests
    })
    client = client_for(monkeypatch, tmp_path, {"role": "admin"})
    data = client.get("/api/overview").json()
    assert data["departments"] == list(DEPARTMENT_SPECS)
    assert len(data["capabilities"]) == 9
    assert all(c["camera_count"] == 0 and c["running"] is False for c in data["capabilities"])
    assert all(summary["capability_total"] == 9 for summary in data["department_summaries"].values())
    assert data["cameras"] == []


def test_overview_reports_scoped_upstream_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "_get_json_concurrently", lambda requests: {
        key: (False, None, None, "测试上游不可用") for key in requests
    })
    client = client_for(monkeypatch, tmp_path, {"role": "admin"})
    response = client.get("/api/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["inventory_complete"] is False
    assert data["inventory_errors"]["electronics_electrician:ai_cameras"] == "测试上游不可用"
    assert len(data["capabilities"]) == 9


@pytest.mark.parametrize("path", [
    "/api/guard-room/sites", "/api/guard-room/sites/1/control/start",
    "/api/platform/status", "/api/sites", "/api/sites/1/config",
    "/api/integrations/guard-room/api/sites", "/api/integrations/security-vlm/api/departments",
    "/security-vlm/api/departments/electronics_electrician/cameras", "/security-vlm/health",
    "/aivision/api/cameras", "/aivision/api/face-recognition/persons",
])
def test_removed_external_routes_do_not_proxy(monkeypatch, tmp_path, path):
    async def forbidden_proxy(*args):
        pytest.fail("旧外部路径不应转发到内部服务")
    monkeypatch.setattr(app_module, "_proxy", forbidden_proxy)
    client = client_for(monkeypatch, tmp_path, {"role": "admin"})
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("method, path, internal", [
    ("GET", "/api/guard-behavior/sites", "/api/guard-behavior/sites"),
    ("POST", "/api/guard-behavior/sites", "/api/guard-behavior/sites"),
    ("PATCH", "/api/guard-behavior/sites/1/policy", "/api/guard-behavior/sites/1/policy"),
    ("GET", "/api/guard-behavior/sites/1/status", "/api/guard-behavior/sites/1/status"),
    ("DELETE", "/api/guard-behavior/sites/1/cameras/2", "/api/guard-behavior/sites/1/cameras/2"),
    ("GET", "/api/face-recognition/persons", "/api/face-recognition/persons"),
])
def test_formal_proxies_forward_method_path_and_query(monkeypatch, tmp_path, method, path, internal):
    from fastapi.responses import JSONResponse
    async def proxy(request, base, upstream):
        assert upstream == internal
        assert request.method == method
        assert request.query_params["department"] == "electronics_electrician"
        return JSONResponse({"ok": True})
    monkeypatch.setattr(app_module, "_proxy", proxy)
    client = client_for(monkeypatch, tmp_path, {"role": "admin"})
    assert client.request(method, path, params={"department": "electronics_electrician"}).status_code == 200


@pytest.mark.parametrize("resource", ["health", "history", "cameras", "cameras/one/rois", "video/one/capture"])
def test_security_proxy_keeps_department_permissions(monkeypatch, tmp_path, resource):
    from fastapi.responses import JSONResponse
    user = {"role": "viewer", "departments": ["electronics_electrician"]}
    async def proxy(request, base, path):
        assert path == f"/api/departments/electronics_electrician/{resource}"
        return JSONResponse({"ok": True})
    monkeypatch.setattr(app_module, "_proxy", proxy)
    client = client_for(monkeypatch, tmp_path, user)
    path = f"/api/security-vlm/departments/electronics_electrician/{resource}"
    assert client.get(path).status_code == 200
    assert client.post(path).status_code == 403
    assert client.get(path.replace("electronics_electrician", "research_institute")).status_code == 403
    user["role"] = "admin"
    assert client.post(path).status_code == 200
