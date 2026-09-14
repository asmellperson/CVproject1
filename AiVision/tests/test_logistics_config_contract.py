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

from AiVision.core import db
from AiVision.core.cache import ConfigCache
from AiVision.features._base import config_manager
from AiVision.features.detect_logistics_single_person import SPEC
from AiVision.features.detect_logistics_single_person.schema import LogisticsSinglePersonConfigSchema, LogisticsChannelConfigUpdate
from AiVision.tests.test_logistics_channel_service import service_db as service_db, _seed_camera
from AiVision.tests.test_logistics_single_person import build_consumer, RuntimeSpy


@pytest.mark.parametrize('entry', [
    'AiVision.features', 'AiVision.features.detect_logistics_single_person.service',
    'AiVision.features.detect_logistics_single_person.runtime',
    'AiVision.platform.camera.config_manager', 'AiVision.platform.orchestrator',
])
def test_fresh_process_imports_register_all_features_once(entry):
    script = f'''import importlib, sys
importlib.import_module({entry!r})
from AiVision.features import all_specs
from AiVision.core.db import Base
from AiVision.features.detect_logistics_single_person import SPEC
assert len(all_specs()) == 8
assert all_specs()[SPEC.name] is SPEC
assert len([name for name in Base.metadata.tables if name.startswith('ai_logistics_channel')]) == 2
assert SPEC.orm_class.__tablename__ in Base.metadata.tables
'''
    result = subprocess.run([sys.executable, '-c', script], env=os.environ.copy(), capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert '加载 features.' not in result.stderr


@pytest.fixture
def member_api(service_db, monkeypatch):
    from AiVision.api import logistics_channels as api
    monkeypatch.setattr(db, 'get_session', service_db.factory)
    monkeypatch.setattr(config_manager, 'get_session', service_db.factory)
    monkeypatch.setattr(config_manager, 'config_cache', Mock())
    monkeypatch.setattr(config_manager, 'config_event_bus', Mock())
    camera_id = _seed_camera(service_db, 'config-camera', department='general_electric')
    channel = service_db.service.create_channel(SPEC.name, 'config-channel', 'general_electric')
    service_db.service.add_existing_camera(SPEC.name, channel['id'], camera_id)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_admin] = lambda: {'role': 'admin'}
    app.dependency_overrides[api.get_current_user] = lambda: {'role': 'admin'}
    app.dependency_overrides[api.get_logistics_channel_service] = lambda: service_db.service
    app.dependency_overrides[api.get_feature_config_manager] = config_manager.FeatureConfigManager
    path = f"/api/logistics-channels/{SPEC.name}/{channel['id']}"
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, path=f'{path}/cameras/{camera_id}/config', channel_path=path,
                              factory=service_db.factory, camera_id=camera_id)


def test_camera_and_channel_roundtrip_have_disjoint_parameter_ownership(member_api):
    api = member_api
    camera = api.client.get(api.path).json()['config']
    assert set(camera) == {'enable', 'value'}
    assert set(camera['value']) == {'roi_pos', 'IOU_THR', 'MIN_BOX_AREA', 'ASPECT_RATIO_RANGE', 'cap_interval'}
    camera['value'].update(IOU_THR=0., MIN_BOX_AREA=9, ASPECT_RATIO_RANGE=[0., 2.], cap_interval=.01,
                           roi_pos=[[.1,.1],[.8,.1],[.8,.8]])
    response = api.client.put(api.path, json=camera)
    assert response.status_code == 200, response.text
    assert response.json()['config'] == api.client.get(api.path).json()['config'] == camera
    channel = api.client.get(api.channel_path).json()['config']
    channel.update(confidence_threshold=0., empty_grace_seconds=0., multi_grace_seconds=0.)
    channel['alarm']['sql_enable'] = True
    response = api.client.patch(api.channel_path, json={'config': channel})
    assert response.status_code == 200, response.text
    assert response.json()['config'] == channel
    assert api.client.get(api.path).json()['config'] == camera
    with api.factory() as session:
        row = session.query(SPEC.orm_class).filter_by(camera_id=api.camera_id).one()
        runtime = ConfigCache._validated_function_dict(row, SPEC)
        assert runtime['IOU_THR'] == 0.
        assert 'CONF_THRESHOLD' not in runtime and 'alarm_interval' not in runtime and 'horn_id' not in runtime
    assert config_manager.config_event_bus.publish.call_count >= 1


@pytest.mark.parametrize('payload', [
    {'alarm': {}}, {'value': {'CONF_THRESHOLD': .3}}, {'value': {'empty_grace_seconds': 2}},
    {'value': {'multi_grace_seconds': 1}}, {'value': {'alarm_interval': 5}},
    {'value': {'detection_start': '08:00'}}, {'value': {'DEDUP_IOU_THRESHOLD': .3}},
    {'value': {'sql_enable': False}}, {'unknown': None},
])
def test_member_camera_api_rejects_removed_or_unknown_fields(member_api, payload):
    before = member_api.client.get(member_api.path).json()
    assert member_api.client.put(member_api.path, json=payload).status_code == 400
    assert member_api.client.get(member_api.path).json() == before


@pytest.mark.parametrize('field,value', [
    ('IOU_THR', -1), ('IOU_THR', 1.1), ('IOU_THR', None), ('IOU_THR', '0.3'),
    ('MIN_BOX_AREA', .5), ('MIN_BOX_AREA', -1), ('MIN_BOX_AREA', True),
    ('ASPECT_RATIO_RANGE', [1]), ('ASPECT_RATIO_RANGE', [3, 1]), ('ASPECT_RATIO_RANGE', [-1, 1]),
    ('cap_interval', 0), ('cap_interval', float('inf')),
])
def test_invalid_camera_values_fail_without_runtime_conversion(field, value):
    with pytest.raises(ValidationError):
        LogisticsSinglePersonConfigSchema(value={field: value})


def test_model_receives_channel_confidence_and_camera_iou_independently():
    runtime = RuntimeSpy(confidence_threshold=0.)
    consumer = build_consumer(SPEC.consumer_cls, runtime=runtime)
    consumer.config_cache[7]['IOU_THR'] = .87
    consumer.dispatch_inference_sync = Mock(return_value={'status': 'ok', 'detections': []})
    consumer._process(np.zeros((10,10,3)), 7)
    assert consumer.dispatch_inference_sync.call_args.kwargs['task_meta'] == {'conf': 0., 'iou': .87}
    runtime.confidence_threshold = None
    assert consumer._process(np.zeros((10,10,3)), 7)[1]['reason'] == 'unknown'
    assert consumer.dispatch_inference_sync.call_count == 1


def test_channel_rejects_camera_parameters():
    for name, value in LogisticsSinglePersonConfigSchema().value.model_dump().items():
        with pytest.raises(ValidationError):
            LogisticsChannelConfigUpdate(**{name: value})


@pytest.mark.parametrize('result', [{}, {'status': 'ok'}, {'status': 'ok', 'detections': None}, {'status': 'error', 'detections': []}])
def test_incomplete_inference_result_is_unknown(result):
    consumer = build_consumer(SPEC.consumer_cls)
    consumer.dispatch_inference_sync = Mock(return_value=result)
    assert consumer._process(np.zeros((10,10,3)), 7)[1]['person_count'] is None


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
