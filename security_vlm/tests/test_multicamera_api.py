import json
from pathlib import Path

import httpx
import pytest
import yaml

import camera_registry
import main


class FakeRuntimeManager:
    def __init__(self):
        self.running = set()
        self.shutdown_called = False

    @staticmethod
    def _require_general(department):
        assert department == "general_electric"

    def start(self, department, camera_id):
        self._require_general(department)
        self.running.add(camera_id)
        return self._result(department, camera_id, True, "running")

    def stop(self, department, camera_id):
        self._require_general(department)
        self.running.discard(camera_id)
        return self._result(department, camera_id, True, "stopped")

    def restart(self, department, camera_id):
        return self.start(department, camera_id)

    def start_all(self, department):
        self._require_general(department)
        return {"ok": True, "results": {}}

    def stop_all(self, department):
        self._require_general(department)
        self.running.clear()
        return {"ok": True, "results": {}}

    def is_running(self, department, camera_id):
        self._require_general(department)
        return camera_id in self.running

    def status(self, department, camera_id):
        running = self.is_running(department, camera_id)
        return {
            "department": department,
            "camera_id": camera_id,
            "running": running,
            "desired_running": running,
            "workers": {
                "capture": running,
                "detector": running,
                "session": running,
            },
            "last_error": "",
            "restart_at": None,
        }

    def reconcile(self):
        return None

    def shutdown(self):
        self.shutdown_called = True
        self.running.clear()

    def _result(self, department, camera_id, ok, message):
        return {
            "ok": ok,
            "department": department,
            "camera_id": camera_id,
            "running": self.is_running(department, camera_id),
            "desired_running": self.is_running(department, camera_id),
            "message": message,
        }


def make_service(tmp_path, *, input_video=""):
    config = {
        "project": {"root": str(tmp_path)},
        "envs": {"worker_python": "/env/bin/python"},
        "runtime": {"dir": str(tmp_path / "runtime")},
        "web": {},
        "data": {
            "input_video": input_video,
            "video_id": "stream",
            "camera_registry_path": str(tmp_path / "config" / "cameras.json"),
            "staff_identity_dir": str(tmp_path / "staff_rois"),
        },
        "staff_rois": {"security_staff_1": [1, 2, 3, 4]},
        "roi": {"min_area_px": 100, "max_vertices": 64},
        "session": {},
        "vlm": {},
        "output": {},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True),
        encoding="utf-8",
    )
    registry = camera_registry.CameraRegistry(
        Path(config["data"]["camera_registry_path"])
    )
    runtime_manager = FakeRuntimeManager()
    service = main.AppService(
        config_path,
        registry=registry,
        runtime_manager=runtime_manager,
        probe_func=lambda _url: {
            "codec_name": "hevc",
            "width": 2560,
            "height": 1440,
        },
        offload_sync=False,
    )
    return service, runtime_manager


def set_capture_dimensions(service, camera_id, width=200, height=100):
    service.camera_store(camera_id).write(
        "capture_status",
        {"ok": True, "width": width, "height": height},
    )


@pytest.mark.asyncio
async def test_camera_crud_redaction_and_running_conflicts(tmp_path):
    service, runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created_response = await client.post(
            "/api/cameras",
            json={
                "name": "安检工位一号",
                "rtsp_url": "rtsp://admin:secret@camera-a/stream",
            },
        )
        assert created_response.status_code == 201
        camera = created_response.json()["camera"]
        camera_id = camera["camera_id"]
        assert camera["rtsp_url"] == "rtsp://***:***@camera-a/stream"
        assert "secret" not in (await client.get("/api/cameras")).text
        credentials_response = await client.get(
            f"/api/cameras/{camera_id}/credentials"
        )
        assert credentials_response.status_code == 200
        assert credentials_response.json()["camera"]["rtsp_url"] == (
            "rtsp://admin:secret@camera-a/stream"
        )
        assert (
            await client.get("/api/cameras/missing/credentials")
        ).status_code == 404

        assert (await client.put(
            f"/api/cameras/{camera_id}",
            json={"name": "一号工位", "rtsp_url": ""},
        )).status_code == 200
        assert (await client.post(
            f"/api/cameras/{camera_id}/control/start"
        )).status_code == 200
        assert camera_id in runtime_manager.running
        assert (await client.put(
            f"/api/cameras/{camera_id}",
            json={"name": "运行中不可改"},
        )).status_code == 409
        assert (await client.delete(f"/api/cameras/{camera_id}")).status_code == 409

        await client.post(f"/api/cameras/{camera_id}/control/stop")
        assert (await client.delete(f"/api/cameras/{camera_id}")).status_code == 200
        assert (await client.get(f"/api/cameras/{camera_id}")).status_code == 404


@pytest.mark.asyncio
async def test_camera_test_controls_health_and_unknown_ids(tmp_path):
    service, _runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        tested = await client.post(
            "/api/cameras/test",
            json={"rtsp_url": "rtsp://admin:secret@camera-a/stream"},
        )
        assert tested.status_code == 200
        assert tested.json() == {
            "ok": True,
            "codec_name": "hevc",
            "width": 2560,
            "height": 1440,
        }
        assert "secret" not in tested.text
        assert (await client.post(
            "/api/cameras/test",
            json={"rtsp_url": "http://camera-a/stream"},
        )).status_code == 400

        camera_id = (await client.post(
            "/api/cameras",
            json={"name": "A", "rtsp_url": "rtsp://camera-a/stream"},
        )).json()["camera"]["camera_id"]
        assert (await client.post(
            f"/api/cameras/{camera_id}/control/start"
        )).json()["running"] is True
        health = (await client.get("/health")).json()
        assert health["running"] is True
        assert health["cameras"][0]["camera_id"] == camera_id
        assert health["cameras"][0]["running"] is True
        assert (await client.post("/api/cameras/control/stop-all")).status_code == 200
        assert (await client.post("/api/cameras/control/start-all")).status_code == 200
        assert (await client.post("/api/cameras/missing/control/start")).status_code == 404
        assert (await client.get("/video/missing/original")).status_code == 404


@pytest.mark.asyncio
async def test_camera_scoped_rois_and_history_filter(tmp_path):
    service, _runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        camera_a = (await client.post(
            "/api/cameras",
            json={"name": "A", "rtsp_url": "rtsp://camera-a/stream"},
        )).json()["camera"]
        camera_b = (await client.post(
            "/api/cameras",
            json={"name": "B", "rtsp_url": "rtsp://camera-b/stream"},
        )).json()["camera"]
        set_capture_dimensions(service, camera_a["camera_id"])

        saved = await client.post(
            f"/api/cameras/{camera_a['camera_id']}/rois",
            json={"staff_rois": {"工位 1": [10, 20, 30, 40]}},
        )
        assert saved.status_code == 200
        rectangle = [
            [10.0, 20.0],
            [30.0, 20.0],
            [30.0, 40.0],
            [10.0, 40.0],
        ]
        assert (await client.get(
            f"/api/cameras/{camera_a['camera_id']}/rois"
        )).json()["staff_rois"] == {"工位 1": rectangle}
        assert (await client.get(
            f"/api/cameras/{camera_b['camera_id']}/rois"
        )).json()["staff_rois"] == {
            "security_staff_1": [
                [1.0, 2.0],
                [3.0, 2.0],
                [3.0, 4.0],
                [1.0, 4.0],
            ]
        }

        polygon = [[5, 5], [150, 5], [180, 50], [100, 90], [10, 80]]
        polygon_saved = await client.post(
            f"/api/cameras/{camera_a['camera_id']}/rois",
            json={"staff_rois": {"多边形工位": polygon}},
        )
        assert polygon_saved.status_code == 200
        assert polygon_saved.json()["staff_rois"] == {
            "多边形工位": [[float(x), float(y)] for x, y in polygon]
        }
        assert (await client.get(
            f"/api/cameras/{camera_b['camera_id']}/rois"
        )).json()["staff_rois"] == {
            "security_staff_1": [
                [1.0, 2.0],
                [3.0, 2.0],
                [3.0, 4.0],
                [1.0, 4.0],
            ]
        }

        service.global_store.write(
            "vlm_history",
            {
                "items": [
                    {"camera_id": camera_a["camera_id"], "session_id": "a1"},
                    {"camera_id": camera_b["camera_id"], "session_id": "b1"},
                ],
            },
        )
        history = (await client.get(
            f"/api/history?camera_id={camera_a['camera_id']}"
        )).json()["history"]
        assert [item["session_id"] for item in history] == ["a1"]


@pytest.mark.asyncio
async def test_roi_save_requires_capture_dimensions_and_validates_geometry(tmp_path):
    service, _runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        camera_id = (await client.post(
            "/api/cameras",
            json={"name": "A", "rtsp_url": "rtsp://camera-a/stream"},
        )).json()["camera"]["camera_id"]
        endpoint = f"/api/cameras/{camera_id}/rois"

        missing_dimensions = await client.post(
            endpoint,
            json={"staff_rois": {"工位": [10, 10, 50, 50]}},
        )
        assert missing_dimensions.status_code == 409
        assert "启动摄像头" in missing_dimensions.json()["detail"]

        invalid_capture_statuses = [
            {"ok": 1, "width": 200, "height": 100},
            {"ok": True, "width": "200", "height": 100},
            {"ok": True, "width": True, "height": 100},
            {"ok": True, "width": 10**400, "height": 100},
            {"ok": True, "width": float("inf"), "height": 100},
        ]
        for status in invalid_capture_statuses:
            service.camera_store(camera_id).write("capture_status", status)
            invalid_dimensions = await client.post(
                endpoint,
                json={"staff_rois": {"工位": [10, 10, 50, 50]}},
            )
            assert invalid_dimensions.status_code == 409, status

        set_capture_dimensions(service, camera_id)
        invalid_coordinates = [
            [True, 10, 50, 50],
            ["10", 10, 50, 50],
            [[0, 0], [10**400, 0], [0, 50]],
        ]
        for coordinates in invalid_coordinates:
            invalid_number = await client.post(
                endpoint,
                json={"staff_rois": {"数值错误": coordinates}},
            )
            assert invalid_number.status_code == 400, coordinates

        out_of_bounds = await client.post(
            endpoint,
            json={"staff_rois": {"越界工位": [[0, 0], [201, 0], [0, 50]]}},
        )
        assert out_of_bounds.status_code == 400
        assert "越界工位" in out_of_bounds.json()["detail"]
        assert "画面范围" in out_of_bounds.json()["detail"]

        too_small = await client.post(
            endpoint,
            json={"staff_rois": {"小工位": [[0, 0], [5, 0], [0, 5]]}},
        )
        assert too_small.status_code == 400
        assert "小工位" in too_small.json()["detail"]
        assert "面积" in too_small.json()["detail"]

        too_few_points = await client.post(
            endpoint,
            json={"staff_rois": {"少点工位": [[0, 0], [20, 0]]}},
        )
        assert too_few_points.status_code == 400
        assert "少点工位" in too_few_points.json()["detail"]

        rounded_duplicate = await client.post(
            endpoint,
            json={
                "staff_rois": {
                    "舍入重复": [[0, 0], [50, 0], [50.004, 0.004], [0, 50]]
                }
            },
        )
        assert rounded_duplicate.status_code == 400
        assert "重复" in rounded_duplicate.json()["detail"]


@pytest.mark.asyncio
async def test_legacy_config_migrates_camera_and_roi_aliases(tmp_path):
    staff_dir = tmp_path / "staff_rois"
    staff_dir.mkdir()
    (staff_dir / "stream_staff_rois.json").write_text(
        json.dumps({"staff_rois": {"旧工位": [5, 6, 7, 8]}}),
        encoding="utf-8",
    )
    service, _runtime_manager = make_service(
        tmp_path,
        input_video="rtsp://legacy-camera/stream",
    )
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        cameras = (await client.get("/api/cameras")).json()["cameras"]
        assert cameras[0]["camera_id"] == "legacy-default"
        assert (await client.get("/api/rois")).json()["staff_rois"] == {
            "旧工位": [
                [5.0, 6.0],
                [7.0, 6.0],
                [7.0, 8.0],
                [5.0, 8.0],
            ]
        }
        paths = set(app.openapi()["paths"])
        assert "/video/{kind}" in paths
        assert "/video/{camera_id}/{kind}" in paths
