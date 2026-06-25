import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import configure_for_tests
from src.server import CameraCreateRequest, CameraUpdateRequest, SiteCreateRequest, create_app


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

    def start(self, site_id: int):
        self.started.append(site_id)
        return {"site_id": site_id, "site_name": "测试保安室", "running": True}

    def stop(self, site_id: int):
        self.stopped.append(site_id)
        return {"site_id": site_id, "site_name": "测试保安室", "running": False}

    def restart(self, site_id: int):
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


def test_site_api_routes_create_site_and_camera(tmp_path):
    app = _app(tmp_path)

    create_site = _route_endpoint(app, "/api/sites", "POST")
    list_sites = _route_endpoint(app, "/api/sites", "GET")
    get_site = _route_endpoint(app, "/api/sites/{site_id}", "GET")
    create_camera = _route_endpoint(app, "/api/sites/{site_id}/cameras", "POST")

    site = create_site(SiteCreateRequest(name="一厂区南门保安室"), _user={"role": "admin"})
    assert site["name"] == "一厂区南门保安室"
    assert site["camera_count"] == 0

    listed = list_sites()
    assert [item["name"] for item in listed["items"]] == ["一厂区南门保安室"]

    camera = create_camera(
        site["id"],
        CameraCreateRequest(name="门口左侧", rtsp_url="rtsp://camera-1"),
        _user={"role": "admin"},
    )
    assert camera["sort_order"] == 1

    detail = get_site(site["id"])
    assert detail["cameras"][0]["name"] == "门口左侧"


def test_site_api_routes_update_and_delete_camera(tmp_path):
    app = _app(tmp_path)

    create_site = _route_endpoint(app, "/api/sites", "POST")
    create_camera = _route_endpoint(app, "/api/sites/{site_id}/cameras", "POST")
    update_camera = _route_endpoint(app, "/api/cameras/{camera_id}", "PUT")
    delete_camera = _route_endpoint(app, "/api/cameras/{camera_id}", "DELETE")
    get_site = _route_endpoint(app, "/api/sites/{site_id}", "GET")

    site = create_site(SiteCreateRequest(name="二厂区值班室"), _user={"role": "admin"})
    camera = create_camera(
        site["id"],
        CameraCreateRequest(name="旧名称", rtsp_url="rtsp://old"),
        _user={"role": "admin"},
    )

    updated = update_camera(
        camera["id"],
        CameraUpdateRequest(name="门口右侧", rtsp_url="rtsp://new", enabled=False),
        _user={"role": "admin"},
    )
    assert updated["name"] == "门口右侧"
    assert updated["rtsp_url"] == "rtsp://new"
    assert updated["enabled"] is False

    assert delete_camera(camera["id"], _user={"role": "admin"}) == {"success": True}
    assert get_site(site["id"])["cameras"] == []


def test_site_api_routes_expose_runtime_controls_and_read_models(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_api_runtime.db'}")
    manager = FakeRuntimeManager()
    app = create_app(
        str(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"),
        runtime_manager=manager,
    )

    start = _route_endpoint(app, "/api/sites/{site_id}/control/start", "POST")
    stop = _route_endpoint(app, "/api/sites/{site_id}/control/stop", "POST")
    restart = _route_endpoint(app, "/api/sites/{site_id}/control/restart", "POST")
    status = _route_endpoint(app, "/api/sites/{site_id}/status", "GET")
    frame = _route_endpoint(app, "/api/sites/{site_id}/frame.jpg", "GET")
    camera_frame = _route_endpoint(app, "/api/sites/{site_id}/cameras/{camera_id}/frame.jpg", "GET")
    alarms = _route_endpoint(app, "/api/sites/{site_id}/alarms", "GET")
    statistics = _route_endpoint(app, "/api/sites/{site_id}/statistics", "GET")

    assert start(7, _user={"role": "admin"})["running"] is True
    assert stop(7, _user={"role": "admin"})["running"] is False
    assert restart(7, _user={"role": "admin"})["restarted"] is True
    assert status(7)["site_name"] == "测试保安室"
    assert frame(7).body == b"jpeg-bytes"
    assert camera_frame(7, "cam2").body == b"7:cam2:jpeg"
    assert alarms(7)["items"][0]["site_id"] == 7
    assert statistics(7)["summary"]["total"] == 0
