"""检测绑定的真实 API/事务与播放路由回归；不访问现场设备。"""
import logging
from types import SimpleNamespace

import numpy as np
import pytest

from AiVision.api.deps import get_logistics_channel_service
from AiVision.api.features import create_features_router
from AiVision.api.logistics_channels import router as logistics_router
from AiVision.core.alarm.dispatcher import AlarmDispatcher
from AiVision.features import get_spec
from AiVision.features._base.config_manager import FeatureConfigManager
from AiVision.features._base.consumer import BaseFunctionConsumer
from AiVision.platform.camera.orm import AiCameraConfig
from AiVision.platform.logistics_channel.service import LogisticsChannelService
from test_horn_backend import backend, payload
from test_horn_runtime_manager import runtime, config as runtime_config
from test_logistics_channel_runtime import build_runtime, channel, snapshot, FEATURE


@pytest.fixture
def binding_api(backend, monkeypatch):
    import AiVision.features._base.config_manager as feature_module
    import AiVision.platform.logistics_channel.service as channel_module

    cache = SimpleNamespace(reload=lambda: None)
    bus = SimpleNamespace(publish=lambda event: backend.notifications.append(event))
    for module in [feature_module, channel_module]:
        monkeypatch.setattr(module, 'get_session', backend.factory)
        monkeypatch.setattr(module, 'config_cache', cache)
        monkeypatch.setattr(module, 'config_event_bus', bus)
    service = LogisticsChannelService()
    backend.app.include_router(create_features_router(FeatureConfigManager()))
    backend.app.include_router(logistics_router)
    backend.app.dependency_overrides[get_logistics_channel_service] = lambda: service
    with backend.factory() as session:
        session.add_all([AiCameraConfig(name=f'Camera {i}', shm_name=f'cam_{i}', url='rtsp://test.local/video') for i in (1, 2)])
        session.commit()
    backend.horn = backend.service.create_horn(payload(enable=True))['id']
    backend.channel_id = service.create_channel(FEATURE, '通道 A')['id']
    return backend


def alarm(horn_id, task=7, enable=True):
    return {'horn': {'enable': enable, 'parm': {'horn_id': horn_id, 'horn_event_id': task}},
            'sql': {'enable': True, 'parm': {}}, 'wechat': {'enable': True, 'parm': {'user': 'test-user'}}}


def save(client, feature, camera, horn):
    return client.put(f'/api/features/{feature}/configs/{camera}', json={'enable': True, 'alarm': horn})


def test_camera_feature_independence_disable_retains_and_explicit_unbind(binding_api):
    b = binding_api
    for feature, camera, task in [('detect_human', 'cam_1', 7), ('detect_human', 'cam_2', 8), ('detect_phone', 'cam_1', 9)]:
        response = save(b.client, feature, camera, alarm(b.horn, task))
        assert response.status_code == 200, response.text
    response = save(b.client, 'detect_human', 'cam_1', {'horn': {'enable': False}})
    assert response.status_code == 200, response.text
    assert response.json()['config']['alarm']['horn'] == alarm(b.horn, 7, False)['horn']
    for feature, camera, task in [('detect_human', 'cam_2', 8), ('detect_phone', 'cam_1', 9)]:
        data = b.client.get(f'/api/features/{feature}/configs/{camera}').json()
        assert data['config']['alarm']['horn'] == alarm(b.horn, task)['horn']
        assert data['config']['alarm']['wechat']['parm']['user'] == 'test-user'
    assert save(b.client, 'detect_human', 'cam_1', alarm(None, None, False)).status_code == 200
    data = b.client.get('/api/features/detect_human/configs/cam_1').json()
    assert data['config']['alarm']['horn']['parm']['horn_id'] is None


@pytest.mark.parametrize('horn_id,task,enabled', [(None, 7, True), (9999, 7, True), (9999, 7, False),
                                                  ('1', 7, True), (True, 7, True), (1, None, True),
                                                  (1, 0, True), (1, -1, False), (1, 1.2, True),
                                                  (1, True, True), (1, '7', True), (1, 2147483648, True)])
def test_feature_invalid_binding_rejected_without_commit_or_hot_event(binding_api, horn_id, task, enabled):
    b = binding_api
    assert save(b.client, 'detect_human', 'cam_1', alarm(b.horn)).status_code == 200
    before = len(b.notifications)
    response = save(b.client, 'detect_human', 'cam_1', alarm(horn_id, task, enabled))
    assert response.status_code == 400, response.text
    assert len(b.notifications) == before
    assert b.client.get('/api/features/detect_human/configs/cam_1').json()['config']['alarm']['horn'] == alarm(b.horn)['horn']


def test_disabled_device_can_be_retained_but_not_enabled(binding_api):
    b = binding_api
    save(b.client, 'detect_human', 'cam_1', alarm(b.horn))
    b.service.update_horn(b.horn, {'enable': False})
    response = save(b.client, 'detect_human', 'cam_1', alarm(b.horn))
    assert response.status_code == 400 and '已停用' in response.text
    response = save(b.client, 'detect_human', 'cam_1', {'horn': {'enable': False}})
    assert response.status_code == 200
    assert response.json()['config']['alarm']['horn']['parm']['horn_id'] == b.horn


def test_logistics_native_round_trip_disable_and_device_validation(binding_api):
    b = binding_api
    path = f'/api/logistics-channels/{FEATURE}/{b.channel_id}'
    horn = {'enabled': True, 'horn_id': b.horn, 'horn_event_id': 11}
    response = b.client.patch(path, json={'config': {'alarm': {'horn': horn}}})
    assert response.status_code == 200, response.text
    assert b.client.get(path).json()['config']['alarm']['horn'] == horn
    for invalid in [dict(horn, horn_id=9999), dict(horn, horn_event_id=0), dict(horn, horn_event_id=True), dict(horn, horn_event_id=1.5)]:
        response = b.client.patch(path, json={'config': {'alarm': {'horn': invalid}}})
        assert response.status_code in (400, 404, 422), response.text
        assert b.client.get(path).json()['config']['alarm']['horn'] == horn
    b.service.update_horn(b.horn, {'enable': False})
    assert b.client.patch(path, json={'config': {'alarm': {'horn': horn}}}).status_code == 400
    response = b.client.patch(path, json={'config': {'alarm': {'horn': {'enabled': False}}}})
    assert response.status_code == 200, response.text
    assert response.json()['config']['alarm']['horn'] == dict(horn, enabled=False)
    assert b.client.delete(f'/api/horns/{b.horn}').status_code == 409
    response = b.client.patch(path, json={'config': {'alarm': {'horn': dict(horn, enabled=False, horn_id=None)}}})
    assert response.status_code == 200
    assert b.client.delete(f'/api/horns/{b.horn}').status_code == 204


def trigger_feature(dispatcher, monkeypatch, *, horn_id=1, task=7, enabled=True, feature='detect_human', camera_id=1):
    import AiVision.features._base.consumer as consumer_module
    monkeypatch.setattr(consumer_module, 'alarm_dispatcher', dispatcher)
    consumer = SimpleNamespace(config_cache={camera_id: {'horn_enable': enabled, 'horn_id': horn_id,
        'horn_event_id': task, 'sql_enable': True, 'wechat_enable': True, 'wechat_user': 'test-user',
        'shm_name': f'cam_{camera_id}', 'alarm_interval': 0, 'department': get_spec(feature).departments[0]}}, _should_alarm=lambda *args: True,
        feature_name=feature, spec=get_spec(feature), frame_cache={})
    BaseFunctionConsumer._handle_alarm(consumer, camera_id, [{'alarm_flag': True}], np.zeros((8, 8, 3), np.uint8))


def test_real_feature_and_logistics_route_to_shared_horn_without_channel_regression(runtime, monkeypatch):
    runtime.configs[2] = runtime_config(id=2)
    runtime.manager.start()
    dispatcher = AlarmDispatcher()
    dispatcher.horn_runtime_manager = runtime.manager
    records, videos = [], []
    dispatcher.violation_writer = SimpleNamespace(save_now=lambda **kw: records.append(kw) or {'id': 5})
    dispatcher.evidence_recorder = SimpleNamespace(start_alarm=lambda *args: videos.append(args) or 'test-evidence.mp4')
    dispatcher.wechat = object()  # 本测试核对入队，既有微信测试核对真实发送格式。
    trigger_feature(dispatcher, monkeypatch, task=7)
    trigger_feature(dispatcher, monkeypatch, task=8, feature='detect_phone')
    trigger_feature(dispatcher, monkeypatch, horn_id=2, task=9, camera_id=2)
    native = channel()
    native['config']['alarm']['horn'] = {'enabled': True, 'horn_id': 1, 'horn_event_id': 11}
    native['config']['alarm']['wechat'] = {'enabled': True, 'user': 'test-user'}
    logistics, _ = build_runtime([native], dispatcher=dispatcher)
    try:
        logistics.update_camera_snapshot(FEATURE, snapshot(10, 2), np.zeros((10, 20, 3), np.uint8))
        logistics.update_camera_snapshot(FEATURE, snapshot(11, 1), np.zeros((10, 20, 3), np.uint8))
        logistics.evaluate(FEATURE, 3, now=101.0)
        runtime.manager._queue.join()
        assert runtime.manager._entries[1][1].played == [7, 8, 11]
        assert runtime.manager._entries[2][1].played == [9]
        assert len(records) == len(videos) == dispatcher._wechat_queue.qsize() == 4
        assert all(record['video_path'] == 'test-evidence.mp4' for record in records)
        assert records[-1]['subject_type'] == 'logistics_channel'
    finally:
        logistics.stop()


@pytest.mark.parametrize('case', ['off', 'disabled', 'deleted', 'missing', 'no_manager', 'missing_task'])
def test_unavailable_horn_does_not_play_or_block_other_channels(runtime, monkeypatch, caplog, case):
    runtime.manager.start()
    horn = runtime.created[0]
    if case == 'disabled':
        runtime.configs[1]['enable'] = False
        runtime.manager.sync(1)
    elif case == 'deleted':
        del runtime.configs[1]
        runtime.manager.sync(1)
    dispatcher = AlarmDispatcher()
    dispatcher.horn_runtime_manager = None if case == 'no_manager' else runtime.manager
    written, video = [], []
    dispatcher.violation_writer = SimpleNamespace(save_now=lambda **kw: written.append(kw) or {'id': 7})
    dispatcher.evidence_recorder = SimpleNamespace(start_alarm=lambda *args: video.append(args) or 'evidence.mp4')
    dispatcher.wechat = object()
    with caplog.at_level(logging.WARNING):
        trigger_feature(dispatcher, monkeypatch, enabled=case != 'off', horn_id=9999 if case == 'missing' else 1,
                        task=None if case == 'missing_task' else 7)
    runtime.manager._queue.join()
    assert horn.played == []
    assert len(written) == len(video) == dispatcher._wechat_queue.qsize() == 1
    if case != 'off':
        assert '未播放' in caplog.text
