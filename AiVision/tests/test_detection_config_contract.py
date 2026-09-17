"""最终配置契约、真实 API/SQLite 持久化和模拟推理行为。"""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from AiVision.core import db
from AiVision.core.cache import ConfigCache
from AiVision.features.registry import all_specs, get_spec
from AiVision.features.logistics_channel.constants import LOGISTICS_FEATURES
from AiVision.features._shared import config_manager
from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.cameras.orm import AiCameraConfig


@pytest.fixture
def api(monkeypatch):
    from auth.auth import get_current_user, require_admin
    from AiVision.api.routes.features import create_features_router
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "get_session", factory)
    monkeypatch.setattr(config_manager, "get_session", factory)
    monkeypatch.setattr(config_manager, "config_cache", Mock())
    monkeypatch.setattr(config_manager, "config_event_bus", Mock())
    with factory.begin() as session:
        session.add(AiCameraConfig(id=1, name="测试", shm_name="test", url="test-source"))
    app = FastAPI()
    app.include_router(create_features_router(config_manager.FeatureConfigManager()))
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, factory=factory)
    engine.dispose()


@pytest.mark.parametrize("feature", [name for name in all_specs() if name not in LOGISTICS_FEATURES])
def test_defaults_read_save_echo_and_cache(api, feature):
    spec = get_spec(feature)
    path = f"/api/features/{feature}/configs/test"
    expected = spec.config_schema().model_dump()
    assert api.client.get(f"/api/features/{feature}").json()["default_config"] == expected
    assert api.client.get(path).json()["config"] == expected
    response = api.client.put(path, json={})
    assert response.status_code == 200, response.text
    assert response.json()["config"] == expected
    assert api.client.get(path).json()["config"] == expected
    with api.factory() as session:
        row = session.query(spec.orm_class).one()
        runtime = ConfigCache._validated_function_dict(row, spec)
        for key, value in expected["value"].items():
            assert runtime[key] == value


def test_feature_metadata_preserves_single_alarm_response(api):
    response = api.client.get("/api/features")
    assert response.status_code == 200
    expected_types = {"blocks": 1, "detect_door": 2, "detect_phone": 3, "detect_face": 4,
                      "detect_human": 5, "detect_logistics_single_person": 6, "recognize_face": 7}
    for meta in response.json()["features"]:
        assert meta["violation_type"] == expected_types[meta["name"]]
        assert set(meta) == {"name", "display_name", "required_models", "violation_type", "default_config", "config_schema"}
        assert api.client.get(f"/api/features/{meta['name']}").json() == meta


@pytest.mark.parametrize("feature", list(all_specs()))
def test_orm_defaults_match_complete_schema_defaults(api, feature):
    spec = get_spec(feature)
    with api.factory.begin() as session:
        row = spec.orm_class(camera_id=1)
        session.add(row)
        session.flush()
        assert row.to_value_dict() == spec.config_schema().value.model_dump()


def test_database_invalid_values_fail_at_cache_entry(api):
    spec = get_spec("detect_face")
    row = spec.orm_class(camera_id=1, **spec.config_schema().value.model_dump())
    row.enable = row.sql_enable = row.horn_enable = row.wechat_enable = False
    row.MAX_TIME = None
    with pytest.raises(ValidationError):
        ConfigCache._validated_function_dict(row, spec)


REMOVED = [
    ("detect_face", "YAW_THRESHOLD"), ("detect_face", "IOU_THR"),
    ("detect_human", "IOU_THR"),
    ("detect_door", "blur_kernel"), ("blocks", "blur_kernel"),
    ("blocks", "diff_threshold"), ("blocks", "diff_threshold_env"), ("blocks", "env_threshold"),
]


@pytest.mark.parametrize("feature,field", REMOVED)
def test_removed_fields_rejected_without_write(api, feature, field):
    path = f"/api/features/{feature}/configs/test"
    before = api.client.get(path).json()["config"]
    assert api.client.put(path, json={"value": {field: 0}}).status_code == 400
    assert api.client.get(path).json()["config"] == before


@pytest.mark.parametrize("payload", [
    {"unknown": 1}, {"value": {"unknown": 1}}, {"alarm": {"unknown": {}}},
    {"alarm": {"sql": {"unknown": 1}}}, {"alarm": {"sql": {"parm": {"unknown": 1}}}},
    {"alarm": {"horn": {"parm": {"unknown": 1}}}},
    {"alarm": {"wechat": {"parm": {"unknown": 1}}}},
])
@pytest.mark.parametrize("feature", list(all_specs()))
def test_undefined_fields_at_every_level(feature, payload):
    with pytest.raises(ValidationError):
        get_spec(feature).config_schema.model_validate(payload)


@pytest.mark.parametrize("feature,field,minimum", [
    ("detect_face", "MAX_LOST", 0), ("detect_phone", "MIN_CONSECUTIVE_HITS", 1),
    ("detect_human", "MAX_LOST", 0),
])
def test_counts_require_integer(api, feature, field, minimum):
    path = f"/api/features/{feature}/configs/test"
    for valid in [minimum, minimum + 3]:
        response = api.client.put(path, json={"value": {field: valid}})
        assert response.status_code == 200, response.text
        assert response.json()["config"]["value"][field] == valid
    for invalid in [minimum - 1, 2.5, "3", True, None]:
        assert api.client.put(path, json={"value": {field: invalid}}).status_code == 400


@pytest.mark.parametrize("feature,field,nullable", [
    ("detect_door", "threshold", False), ("detect_door", "global_motion_threshold", False),
    ("detect_door", "env_threshold", True), ("blocks", "threshold", False),
] + [(feature, field, False) for feature in ["detect_face", "detect_human"]
     for field in ["DETECTION_IOU_THR", "TRACK_IOU_THR"]])
def test_ratio_boundaries_and_invalid_values(api, feature, field, nullable):
    path = f"/api/features/{feature}/configs/test"
    for valid in [0, 0.4, 1] + ([None] if nullable else []):
        response = api.client.put(path, json={"value": {field: valid}})
        assert response.status_code == 200, response.text
        assert api.client.get(path).json()["config"]["value"][field] == valid
    for invalid in [-0.01, 1.01, "0.5", True] + ([] if nullable else [None]):
        assert api.client.put(path, json={"value": {field: invalid}}).status_code == 400
    with pytest.raises(ValidationError):
        get_spec(feature).config_schema(value={field: float("nan")})


def consumer(feature, **values):
    spec = get_spec(feature)
    instance = spec.consumer_cls(spec=spec, infer_dict={}, result_queue=None,
                                 latest_frames={}, is_camera_active=lambda _: True)
    instance.config_cache[1] = spec.config_schema(value=values).value.model_dump()
    return instance


@pytest.mark.parametrize("feature", ["detect_face", "detect_human"])
def test_independent_iou_hot_update_zero_time_and_visible_tracks(feature):
    instance = consumer(feature, DETECTION_IOU_THR=0.0, TRACK_IOU_THR=1.0, MAX_LOST=0, MAX_TIME=0)
    kind = "face" if feature == "detect_face" else "person"
    instance.dispatch_inference_sync = Mock(return_value={"status": "ok", "detections": [{"type": kind, "bbox": [0, 0, 10, 20], "confidence": .9, "class_id": 0}]})
    roi = np.zeros((20, 20, 3), dtype=np.uint8)
    assert instance._process(roi, 1)[0] is True
    assert instance.dispatch_inference_sync.call_args.kwargs["task_meta"]["iou"] == 0.0
    assert instance._trackers[1].iou_thr == 1.0
    instance.config_cache[1].update(DETECTION_IOU_THR=0.9, TRACK_IOU_THR=0.1)
    assert instance._process(roi, 1)[0] is True
    assert instance.dispatch_inference_sync.call_args.kwargs["task_meta"]["iou"] == 0.9
    assert instance._trackers[1].iou_thr == 0.1
    instance.dispatch_inference_sync.return_value = {"status": "ok", "detections": []}
    assert instance._process(roi, 1)[0] is False
    assert not instance._trackers[1].tracks  # MAX_LOST=0 的第一次丢失立即删除


def test_blocks_zero_is_inference_confidence():
    instance = consumer("blocks", threshold=0)
    instance.dispatch_inference_sync = Mock(return_value={"detections": []})
    instance._process(np.zeros((10, 10, 3), np.uint8), 1)
    assert instance.dispatch_inference_sync.call_args.kwargs["task_meta"] == {"conf": 0.0}


@pytest.mark.parametrize("env,expected", [(None, True), (0, False), (.4, False), (.5, True), (1, True)])
def test_door_nullable_environment_filter(env, expected):
    instance = consumer("detect_door", env_threshold=env, threshold=.5, global_motion_threshold=1,
                        stable_confirm_seconds=0, stable_confirm_hits=1)
    roi = np.zeros((10, 10, 3), np.uint8)
    instance.blur_roi[1] = roi.copy()
    instance._process(roi, 1)
    roi[:5] = 255
    instance.blur_roi[1] = roi
    result = instance._process(roi, 1)
    assert result[0] is expected


def test_door_requires_both_local_thresholds_and_zero_first_alarm():
    instance = consumer("detect_door", threshold=0, min_local_change_ratio=.6,
                        global_motion_threshold=1, stable_confirm_seconds=0, stable_confirm_hits=1,
                        first_alarm=0)
    roi = np.zeros((10, 10, 3), np.uint8)
    instance.blur_roi[1] = roi.copy()
    instance._process(roi, 1)
    roi[:5] = 255
    instance.blur_roi[1] = roi
    assert instance._process(roi, 1)[0] is False
    assert instance._should_alarm(1, (True, {}), instance.config_cache[1]) is True


def test_camera_alarm_features_use_common_schema():
    defaults = AlarmConfigSchema().model_dump()
    for name, spec in all_specs().items():
        if name == "detect_logistics_single_person":
            assert "alarm" not in spec.config_schema.model_fields
            with pytest.raises(ValidationError):
                spec.config_schema(alarm=defaults)
        else:
            assert spec.config_schema.model_fields["alarm"].annotation is AlarmConfigSchema
            assert spec.config_schema().model_dump()["alarm"] == defaults
    first = AlarmConfigSchema()
    first.wechat.parm.user = "changed"
    assert AlarmConfigSchema().wechat.parm.user == ""
