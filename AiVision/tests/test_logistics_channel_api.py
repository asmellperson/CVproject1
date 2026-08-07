import asyncio
import importlib
import sys
from copy import deepcopy

import numpy as np
import pytest
import anyio.to_thread
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import ResponseValidationError
from fastapi.routing import serialize_response


sys.modules.pop("platform", None)
api = importlib.import_module("api.v2.logistics_channels")

FEATURES = tuple(sorted(importlib.import_module(
    "platform.logistics_channel.constants"
).LOGISTICS_FEATURES))
ADMIN = {"role": "admin", "department": None}


class FakeService:
    def __init__(self):
        self.channels = {feature: {} for feature in FEATURES}
        self.next_id = 1
        self.calls = []
        self.error = None

    def _raise(self):
        if self.error:
            raise ValueError(self.error)

    def list_channels(self, feature):
        return {"items": [deepcopy(value) for value in self.channels[feature].values()]}

    def get_channel(self, feature, channel_id):
        return deepcopy(self.channels[feature].get(channel_id))

    def create_channel(self, feature, name):
        self._raise()
        channel_id = self.next_id
        self.next_id += 1
        value = {
            "id": channel_id, "name": name, "feature_name": feature,
            "enabled": True, "sort_order": 0,
            "config": {
                "enabled": True,
                "detection_start": "08:00:00",
                "detection_end": "20:00:00",
                "empty_grace_seconds": 2,
                "multi_grace_seconds": 1,
                "alarm_interval": 5,
                "alarm": {},
            },
            "members": [],
        }
        self.channels[feature][channel_id] = value
        return deepcopy(value)

    def update_channel(self, feature, channel_id, payload):
        self._raise()
        value = self.channels[feature].get(channel_id)
        if value is not None:
            value.update(payload)
        return deepcopy(value)

    def update_config(self, feature, channel_id, payload):
        self._raise()
        value = self.channels[feature].get(channel_id)
        if value is None:
            return None
        update = payload.model_dump(exclude_unset=True)
        value["config"].update(update)
        self.calls.append(("config", feature, channel_id, update))
        return deepcopy(value)

    def update_channel_and_config(self, feature, channel_id, metadata, config):
        value = self.update_channel(feature, channel_id, metadata)
        if value is None or config is None:
            return value
        return self.update_config(feature, channel_id, config)

    def delete_channel(self, feature, channel_id):
        return self.channels[feature].pop(channel_id, None) is not None

    def add_existing_camera(self, feature, channel_id, camera_id):
        self._raise()
        value = self.channels[feature][channel_id]
        value["members"].append({
            "id": len(value["members"]) + 1, "channel_id": channel_id,
            "camera_id": camera_id, "enabled": True,
            "sort_order": len(value["members"]),
        })
        return deepcopy(value)

    def create_camera_and_bind(self, feature, channel_id, payload):
        self.calls.append(("create_camera", feature, channel_id, payload.name, payload.url))
        return self.add_existing_camera(feature, channel_id, 99)

    def reorder_members(self, feature, channel_id, camera_ids):
        value = self.channels[feature][channel_id]
        members = {member["camera_id"]: member for member in value["members"]}
        value["members"] = [members[camera_id] for camera_id in camera_ids]
        for index, member in enumerate(value["members"]):
            member["sort_order"] = index
        return deepcopy(value)

    def move_camera(self, feature, camera_id, channel_id):
        self.calls.append(("move", feature, camera_id, channel_id))
        return deepcopy(self.channels[feature][channel_id])

    def remove_camera(self, feature, channel_id, camera_id):
        value = self.channels[feature].get(channel_id)
        if value is None:
            return False
        before = len(value["members"])
        value["members"] = [m for m in value["members"] if m["camera_id"] != camera_id]
        return len(value["members"]) != before


class FakeOrchestrator:
    status = None
    frame = None

    def get_logistics_channel_status(self, feature, channel_id):
        return deepcopy(self.status)

    def get_logistics_channel_frame(self, feature, channel_id):
        return self.frame


class EmptyAlarmQuery:
    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def limit(self, _limit):
        return self

    def all(self):
        return []


class EmptyAlarmSession:
    def query(self, _model):
        return EmptyAlarmQuery()

    def close(self):
        return None


def _seed(service, feature=FEATURES[0], name="一号通道"):
    return service.create_channel(feature, name)


def test_router_exposes_full_channel_contract_and_app_registers_it():
    paths = {(route.path, method) for route in api.router.routes for method in route.methods}
    expected = {
        ("/api/v2/logistics-channels/{feature}", "GET"),
        ("/api/v2/logistics-channels/{feature}", "POST"),
        ("/api/v2/logistics-channels/{feature}/{channel_id}", "GET"),
        ("/api/v2/logistics-channels/{feature}/{channel_id}", "PUT"),
        ("/api/v2/logistics-channels/{feature}/{channel_id}", "DELETE"),
        ("/api/v2/logistics-channels/{feature}/{channel_id}/cameras", "POST"),
        ("/api/v2/logistics-channels/{feature}/{channel_id}/cameras/order", "PUT"),
        ("/api/v2/logistics-channels/{feature}/{channel_id}/status", "GET"),
        ("/api/v2/logistics-channels/{feature}/{channel_id}/frame.jpg", "GET"),
        ("/api/v2/logistics-channels/{feature}/{channel_id}/alarms", "GET"),
        ("/api/v2/logistics-channels/{feature}/{channel_id}/statistics", "GET"),
    }
    assert expected <= paths
    app_module = importlib.import_module("api.app")
    assert any(route.path.startswith("/api/v2/logistics-channels") for route in app_module.app.routes)

    openapi = app_module.app.openapi()
    for path, methods in openapi["paths"].items():
        if not path.startswith("/api/v2/logistics-channels"):
            continue
        for method, operation in methods.items():
            if method == "parameters" or path.endswith("frame.jpg"):
                continue
            success_code = "201" if "201" in operation["responses"] else "200"
            schema = operation["responses"][success_code][
                "content"
            ]["application/json"]["schema"]
            assert schema.get("$ref") or schema.get("type") == "object"


def test_fastapi_response_field_filters_and_rejects_invalid_output():
    route = next(
        route for route in api.router.routes
        if route.path == "/api/v2/logistics-channels/{feature}" and "GET" in route.methods
    )
    valid = {
        "items": [{
            "id": 1,
            "name": "一号通道",
            "feature_name": FEATURES[0],
            "enabled": True,
            "sort_order": 0,
            "server_only": "must be filtered",
        }],
        "server_only": "must be filtered",
    }
    encoded = asyncio.run(serialize_response(
        field=route.response_field,
        response_content=valid,
        is_coroutine=True,
    ))
    assert "server_only" not in encoded
    assert "server_only" not in encoded["items"][0]

    with pytest.raises(ResponseValidationError):
        asyncio.run(serialize_response(
            field=route.response_field,
            response_content={"items": [{"id": "invalid"}]},
            is_coroutine=True,
        ))


def test_real_asgi_auth_permissions_and_endpoint_contracts(monkeypatch):
    service = FakeService()
    orchestrator = FakeOrchestrator()
    channel = _seed(service)
    feature = "detect_logistics_single_person"
    channel_id = channel["id"]
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_logistics_channel_service] = lambda: service
    app.dependency_overrides[api.get_current_orchestrator] = lambda: orchestrator
    monkeypatch.setattr(api, "get_session", EmptyAlarmSession)

    async def inline_run_sync(func, *args, **_kwargs):
        return func(*args)

    # 受限测试环境不允许 worker thread；仍通过完整 ASGI 路由/依赖/序列化栈请求。
    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            base = f"/api/v2/logistics-channels/{feature}"
            assert (await client.get(base)).status_code == 401

            viewer = {"role": "viewer", "department": "general_electric"}
            app.dependency_overrides[api.get_current_user] = lambda: viewer
            assert (await client.get(base)).status_code == 200
            assert (await client.get(
                "/api/v2/logistics-channels/"
                "detect_logistics_single_person_electronics_electrician"
            )).status_code == 403

            write_requests = (
                ("POST", base, {"name": "禁止新增"}),
                ("PUT", f"{base}/{channel_id}", {"name": "禁止更新"}),
                ("DELETE", f"{base}/{channel_id}", None),
                ("PUT", f"{base}/{channel_id}/config", {"empty_grace_seconds": 3}),
                ("POST", f"{base}/{channel_id}/cameras", {"camera_id": 7}),
                ("PUT", f"{base}/{channel_id}/cameras/order", {"camera_ids": [7]}),
                ("PUT", f"{base}/{channel_id}/cameras/7", None),
                ("DELETE", f"{base}/{channel_id}/cameras/7", None),
            )
            for method, url, payload in write_requests:
                response = await client.request(method, url, json=payload)
                assert response.status_code == 403, (method, url, response.text)

            app.dependency_overrides[api.require_admin] = lambda: ADMIN
            created = await client.post(base, json={"name": "管理员新增"})
            assert created.status_code == 201
            assert created.json()["name"] == "管理员新增"
            assert (await client.put(
                f"{base}/{channel_id}",
                json={"name": "管理员更新", "config": {"empty_grace_seconds": 3}},
            )).status_code == 200
            assert (await client.put(
                f"{base}/{channel_id}/config",
                json={"empty_grace_seconds": 4},
            )).status_code == 200
            assert (await client.post(
                f"{base}/{channel_id}/cameras",
                json={"camera_id": 7},
            )).status_code == 200
            assert (await client.get(
                "/api/v2/logistics-channels/not-a-feature"
            )).status_code == 404
            assert (await client.post(base, json={})).status_code == 422
            assert (await client.put(
                f"{base}/{channel_id}/config",
                json={"detection_start": "20:00:00", "detection_end": "08:00:00"},
            )).status_code == 422

            assert (await client.get(f"{base}/{channel_id}/status")).status_code == 200
            assert (await client.get(f"{base}/{channel_id}/frame.jpg")).status_code == 503
            orchestrator.frame = np.zeros((60, 120, 3), dtype=np.uint8)
            frame = await client.get(f"{base}/{channel_id}/frame.jpg")
            assert frame.status_code == 200
            assert frame.headers["content-type"] == "image/jpeg"
            assert frame.content.startswith(b"\xff\xd8")
            alarms = await client.get(f"{base}/{channel_id}/alarms")
            assert alarms.status_code == 200
            assert alarms.json() == {"items": []}
            statistics = await client.get(f"{base}/{channel_id}/statistics")
            assert statistics.status_code == 200
            assert statistics.json()["summary"] == {"total": 0, "today": 0}

    asyncio.run(scenario())


def test_four_features_are_isolated_and_whitelisted():
    service = FakeService()
    for index, feature in enumerate(FEATURES):
        api.create_channel(feature, api.LogisticsChannelCreate(name=f"通道-{index}"), ADMIN, service)
    for index, feature in enumerate(FEATURES):
        assert [item.name for item in api.list_channels(feature, ADMIN, service).items] == [f"通道-{index}"]
    with pytest.raises(HTTPException) as caught:
        api.list_channels("arbitrary", ADMIN, service)
    assert caught.value.status_code == 404


def test_viewer_department_access_and_admin_dependency_contract():
    general_feature = "detect_logistics_single_person"
    viewer = {"role": "viewer", "department": "general_electric"}
    assert api._require_feature_access(general_feature, viewer) == general_feature
    other = next(feature for feature in FEATURES if feature != general_feature)
    with pytest.raises(HTTPException) as caught:
        api._require_feature_access(other, viewer)
    assert caught.value.status_code == 403
    create_route = next(
        route for route in api.router.routes
        if route.path == "/api/v2/logistics-channels/{feature}" and "POST" in route.methods
    )
    assert any(dependency.call.__name__ == "require_admin" for dependency in create_route.dependant.dependencies)


def test_crud_config_and_validation_models():
    service = FakeService()
    channel = api.create_channel(FEATURES[0], api.LogisticsChannelCreate(name="初始"), ADMIN, service)
    payload = api.LogisticsChannelPutRequest(
        name="更新",
        config={
            "detection_start": "09:00:00", "detection_end": "18:00:00",
            "empty_grace_seconds": 3,
        },
    )
    result = api.update_channel(FEATURES[0], channel.id, payload, ADMIN, service)
    assert result.name == "更新"
    assert result.config.empty_grace_seconds == 3
    assert api.get_channel(FEATURES[0], channel.id, ADMIN, service).name == "更新"
    assert api.delete_channel(FEATURES[0], channel.id, ADMIN, service).ok is True
    with pytest.raises(HTTPException) as caught:
        api.get_channel(FEATURES[0], channel.id, ADMIN, service)
    assert caught.value.status_code == 404

    with pytest.raises(ValueError):
        api.LogisticsChannelConfigUpdate(
            detection_start="20:00:00", detection_end="08:00:00"
        )
    with pytest.raises(ValueError):
        api.LogisticsChannelConfigUpdate(roi_pos=[[0, 0], [1, 1]])


def test_member_bind_create_reorder_move_and_remove():
    service = FakeService()
    source = _seed(service, name="来源")
    target = _seed(service, name="目标")
    feature = FEATURES[0]
    api.add_camera(feature, source["id"], api.LogisticsChannelMemberCreate(camera_id=7), ADMIN, service)
    api.add_camera(feature, source["id"], api.LogisticsChannelMemberCreate(camera_id=8), ADMIN, service)
    ordered = api.reorder_cameras(
        feature, source["id"], api.LogisticsChannelMemberOrder(camera_ids=[8, 7]), ADMIN, service
    )
    assert [member.camera_id for member in ordered.members] == [8, 7]
    api.move_camera(feature, target["id"], 8, ADMIN, service)
    assert ("move", feature, 8, target["id"]) in service.calls
    assert api.remove_camera(feature, source["id"], 7, ADMIN, service).ok is True
    api.add_camera(
        feature, source["id"],
        api.LogisticsChannelMemberCreate(name="新增", url="rtsp://camera"),
        ADMIN, service,
    )
    assert any(call[0] == "create_camera" for call in service.calls)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("同一功能下通道名称已存在", 409),
        ("通道已达到最多 9 路上限", 409),
        ("摄像头不存在: 42", 404),
        ("department 必须与功能归属一致", 400),
    ],
)
def test_service_errors_have_stable_http_mapping(message, expected):
    service = FakeService()
    service.error = message
    with pytest.raises(HTTPException) as caught:
        api.create_channel(FEATURES[0], api.LogisticsChannelCreate(name="冲突"), ADMIN, service)
    assert caught.value.status_code == expected


def test_status_response_and_composite_jpeg_semantics():
    service = FakeService()
    orchestrator = FakeOrchestrator()
    channel = _seed(service)
    feature, channel_id = FEATURES[0], channel["id"]
    fallback = api.get_channel_status(feature, channel_id, ADMIN, service, orchestrator)
    assert fallback.reason == "unknown"
    assert fallback.alarm is False

    orchestrator.status = {
        "feature_name": feature,
        "channel_id": channel_id,
        "channel_name": "一号通道",
        "reason": "normal",
        "alarm": False,
        "camera_ids": [7],
        "camera_counts": {"7": 1},
        "camera_states": {},
        "offending_camera_ids": [],
        "updated_at": 1.0,
    }
    status = api.get_channel_status(feature, channel_id, ADMIN, service, orchestrator)
    assert status.reason == "normal"
    assert status.camera_counts == {"7": 1}

    with pytest.raises(HTTPException) as caught:
        api.get_channel_frame(feature, channel_id, 85, None, None, ADMIN, service, orchestrator)
    assert caught.value.status_code == 503
    orchestrator.frame = np.zeros((120, 240, 3), dtype=np.uint8)
    response = api.get_channel_frame(feature, channel_id, 85, None, None, ADMIN, service, orchestrator)
    assert response.media_type == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-width"] == "240"
    assert response.body.startswith(b"\xff\xd8")
    resized = api.get_channel_frame(
        feature, channel_id, 85, 120, None, ADMIN, service, orchestrator
    )
    assert "x-frame-width" not in resized.headers
    assert "x-frame-height" not in resized.headers
    with pytest.raises(HTTPException) as caught:
        api.get_channel_frame(feature, 999, 85, None, None, ADMIN, service, orchestrator)
    assert caught.value.status_code == 404
