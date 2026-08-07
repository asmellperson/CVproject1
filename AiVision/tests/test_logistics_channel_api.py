import asyncio
import importlib
import sys
from copy import deepcopy

import numpy as np
import pytest
from fastapi import HTTPException
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
    with pytest.raises(HTTPException) as caught:
        api.get_channel_frame(feature, 999, 85, None, None, ADMIN, service, orchestrator)
    assert caught.value.status_code == 404
