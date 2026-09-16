"""已有摄像头启用普通 Feature 的部门校验及事务、缓存、告警回归。"""
from types import SimpleNamespace
from AiVision.departments.department_registry import DEPARTMENT_SPECS

import numpy as np
import pytest
from sqlalchemy.exc import OperationalError

from AiVision.api.routes.cameras import router as camera_router
from AiVision.api.deps import get_camera_config_manager
from AiVision.api.routes.features import create_features_router
from AiVision.core.cache import ConfigCache
from AiVision.features.registry import all_specs, get_spec
from AiVision.features._shared.config_manager import FeatureConfigManager
from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.cameras.config_manager import CameraConfigManager
from AiVision.cameras.orm import AiCameraConfig
from AiVision.features.logistics_channel.constants import LOGISTICS_FEATURES
from test_horn_backend import backend as backend


ORDINARY_FEATURES = [spec for spec in all_specs().values() if spec.name not in LOGISTICS_FEATURES]


@pytest.fixture
def department_api(backend, monkeypatch):
    import AiVision.core.cache as cache_module
    import AiVision.features._shared.config_manager as feature_module
    import AiVision.cameras.config_manager as camera_module

    cache = ConfigCache()
    observations = []
    real_reload = cache.reload

    def reload():
        real_reload()
        observations.append("reload")

    def publish(event):
        # 热更新触发时，用独立连接确认事务已提交，缓存也已同步。
        with backend.factory() as session:
            camera = session.get(AiCameraConfig, event.camera_id)
            assert cache.get_camera_config(camera.id)["department"] == camera.department
            for spec in all_specs().values():
                cfg = session.query(spec.orm_class).filter_by(camera_id=camera.id).first()
                cached = cache.get_function_config(camera.id, spec.name)
                if cfg is not None and cached is not None:
                    assert cached["enable"] == cfg.enable
                    assert cached["department"] == camera.department
        observations.append(event.change_type)

    monkeypatch.setattr(cache_module, "get_session", backend.factory)
    monkeypatch.setattr(cache, "reload", reload)
    for module in (feature_module, camera_module):
        monkeypatch.setattr(module, "get_session", backend.factory)
        monkeypatch.setattr(module, "config_cache", cache)
        monkeypatch.setattr(module, "config_event_bus", SimpleNamespace(publish=publish))
    manager = CameraConfigManager()
    backend.app.include_router(camera_router)
    backend.app.include_router(create_features_router(FeatureConfigManager(), manager))
    backend.app.dependency_overrides[get_camera_config_manager] = lambda: manager
    backend.cache = cache
    backend.observations = observations
    return backend


def create_camera(api, **changes):
    response = api.client.post("/api/cameras", json={
        "department": "general_electric", "name": "测试摄像头", "shm_name": "test_camera", "url": "rtsp://test.local/video",
        **changes,
    })
    assert response.status_code == 201, response.text
    api.observations.clear()
    return response.json()


def save(api, feature, enabled, camera="test_camera", **payload):
    return api.client.put(f"/api/features/{feature}/configs/{camera}", json={"enable": enabled, **payload})


@pytest.mark.parametrize("threshold", [0.0, 0.35, 1.0])
def test_recognize_face_detection_threshold_is_persisted_per_camera(department_api, threshold):
    api = department_api
    camera = create_camera(api, department="electronics_electrician")
    create_camera(api, name="另一台识别摄像头", shm_name="other_camera", department="electronics_electrician")
    path = "/api/features/recognize_face/configs/test_camera"
    initial = api.client.get(path)
    assert initial.status_code == 200
    payload = initial.json()["config"]
    expected = dict(payload["value"], detection_threshold=threshold)
    assert payload["value"]["detection_threshold"] == 0.5
    payload["value"]["detection_threshold"] = threshold
    saved = api.client.put(path, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["config"]["value"] == expected
    assert api.client.get(path).json()["config"]["value"] == expected
    assert api.client.get("/api/features/recognize_face/configs/other_camera").json()["config"]["value"]["detection_threshold"] == 0.5
    with api.factory() as session:
        stored = session.query(get_spec("recognize_face").orm_class).filter_by(camera_id=camera["camera_id"]).one()
        assert stored.detection_threshold == threshold
    cached = api.cache.get_function_config(camera["camera_id"], "recognize_face")
    assert cached["detection_threshold"] == threshold
    for invalid in (-0.1, 1.1):
        payload["value"]["detection_threshold"] = invalid
        assert api.client.put(path, json=payload).status_code == 400
        assert api.client.get(path).json()["config"]["value"] == expected


@pytest.mark.parametrize("department", [None, "", "ge", "通用电气", "general-electric"])
def test_camera_creation_requires_formal_department(department_api, department):
    response = department_api.client.post("/api/cameras", json={
        "name": "未分配摄像头", "shm_name": "unassigned", "url": "rtsp://test.local/video",
        "department": department,
    })
    assert response.status_code in {400, 422}
    assert department_api.observations == []



@pytest.mark.parametrize("spec", list(all_specs().values()), ids=lambda spec: spec.name)
@pytest.mark.parametrize("department", [None, "", "unknown"])
@pytest.mark.parametrize("missing_config", [False, True])
def test_enable_requires_registered_camera_department_without_writes(department_api, spec, department, missing_config):
    api = department_api
    camera = create_camera(api)
    with api.factory.begin() as session:
        session.get(AiCameraConfig, camera["camera_id"]).department = department
        if missing_config:
            session.query(spec.orm_class).filter_by(camera_id=camera["camera_id"]).delete()
    response = save(api, spec.name, True)
    assert response.status_code == 400
    assert response.json()["detail"] == "摄像头必须先设置所属事业部/子公司"
    assert api.observations == []
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department == department
        cfg = session.query(spec.orm_class).filter_by(camera_id=camera["camera_id"]).first()
        assert cfg is None if missing_config else cfg.enable is False


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_explicit_camera_department_then_enable_multi_department_feature(department_api, department):
    api = department_api
    camera = create_camera(api)
    other = create_camera(api, name="另一台摄像头", shm_name="other_camera")
    response = api.client.patch(f"/api/cameras/{camera['id']}", json={"department": department})
    assert response.status_code == 200, response.text
    assert save(api, "detect_phone", True).status_code == 200
    assert save(api, "detect_phone", False).status_code == 200
    assert save(api, "detect_phone", True).status_code == 200
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department == department
        assert session.get(AiCameraConfig, other["camera_id"]).department == "general_electric"
        assert session.query(get_spec("detect_phone").orm_class).filter_by(camera_id=other["camera_id"]).one().enable is False


@pytest.mark.parametrize("spec", ORDINARY_FEATURES, ids=lambda spec: spec.name)
@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_every_feature_uses_camera_department_without_changing_it(department_api, spec, department, monkeypatch):
    api = department_api
    camera = create_camera(api, department=department)
    response = save(api, spec.name, True)
    assert response.status_code == 200, response.text
    assert api.observations == ["reload", f"{spec.name}_config_updated", f"{spec.name}_enabled"]
    cfg = api.cache.get_function_config(camera["camera_id"], spec.name)
    assert cfg["department"] == department
    import AiVision.features._shared.consumer as consumer_module
    requests = []
    monkeypatch.setattr(consumer_module.alarm_dispatcher, "maybe_dispatch", lambda req, **_: requests.append(req))
    consumer = SimpleNamespace(feature_name=spec.name, spec=spec, frame_cache={},
        config_cache={camera["camera_id"]: cfg}, _should_alarm=lambda *_: True, _alarm_context=lambda *_: {})
    BaseFunctionConsumer._handle_alarm(consumer, camera["camera_id"], [], np.zeros((4, 4, 3), np.uint8))
    assert len(requests) == 1
    assert (requests[0].department, requests[0].feature_name) == (department, spec.name)
    assert save(api, spec.name, False).status_code == 200
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department == department


def test_enable_is_rolled_back_on_other_validation_or_commit_failure(department_api, monkeypatch):
    api = department_api
    camera = create_camera(api, department="haoda_company")
    response = save(api, "detect_face", True, alarm={"horn": {"enable": True}})
    assert response.status_code == 400
    assert "喇叭" in response.json()["detail"]

    def fail_commit(_session):
        raise OperationalError("test commit", {}, RuntimeError("test failure"))

    with monkeypatch.context() as patch:
        patch.setattr(api.factory.class_, "commit", fail_commit)
        with pytest.raises(OperationalError):
            save(api, "detect_face", True)
    assert api.observations == []
    assert api.cache.get_camera_config(camera["camera_id"])["department"] == "haoda_company"
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department == "haoda_company"
        assert session.query(get_spec("detect_face").orm_class).filter_by(camera_id=camera["camera_id"]).one().enable is False


@pytest.mark.parametrize("enabled", [False, True])
def test_enabled_unassigned_camera_must_be_assigned_before_saving_enabled(department_api, enabled):
    api = department_api
    camera = create_camera(api)
    with api.factory.begin() as session:
        session.get(AiCameraConfig, camera["camera_id"]).department = None
        session.query(get_spec("detect_phone").orm_class).filter_by(camera_id=camera["camera_id"]).one().enable = True
    assert save(api, "detect_phone", enabled).status_code == (400 if enabled else 200)
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department is None
    if not enabled:
        assert save(api, "detect_phone", True).status_code == 400


def test_explicit_department_is_reused_and_cannot_be_overwritten_by_next_feature(department_api):
    api = department_api
    camera = create_camera(api, department="general_electric")
    assert save(api, "detect_human", True).status_code == 200
    assert save(api, "detect_phone", True).status_code == 200
    assert save(api, "detect_face", True).status_code == 200
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department == "general_electric"


def test_enable_rechecks_department_after_camera_lookup(department_api, monkeypatch):
    api = department_api
    camera = create_camera(api)
    with api.factory.begin() as session:
        session.get(AiCameraConfig, camera["camera_id"]).department = None
    original_lookup = FeatureConfigManager._get_camera_by_key

    def lookup_then_update(session, key):
        row = original_lookup(session, key)
        # 模拟首次查到空部门后，另一个请求已经提交了部门选择。
        with api.factory.begin() as other_session:
            other_session.get(AiCameraConfig, camera["camera_id"]).department = "general_electric"
        return row

    monkeypatch.setattr(FeatureConfigManager, "_get_camera_by_key", staticmethod(lookup_then_update))
    response = save(api, "detect_face", True)
    assert response.status_code == 200
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department == "general_electric"
        assert session.query(get_spec("detect_face").orm_class).filter_by(camera_id=camera["camera_id"]).one().enable is True
