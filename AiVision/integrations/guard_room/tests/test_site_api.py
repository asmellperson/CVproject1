import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from AiVision.departments.department_registry import DEPARTMENT_SPECS
from AiVision.integrations.guard_room.src import server
from AiVision.integrations.guard_room.src.db import configure_for_tests
from AiVision.integrations.guard_room.src.server import CameraCreateRequest, CameraUpdateRequest, SiteCreateRequest, create_app
from AiVision.integrations.guard_room.src.service import GuardRoomService


def _app(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_api.db'}")
    return create_app(str(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"))


def _route_endpoint(app, path: str, method: str):
    method = method.upper()
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class FakeRuntimeManager:
    def __init__(self):
        self.started = []
        self.stopped = []
        self.restarted = []
        self.stop_all_calls = 0

    def start(self, site_id: int):
        self.started.append(site_id)
        return {"site_id": site_id, "site_name": "测试保安室", "running": True}

    def stop(self, site_id: int):
        self.stopped.append(site_id)
        return {"site_id": site_id, "site_name": "测试保安室", "running": False}

    def restart(self, site_id: int):
        self.restarted.append(site_id)
        return {"site_id": site_id, "site_name": "测试保安室", "running": True, "restarted": True}

    def get_status(self, site_id: int):
        return {"site_id": site_id, "site_name": "测试保安室", "running": False}

    def get_latest_frame(self, site_id: int):
        return b"jpeg-bytes"

    def get_camera_frame(self, site_id: int, camera_id: str):
        return f"{site_id}:{camera_id}:jpeg".encode()

    def get_alarms(self, site_id: int, limit: int = 50):
        return [{"id": "alarm-1", "site_id": site_id, "site_name": "测试保安室"}]

    def get_statistics(self, site_id: int):
        return {"site_id": site_id, "site_name": "测试保安室", "summary": {"total": 0}}

    def stop_all(self):
        self.stop_all_calls += 1


def test_site_api_routes_create_site_and_camera(tmp_path):
    app = _app(tmp_path)

    create_site = _route_endpoint(app, "/api/sites", "POST")
    list_sites = _route_endpoint(app, "/api/sites", "GET")
    get_site = _route_endpoint(app, "/api/sites/{site_id}", "GET")
    create_camera = _route_endpoint(app, "/api/sites/{site_id}/cameras", "POST")

    site = create_site(SiteCreateRequest(name="一厂区南门保安室", department="general_electric"), _user={"role": "admin"})
    assert site["name"] == "一厂区南门保安室"
    assert site["camera_count"] == 0

    listed = list_sites(department="general_electric", _user={"role": "admin"})
    assert [item["name"] for item in listed["items"]] == ["一厂区南门保安室"]

    camera = create_camera(
        site["id"],
        CameraCreateRequest(name="门口左侧", rtsp_url="rtsp://camera-1"),
        department="general_electric", _user={"role": "admin"},
    )
    assert camera["sort_order"] == 1

    detail = get_site(site["id"], department="general_electric", _user={"role": "admin"})
    assert detail["cameras"][0]["name"] == "门口左侧"


def test_site_api_routes_scope_sites_by_department(tmp_path):
    app = _app(tmp_path)

    create_site = _route_endpoint(app, "/api/sites", "POST")
    list_sites = _route_endpoint(app, "/api/sites", "GET")

    sites = {
        department: create_site(SiteCreateRequest(name="保安室", department=department), _user={"role": "admin"})
        for department in DEPARTMENT_SPECS
    }
    get_site = _route_endpoint(app, "/api/sites/{site_id}", "GET")
    for department, site in sites.items():
        viewer = {"role": "viewer", "departments": [department]}
        assert [row["id"] for row in list_sites(department=department, _user=viewer)["items"]] == [site["id"]]
        assert get_site(site["id"], department=department, _user=viewer)["department"] == department
        foreign = next(row for other, row in sites.items() if other != department)
        with pytest.raises(HTTPException) as caught:
            get_site(foreign["id"], department=department, _user=viewer)
        assert caught.value.status_code == 404
        with pytest.raises(HTTPException) as caught:
            list_sites(department=foreign["department"], _user=viewer)
        assert caught.value.status_code == 403
    for department, site in sites.items():
        assert [row["id"] for row in list_sites(department=department, _user={"role": "admin"})["items"]] == [site["id"]]
    for departments in ([], ["unknown"], ["all"], ["ge"], ["通用电气"]):
        with pytest.raises(HTTPException) as caught:
            list_sites(department="general_electric", _user={"role": "viewer", "departments": departments})
        assert caught.value.status_code == 403


def test_site_api_routes_update_and_delete_camera(tmp_path):
    app = _app(tmp_path)

    create_site = _route_endpoint(app, "/api/sites", "POST")
    create_camera = _route_endpoint(app, "/api/sites/{site_id}/cameras", "POST")
    update_camera = _route_endpoint(app, "/api/cameras/{camera_id}", "PUT")
    delete_camera = _route_endpoint(app, "/api/cameras/{camera_id}", "DELETE")
    get_site = _route_endpoint(app, "/api/sites/{site_id}", "GET")

    site = create_site(SiteCreateRequest(name="二厂区值班室", department="general_electric"), _user={"role": "admin"})
    camera = create_camera(
        site["id"],
        CameraCreateRequest(name="旧名称", rtsp_url="rtsp://old"),
        department="general_electric", _user={"role": "admin"},
    )

    updated = update_camera(
        camera["id"],
        CameraUpdateRequest(name="门口右侧", rtsp_url="rtsp://new", enabled=False),
        department="general_electric", _user={"role": "admin"},
    )
    assert updated["name"] == "门口右侧"
    assert updated["rtsp_url"] == "rtsp://new"
    assert updated["enabled"] is False

    assert delete_camera(camera["id"], department="general_electric", _user={"role": "admin"}) == {"success": True}
    assert get_site(site["id"], department="general_electric", _user={"role": "admin"})["cameras"] == []


def test_site_api_routes_expose_runtime_controls_and_read_models(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_api_runtime.db'}")
    service = GuardRoomService()
    service.ensure_schema()
    site_id = service.create_site("测试保安室", department="general_electric")["id"]
    manager = FakeRuntimeManager()
    app = create_app(
        str(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"),
        runtime_manager=manager,
        guard_room_service=service,
    )

    start = _route_endpoint(app, "/api/sites/{site_id}/control/start", "POST")
    stop = _route_endpoint(app, "/api/sites/{site_id}/control/stop", "POST")
    restart = _route_endpoint(app, "/api/sites/{site_id}/control/restart", "POST")
    status = _route_endpoint(app, "/api/sites/{site_id}/status", "GET")
    frame = _route_endpoint(app, "/api/sites/{site_id}/frame.jpg", "GET")
    camera_frame = _route_endpoint(app, "/api/sites/{site_id}/cameras/{camera_id}/frame.jpg", "GET")
    alarms = _route_endpoint(app, "/api/sites/{site_id}/alarms", "GET")
    statistics = _route_endpoint(app, "/api/sites/{site_id}/statistics", "GET")

    assert start(site_id, department="general_electric", _user={"role": "admin"})["running"] is True
    assert stop(site_id, department="general_electric", _user={"role": "admin"})["running"] is False
    assert restart(site_id, department="general_electric", _user={"role": "admin"})["restarted"] is True
    assert manager.restarted == [site_id]
    assert status(site_id, department="general_electric", _user={"role": "admin"})["site_name"] == "测试保安室"
    assert frame(site_id, department="general_electric", _user={"role": "admin"}).body == b"jpeg-bytes"
    assert camera_frame(site_id, "cam2", department="general_electric", _user={"role": "admin"}).body == f"{site_id}:cam2:jpeg".encode()
    assert alarms(site_id, department="general_electric", _user={"role": "admin"})["items"][0]["site_id"] == site_id
    assert statistics(site_id, department="general_electric", _user={"role": "admin"})["summary"]["total"] == 0


def test_app_lifespan_starts_enabled_sites_and_preserves_disabled_sites(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_api_lifespan.db'}")
    service = GuardRoomService()
    service.ensure_schema()
    enabled = service.create_site("默认开启", department="general_electric")
    disabled = service.create_site("手动关闭", enabled=False, department="general_electric")
    service.create_camera(enabled["id"], name="入口", rtsp_url="rtsp://enabled")
    service.create_camera(disabled["id"], name="入口", rtsp_url="rtsp://disabled")
    manager = FakeRuntimeManager()
    app = create_app(
        str(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"),
        guard_room_service=service,
        runtime_manager=manager,
    )

    async def run_lifespan():
        async with app.router.lifespan_context(app):
            assert manager.started == [enabled["id"]]

    asyncio.run(run_lifespan())

    assert manager.stop_all_calls == 1


def test_first_enabled_camera_starts_an_enabled_site_after_app_startup(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_api_first_camera.db'}")
    service = GuardRoomService()
    service.ensure_schema()
    site = service.create_site("待添加摄像头", department="general_electric")
    manager = FakeRuntimeManager()
    app = create_app(
        str(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"),
        guard_room_service=service,
        runtime_manager=manager,
    )
    create_camera = _route_endpoint(app, "/api/sites/{site_id}/cameras", "POST")

    async def run_lifespan():
        async with app.router.lifespan_context(app):
            assert manager.started == []
            create_camera(
                site["id"],
                CameraCreateRequest(name="入口", rtsp_url="rtsp://camera"),
                department="general_electric", _user={"role": "admin"},
            )
            assert manager.restarted == [site["id"]]

    asyncio.run(run_lifespan())


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
@pytest.mark.parametrize("role", ["admin", "viewer"])
def test_business_reads_require_explicit_authorized_department(tmp_path, monkeypatch, department, role):
    app = _app(tmp_path)
    create_site = _route_endpoint(app, "/api/sites", "POST")
    site = create_site(SiteCreateRequest(name="当前站点", department=department), _user={"role": "admin"})
    other = next(value for value in DEPARTMENT_SPECS if value != department)
    foreign = create_site(SiteCreateRequest(name="其他站点", department=other), _user={"role": "admin"})
    user = {"role": role, "departments": [department]}
    monkeypatch.setattr(server, "get_current_user_from_request", lambda _request: user)
    suffixes = ("", "/config", "/status", "/frame.jpg", "/stream.mjpg", "/cameras",
                "/cameras/cam1/frame.jpg", "/alarms", "/alarms/1/image", "/alarms/1/video", "/statistics")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for authorized in ([department], [department, other]):
                user["departments"] = authorized
                for path in ["/api/sites", *(f"/api/sites/{site['id']}{suffix}" for suffix in suffixes)]:
                    assert (await client.get(path)).status_code == 422, path
                    for invalid in ("", "ge", "unknown", "通用电气"):
                        response = await client.get(path, params={"department": invalid})
                        assert response.status_code == 400, (path, response.text)
                response = await client.get("/api/sites", params={"department": department})
                assert response.status_code == 200
                assert [row["id"] for row in response.json()["items"]] == [site["id"]]
            for suffix in suffixes:
                response = await client.get(f"/api/sites/{foreign['id']}{suffix}", params={"department": department})
                assert response.status_code == 404, (suffix, response.text)
            user["departments"] = [department]
            if role == "viewer":
                assert (await client.get("/api/sites", params={"department": other})).status_code == 403

    asyncio.run(scenario())


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_business_writes_require_department_and_matching_resources(tmp_path, monkeypatch, department):
    app = _app(tmp_path)
    create_site = _route_endpoint(app, "/api/sites", "POST")
    other = next(value for value in DEPARTMENT_SPECS if value != department)
    foreign = create_site(SiteCreateRequest(name="其他站点", department=other), _user={"role": "admin"})
    create_camera = _route_endpoint(app, "/api/sites/{site_id}/cameras", "POST")
    camera = create_camera(foreign["id"], CameraCreateRequest(name="其他摄像头", rtsp_url="rtsp://camera"),
                           department=other, _user={"role": "admin"})
    monkeypatch.setattr(server, "get_current_user_from_request", lambda _request: {"role": "admin"})
    site_path = f"/api/sites/{foreign['id']}"
    requests = [
        ("PUT", site_path, {"name": "拒绝更新"}),
        ("DELETE", site_path, None),
        ("POST", f"{site_path}/config", {}),
        *(("POST", f"{site_path}/control/{action}", None) for action in ("start", "stop", "restart")),
        ("POST", f"{site_path}/cameras", {"name": "拒绝创建", "rtsp_url": "rtsp://new-camera"}),
        ("PUT", f"/api/cameras/{camera['id']}", {"name": "拒绝更新"}),
        ("DELETE", f"/api/cameras/{camera['id']}", None),
    ]

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/api/sites", json={"name": "缺少事业部"})).status_code == 422
            for method, path, payload in requests:
                assert (await client.request(method, path, json=payload)).status_code == 422, path
                assert (await client.request(method, path, params={"department": "ge"}, json=payload)).status_code == 400, path
                response = await client.request(method, path, params={"department": department}, json=payload)
                assert response.status_code == 404, (path, response.text)
            response = await client.get(site_path, params={"department": other})
            assert response.json()["name"] == foreign["name"]
            assert [row["id"] for row in response.json()["cameras"]] == [camera["id"]]

    asyncio.run(scenario())
