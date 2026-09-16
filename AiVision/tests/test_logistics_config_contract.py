"""最终物流配置的导入、校验、成员接口保存/回显及推理参数来源。"""
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from AiVision.core.cache import ConfigCache
from AiVision.features.logistics_channel.spec import SPEC
from AiVision.features.logistics_channel.schema import LogisticsSinglePersonConfigSchema, LogisticsChannelConfigUpdate
from AiVision.tests.test_logistics_channel_service import service_db as service_db, _seed_camera
from AiVision.tests.test_logistics_single_person import build_consumer, RuntimeSpy


@pytest.mark.parametrize('entry', [
    'AiVision.features', 'AiVision.features.logistics_channel.service',
    'AiVision.features.logistics_channel.runtime',
    'AiVision.cameras.config_manager', 'AiVision.runtime.orchestrator',
])
def test_fresh_process_imports_register_all_features_once(entry):
    script = f'''import importlib
importlib.import_module({entry!r})
from AiVision.features.registry import all_specs
from AiVision.core.db import Base
from AiVision.features.logistics_channel.spec import SPEC
expected = {{
    'blocks', 'detect_door', 'detect_face', 'detect_human',
    'detect_logistics_single_person', 'detect_phone', 'recognize_face',
}}
specs = all_specs()
assert set(specs) == expected, sorted(specs)
assert {{spec.name for spec in specs.values()}} == expected
assert len({{id(spec) for spec in specs.values()}}) == len(expected)
assert len({{spec.orm_class for spec in specs.values()}}) == len(expected)
packages = {{
    'blocks': 'intrusion', 'detect_door': 'door_state', 'detect_face': 'face_dwell',
    'detect_human': 'person_dwell', 'detect_phone': 'phone_detection',
    'recognize_face': 'face_recognition', 'detect_logistics_single_person': 'logistics_channel',
}}
assert set(packages) == expected
for name, package in packages.items():
    spec = specs[name]
    assert importlib.import_module(f'AiVision.features.{{package}}.spec').SPEC is spec
    assert Base.metadata.tables[spec.orm_class.__tablename__] is spec.orm_class.__table__
assert all_specs() == specs
assert specs[SPEC.name] is SPEC
assert {{name for name in Base.metadata.tables if name.startswith('ai_logistics_channel')}} == {{
    'ai_logistics_channel', 'ai_logistics_channel_camera',
}}
assert SPEC.orm_class.__tablename__ in Base.metadata.tables
'''
    result = subprocess.run([sys.executable, '-c', script], env=os.environ.copy(), capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert '加载 features.' not in result.stderr


@pytest.fixture
def member_api(service_db):
    from AiVision.api.routes import logistics_channels as api
    camera_ids = [_seed_camera(service_db, f"roi-camera-{index}", department="general_electric") for index in range(2)]
    channel = service_db.service.create_channel(SPEC.name, "roi-channel", "general_electric")
    for camera_id in camera_ids:
        service_db.service.add_existing_camera(SPEC.name, channel["id"], camera_id)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_admin] = lambda: {"role": "admin"}
    app.dependency_overrides[api.get_current_user] = lambda: {"role": "admin"}
    app.dependency_overrides[api.get_logistics_channel_service] = lambda: service_db.service
    path = f"/api/logistics-channels/{SPEC.name}/{channel['id']}"
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, app=app, path=f"{path}/cameras/{camera_ids[0]}/roi",
                              other_path=f"{path}/cameras/{camera_ids[1]}/roi", channel_path=path,
                              factory=service_db.factory, camera_id=camera_ids[0], channel_id=channel["id"],
                              service=service_db.service)


def test_roi_and_channel_roundtrip_have_disjoint_parameter_ownership(member_api):
    api = member_api
    initial = api.client.get(api.path).json()
    assert set(initial) == {"camera", "roi_pos"}
    other = api.client.get(api.other_path).json()
    roi = {"roi_pos": [[.1, .1], [.8, .1], [.8, .8]]}
    response = api.client.put(api.path, json=roi)
    assert response.status_code == 200, response.text
    assert response.json() == api.client.get(api.path).json() == {**initial, **roi}
    assert api.client.get(api.other_path).json() == other
    channel = api.client.get(api.channel_path).json()["config"]
    channel.update(model_iou_threshold=0., min_box_area=9, min_aspect_ratio=.2, max_aspect_ratio=2., cap_interval=.01)
    response = api.client.patch(api.channel_path, json={"config": channel})
    assert response.status_code == 200, response.text
    assert response.json()["config"] == channel
    assert api.client.get(api.path).json()["roi_pos"] == roi["roi_pos"]
    with api.factory() as session:
        row = session.query(SPEC.orm_class).filter_by(camera_id=api.camera_id).one()
        runtime = ConfigCache._validated_function_dict(row, SPEC)
        assert runtime["roi_pos"] == roi["roi_pos"]
        assert not {"IOU_THR", "MIN_BOX_AREA", "ASPECT_RATIO_RANGE", "cap_interval", "alarm_interval", "horn_id"}.intersection(runtime)
        assert row.enable is True
    assert set(SPEC.orm_class.__table__.columns.keys()) == {"id", "camera_id", "enable", "roi_pos", "created_at", "updated_at"}
    assert set(LogisticsSinglePersonConfigSchema().value.model_dump()) == {"roi_pos"}


@pytest.mark.parametrize("field,value", [("IOU_THR", .3), ("MIN_BOX_AREA", 1), ("ASPECT_RATIO_RANGE", [0, 2]),
    ("cap_interval", .2), ("confidence_threshold", .4), ("model_iou_threshold", .4),
    ("min_box_area", 4), ("min_aspect_ratio", .2), ("max_aspect_ratio", 2.), ("enable", False), ("value", {}), ("alarm", {})])
def test_roi_api_rejects_all_policy_and_lifecycle_fields(member_api, field, value):
    before = member_api.client.get(member_api.path).json()
    response = member_api.client.put(member_api.path, json={"roi_pos": [], field: value})
    assert response.status_code == 422, response.text
    assert member_api.client.get(member_api.path).json() == before


@pytest.mark.parametrize("field,value", [("model_iou_threshold", -1), ("model_iou_threshold", 1.1),
    ("min_box_area", .5), ("min_box_area", -1), ("min_box_area", True),
    ("min_aspect_ratio", -1), ("max_aspect_ratio", float('inf')), ("cap_interval", 0)])
def test_invalid_channel_detection_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        LogisticsChannelConfigUpdate(**{field: value})


def test_roi_save_preserves_disabled_member_and_internal_feature_binding(member_api):
    api = member_api
    api.service.set_member_enabled(SPEC.name, api.channel_id, api.camera_id, False)
    assert api.client.put(api.path, json={"roi_pos": []}).status_code == 200
    with api.factory() as session:
        assert session.query(SPEC.orm_class).filter_by(camera_id=api.camera_id).one().enable is True
    channel = api.service.get_channel(SPEC.name, api.channel_id)
    assert channel["members"][0]["enabled"] is False
    assert channel["members"][1]["enabled"] is True


def test_removed_config_api_has_no_alias_and_generic_feature_api_cannot_mutate_lifecycle(member_api):
    from AiVision.api.routes.features import create_features_router
    from AiVision.features._shared.config_manager import FeatureConfigManager
    api = member_api
    api.app.include_router(create_features_router(FeatureConfigManager()))
    for method in ("get", "put"):
        assert api.client.request(method, api.path.removesuffix("/roi") + "/config", json={}).status_code == 404
        assert api.client.request(method, f"/api/features/{SPEC.name}/configs/{api.camera_id}", json={}).status_code == 404
    with pytest.raises(ValueError, match="生命周期"):
        FeatureConfigManager().save_config(SPEC, str(api.camera_id), {"enable": False, "value": {"roi_pos": []}})


def test_roi_save_rechecks_membership_and_never_changes_another_channel(member_api):
    api = member_api
    api.service.remove_camera(SPEC.name, api.channel_id, api.camera_id)
    before = api.client.get(api.other_path).json()
    assert api.client.put(api.path, json={"roi_pos": [[0., 0.], [1., 0.], [1., 1.]]}).status_code == 404
    assert api.client.get(api.other_path).json() == before


def test_model_receives_all_detection_values_from_runtime():
    from dataclasses import replace
    runtime = RuntimeSpy(confidence_threshold=0.)
    runtime.detection = replace(runtime.detection, model_iou_threshold=.87, min_box_area=99, cap_interval=.07)
    consumer = build_consumer(SPEC.consumer_cls, runtime=runtime)
    consumer.dispatch_inference_sync = Mock(return_value={"status": "ok", "detections": []})
    consumer._process(np.zeros((10, 10, 3)), 7)
    assert consumer.dispatch_inference_sync.call_args.kwargs["task_meta"] == {"conf": 0., "iou": .87}
    assert consumer._processing_interval_seconds(7, consumer.config_cache[7]) == .07
    runtime.detection = None
    assert consumer._process(np.zeros((10, 10, 3)), 7)[1]["reason"] == "unknown"
    assert consumer._processing_interval_seconds(7, {}) is None
    assert consumer.dispatch_inference_sync.call_count == 1


@pytest.mark.parametrize("result", [{}, {"status": "ok"}, {"status": "ok", "detections": None}, {"status": "error", "detections": []}])
def test_incomplete_inference_result_is_unknown(result):
    consumer = build_consumer(SPEC.consumer_cls)
    consumer.dispatch_inference_sync = Mock(return_value=result)
    assert consumer._process(np.zeros((10, 10, 3)), 7)[1]["person_count"] is None


def test_partial_channel_update_validates_against_retained_fields_before_commit(service_db):
    from datetime import time
    channel = service_db.service.create_channel(SPEC.name, 'times', 'general_electric')
    service_db.service.update_channel_and_config(SPEC.name, channel['id'], {},
        {'detection_start': time(7), 'detection_end': time(9)})
    with pytest.raises(ValueError):
        service_db.service.update_channel_and_config(SPEC.name, channel['id'], {'name': 'must-rollback'},
            {'detection_start': time(10)})
    saved = service_db.service.get_channel(SPEC.name, channel['id'])
    assert saved['name'] == 'times'
    assert saved['config']['detection_start'] == time(7)


def test_partial_aspect_update_validates_against_channel_values_and_rolls_back(member_api):
    api = member_api
    response = api.client.patch(api.channel_path, json={"config": {"min_aspect_ratio": 2., "max_aspect_ratio": 4.}})
    assert response.status_code == 200
    before = response.json()["config"]
    for payload in ({"max_aspect_ratio": 1.}, {"min_aspect_ratio": 5.}):
        assert api.client.patch(api.channel_path, json={"config": payload}).status_code == 400
        assert api.client.get(api.channel_path).json()["config"] == before
    response = api.client.patch(api.channel_path, json={"config": {"max_aspect_ratio": 3.}})
    assert response.status_code == 200
    assert response.json()["config"]["min_aspect_ratio"] == 2.


@pytest.mark.parametrize("field,value", [("IOU_THR", .3), ("MIN_BOX_AREA", 2), ("ASPECT_RATIO_RANGE", [0, 10])])
def test_channel_api_rejects_removed_camera_parameter_names(member_api, field, value):
    before = member_api.client.get(member_api.channel_path).json()["config"]
    assert member_api.client.patch(member_api.channel_path, json={"config": {field: value}}).status_code == 422
    assert member_api.client.get(member_api.channel_path).json()["config"] == before
