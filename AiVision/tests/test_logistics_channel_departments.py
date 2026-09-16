"""统一物流 Feature 的数据库过滤、成员归属与所有通道接口授权。"""
import asyncio
from types import SimpleNamespace

import anyio
import httpx
import pytest
from fastapi import FastAPI

from AiVision.api.routes import logistics_channels as api
from AiVision.departments.department_registry import DEPARTMENT_SPECS
from AiVision.cameras.orm import AiCameraConfig
from AiVision.features.logistics_channel.constants import LOGISTICS_FEATURE_NAME as FEATURE
from AiVision.features.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera
from AiVision.tests.test_logistics_channel_service import service_db as service_db, _seed_camera


def test_names_are_unique_within_department_and_department_cannot_be_patched(service_db):
    service = service_db.service
    for department in DEPARTMENT_SPECS:
        channel = service.create_channel(FEATURE, "一号通道", department)
        assert channel["department"] == department
        with pytest.raises(ValueError, match="已存在"):
            service.create_channel(FEATURE, "一号通道", department)
    with pytest.raises(ValueError, match="department"):
        service.update_channel_and_config(FEATURE, channel["id"], {"department": "general_electric"}, None)
    assert len(service.list_channels(FEATURE)["items"]) == len(DEPARTMENT_SPECS)
    assert len(service.list_channels(FEATURE, departments=["electrical_components"])["items"]) == 1
    assert service.list_channels(FEATURE, departments=[])["items"] == []


def test_inventory_filters_both_channels_and_cameras_in_database(service_db):
    service = service_db.service
    own = service.create_channel(FEATURE, "一号", "general_electric")
    other = service.create_channel(FEATURE, "一号", "electronics_electrician")
    own_camera = _seed_camera(service_db, "own", department="general_electric")
    other_camera = _seed_camera(service_db, "other", department="electronics_electrician")
    service.add_existing_camera(FEATURE, own["id"], own_camera)
    service.add_existing_camera(FEATURE, other["id"], other_camera)
    # 模拟异常历史成员，授权过滤仍不得把另一事业部 Camera 泄露给用户。
    with service_db.factory.begin() as session:
        session.add(LogisticsChannelCamera(channel_id=own["id"], camera_id=other_camera))
    inventory = service.list_camera_inventory([FEATURE], departments=["general_electric"])
    assert [item["camera_id"] for item in inventory] == [own_camera]
    assert service.list_camera_inventory([FEATURE], departments=[]) == []


def test_empty_camera_department_does_not_gain_all_logistics_departments(service_db):
    _seed_camera(service_db, "未归属物流相机", department=None, enabled_features=(FEATURE,))
    for department in DEPARTMENT_SPECS:
        assert service_db.camera_config_manager.list_cameras(department) == []


def test_camera_department_is_inherited_and_cross_department_membership_rejected(service_db):
    service = service_db.service
    own = service.create_channel(FEATURE, "一号", "electronics_electrician")
    other = service.create_channel(FEATURE, "一号", "electrical_components")
    result = service.create_camera_and_bind(FEATURE, own["id"], {"name": "新相机", "url": "rtsp://example.invalid/stream"})
    camera_id = result["members"][0]["camera_id"]
    with service_db.factory() as session:
        assert session.get(AiCameraConfig, camera_id).department == "electronics_electrician"
    with pytest.raises(ValueError, match="department"):
        service.move_camera(FEATURE, camera_id, other["id"])
    with pytest.raises(ValueError, match="department"):
        service.add_existing_camera(FEATURE, other["id"], camera_id)
    blank = _seed_camera(service_db, "未归属相机", department=None)
    with pytest.raises(ValueError, match="department 为空"):
        service.add_existing_camera(FEATURE, own["id"], blank)
    with service_db.factory() as session:
        assert session.get(AiCameraConfig, blank).department is None
        assert session.query(LogisticsChannelCamera).filter_by(camera_id=blank).count() == 0
        assert session.get(LogisticsChannel, own["id"]).department == "electronics_electrician"


@pytest.mark.parametrize("method,suffix,payload", [
    ("GET", "", None), ("GET", "/status", None), ("GET", "/frame.jpg", None),
    ("GET", "/alarms", None), ("GET", "/statistics", None),
    ("GET", "/cameras/1/config", None),
    ("PATCH", "", {"name": "更新"}), ("DELETE", "", None),
    ("POST", "/cameras", {"camera_id": 1}),
    ("PUT", "/cameras/order", {"camera_ids": [1]}),
    ("PUT", "/cameras/1", None), ("PUT", "/cameras/1/enabled", {"enabled": True}),
    ("PUT", "/cameras/1/config", {}), ("DELETE", "/cameras/1", None),
])
def test_every_channel_route_rejects_foreign_department(service_db, monkeypatch, method, suffix, payload):
    service = service_db.service
    channel = service.create_channel(FEATURE, "受保护通道", "electronics_electrician")
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_current_user] = lambda: {"role": "viewer", "departments": ["general_electric"]}
    app.dependency_overrides[api.get_logistics_channel_service] = lambda: service
    def forbidden(*args, **kwargs):
        raise AssertionError("未授权请求不得访问 Runtime、告警库或配置")
    app.dependency_overrides[api.get_current_orchestrator] = lambda: SimpleNamespace(get_logistics_channel_status=forbidden, get_logistics_channel_frame=forbidden)
    app.dependency_overrides[api.get_feature_config_manager] = lambda: SimpleNamespace(get_config=forbidden, save_config=forbidden)
    monkeypatch.setattr(api, "get_session", forbidden)
    async def inline(func, *args, **kwargs):
        return func(*args)
    monkeypatch.setattr(anyio.to_thread, "run_sync", inline)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.request(method, f"/api/logistics-channels/{FEATURE}/{channel['id']}{suffix}", json=payload)
            assert response.status_code == 403, response.text
    asyncio.run(scenario())


@pytest.mark.parametrize("user,expected", [
    ({"role": "viewer", "departments": ["general_electric"]}, ["general_electric"]),
    ({"role": "viewer", "departments": []}, []),
    ({"role": "viewer", "departments": ["all"]}, []),
    ({"role": "admin"}, ["general_electric", "electronics_electrician"]),
])
def test_api_list_passes_user_departments_to_database(service_db, user, expected):
    service = service_db.service
    for department in ("general_electric", "electronics_electrician"):
        service.create_channel(FEATURE, "同名", department)
    assert [item.department for item in api.list_channels(FEATURE, user, service).items] == expected


@pytest.mark.parametrize("user", [
    {"role": "admin"},
    {"role": "viewer", "departments": list(DEPARTMENT_SPECS)},
    {"role": "viewer", "departments": ["general_electric", "electronics_electrician"]},
    {"role": "viewer", "departments": ["electronics_electrician"]},
])
def test_department_page_filters_channels_and_inventory_before_response(service_db, user):
    service = service_db.service
    channels = {}
    cameras = {}
    for department in DEPARTMENT_SPECS:
        channels[department] = service.create_channel(FEATURE, "同名通道", department)
        cameras[department] = _seed_camera(service_db, department, department=department)
        service.add_existing_camera(FEATURE, channels[department]["id"], cameras[department])
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_current_user] = lambda: user
    app.dependency_overrides[api.get_logistics_channel_service] = lambda: service
    app.dependency_overrides[api.get_current_orchestrator] = lambda: SimpleNamespace(
        get_logistics_channel_status=lambda *args: {},
    )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            department = "electronics_electrician"
            response = await client.get(f"/api/logistics-channels/{FEATURE}", params={"department": department})
            assert response.status_code == 200, response.text
            assert [(item["id"], item["department"]) for item in response.json()["items"]] == [
                (channels[department]["id"], department),
            ]
            response = await client.get("/api/logistics-channels/inventory", params={"department": department})
            assert response.status_code == 200, response.text
            assert [(item["camera_id"], item["department"]) for item in response.json()["items"]] == [
                (cameras[department], department),
            ]
    asyncio.run(scenario())


@pytest.mark.parametrize("resource", [FEATURE, "inventory"])
@pytest.mark.parametrize("departments,requested,expected", [
    (["general_electric"], "electronics_electrician", 403),
    (["general_electric", "electronics_electrician"], "electrical_components", 403),
    ([], "general_electric", 403),
    (["all"], "all", 400),
    (["all"], "unknown", 400),
    (["all"], "", 400),
])
def test_department_query_cannot_bypass_permissions(resource, departments, requested, expected):
    def forbidden(*args, **kwargs):
        raise AssertionError("越权或非法事业部请求不得查询数据库")
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_current_user] = lambda: {"role": "viewer", "departments": departments}
    app.dependency_overrides[api.get_logistics_channel_service] = lambda: SimpleNamespace(
        list_channels=forbidden, list_camera_inventory=forbidden,
    )
    app.dependency_overrides[api.get_current_orchestrator] = lambda: SimpleNamespace()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.get(f"/api/logistics-channels/{resource}", params={"department": requested})
            assert response.status_code == expected, response.text
    asyncio.run(scenario())
