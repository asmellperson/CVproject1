import asyncio
import importlib
import sys

import anyio.to_thread
import httpx
import numpy as np
import pytest
from fastapi import FastAPI, HTTPException


sys.modules.pop("platform", None)
cameras_module = importlib.import_module("api.v2.cameras")
compat_module = importlib.import_module("api.compat")
get_camera_frame_jpg = cameras_module.get_camera_frame_jpg
compat_get_camera_frame_jpg = compat_module.compat_get_camera_frame_jpg


class FrameOrchestrator:
    def __init__(self, frame):
        self.frame = frame

    def get_camera_frame_info(self, key, feature=None):
        return self.frame, 123.0


class FrameCameraService:
    def get_camera(self, key):
        return {"shm_name": key, "department": "general_electric"}


class PermissionCameraService:
    def __init__(self):
        self.cameras = [
            {
                "id": "camera_1", "camera_id": 1, "name": "本部门摄像头",
                "shm_name": "camera_1", "url": "rtsp://general/one",
                "enabled": True, "department": "general_electric", "functions": {},
            },
            {
                "id": "camera_2", "camera_id": 2, "name": "其他部门摄像头",
                "shm_name": "camera_2", "url": "rtsp://other/two",
                "enabled": True, "department": "electronics_electrician", "functions": {},
            },
        ]

    def list_cameras(self, department=None):
        if department is None:
            return list(self.cameras)
        return [item for item in self.cameras if item["department"] == department]

    def get_camera(self, key):
        key = str(key)
        for item in self.cameras:
            if key in {item["id"], item["shm_name"], item["name"], str(item["camera_id"])}:
                return dict(item)
        return None


def test_v2_and_compat_camera_reads_are_scoped_by_department(monkeypatch):
    service = PermissionCameraService()
    app = FastAPI()
    app.include_router(cameras_module.router)
    app.include_router(compat_module.router)
    app.dependency_overrides[cameras_module.get_camera_service] = lambda: service

    async def inline_run_sync(func, *args, **_kwargs):
        return func(*args)

    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            def unauthenticated():
                raise HTTPException(status_code=401, detail="not authenticated")

            app.dependency_overrides[cameras_module.get_current_user] = unauthenticated
            for prefix in ("/api/v2/cameras", "/api/aivision/cameras"):
                assert (await client.get(prefix)).status_code == 401
                assert (await client.get(f"{prefix}/1")).status_code == 401

            viewer = {"role": "viewer", "department": "general_electric"}
            app.dependency_overrides[cameras_module.get_current_user] = lambda: viewer
            for prefix in ("/api/v2/cameras", "/api/aivision/cameras"):
                default_list = await client.get(prefix)
                assert default_list.status_code == 200
                assert [item["camera_id"] for item in default_list.json()] == [1]
                assert default_list.json()[0]["url"] == "rtsp://general/one"
                assert (await client.get(
                    prefix,
                    params={"department": "electronics_electrician"},
                )).status_code == 403
                assert (await client.get(f"{prefix}/1")).status_code == 200
                assert (await client.get(f"{prefix}/camera_1")).status_code == 200
                assert (await client.get(f"{prefix}/2")).status_code == 403
                assert (await client.get(f"{prefix}/camera_2")).status_code == 403

            admin = {"role": "admin", "department": None}
            app.dependency_overrides[cameras_module.get_current_user] = lambda: admin
            for prefix in ("/api/v2/cameras", "/api/aivision/cameras"):
                all_cameras = await client.get(prefix)
                assert [item["camera_id"] for item in all_cameras.json()] == [1, 2]
                filtered = await client.get(
                    prefix,
                    params={"department": "electronics_electrician"},
                )
                assert [item["camera_id"] for item in filtered.json()] == [2]
                assert (await client.get(f"{prefix}/camera_2")).status_code == 200

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "handler",
    [get_camera_frame_jpg, compat_get_camera_frame_jpg],
)
def test_frame_response_exposes_original_dimensions_when_preview_is_resized(handler):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    response = handler(
        key="camera-1",
        feature="detect_human",
        quality=72,
        max_width=960,
        max_height=None,
        user={"role": "viewer", "department": "general_electric"},
        camera_service=FrameCameraService(),
        orchestrator=FrameOrchestrator(frame),
    )

    assert response.headers["x-frame-width"] == "1920"
    assert response.headers["x-frame-height"] == "1080"


def test_slow_frame_response_logs_lookup_and_encode_timings(monkeypatch):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    warnings: list[str] = []
    monotonic_values = iter([0.0, 0.2, 0.2, 1.5, 1.5])

    monkeypatch.setattr(cameras_module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(cameras_module, "encode_frame_to_jpeg", lambda *args, **kwargs: b"jpeg")
    monkeypatch.setattr(cameras_module.logger, "warning", warnings.append)
    monkeypatch.setattr(cameras_module.settings.runtime, "slow_frame_log_seconds", 1.0)

    response = cameras_module.build_camera_frame_response(
        key="camera-1",
        feature="detect_human",
        quality=72,
        max_width=960,
        max_height=None,
        orchestrator=FrameOrchestrator(frame),
    )

    assert response.body == b"jpeg"
    assert len(warnings) == 1
    assert "key=camera-1" in warnings[0]
    assert "lookup=0.200s" in warnings[0]
    assert "encode=1.300s" in warnings[0]
    assert "total=1.500s" in warnings[0]
