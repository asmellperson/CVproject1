"""已有摄像头启用普通 Feature 的部门校验及事务、缓存、告警回归。"""
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy.exc import OperationalError

from AiVision.api.cameras import router as camera_router
from AiVision.api.deps import get_camera_config_manager
from AiVision.api.features import create_features_router
from AiVision.core.cache import ConfigCache
from AiVision.features import all_specs, get_spec
from AiVision.features._base.config_manager import FeatureConfigManager
from AiVision.features._base.consumer import BaseFunctionConsumer
from AiVision.platform.camera.config_manager import CameraConfigManager
from AiVision.platform.camera.orm import AiCameraConfig
from AiVision.platform.logistics_channel.constants import LOGISTICS_FEATURES
from test_horn_backend import backend


ORDINARY_FEATURES = [spec for spec in all_specs().values() if spec.name not in LOGISTICS_FEATURES]
SINGLE_DEPARTMENT_FEATURES = [spec for spec in ORDINARY_FEATURES if len(spec.departments) == 1]


@pytest.fixture
def department_api(backend, monkeypatch):
    import AiVision.core.cache as cache_module
    import AiVision.features._base.config_manager as feature_module
    import AiVision.platform.camera.config_manager as camera_module

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
        "name": "测试摄像头", "shm_name": "test_camera", "url": "rtsp://test.local/video",
        **changes,
    })
    assert response.status_code == 201, response.text
    api.observations.clear()
    return response.json()


def save(api, feature, enabled, camera="test_camera", **payload):
    return api.client.put(f"/api/features/{feature}/configs/{camera}", json={"enable": enabled, **payload})


@pytest.mark.parametrize("department", [None, ""])
@pytest.mark.parametrize("enabled", [False, True])
def test_camera_creation_and_disabled_feature_saves_allow_empty_department(department_api, department, enabled):
    api = department_api
    camera = create_camera(api, department=department, enabled=enabled)
    assert not any(camera["functions"].values())
    for spec in ORDINARY_FEATURES:
        response = save(api, spec.name, False)
        assert response.status_code == 200, response.text
    with api.factory() as session:
        stored = session.get(AiCameraConfig, camera["camera_id"])
        assert stored.department == department
        assert stored.enable is enabled


@pytest.mark.parametrize("spec", SINGLE_DEPARTMENT_FEATURES, ids=lambda spec: spec.name)
@pytest.mark.parametrize("department", [None, ""])
@pytest.mark.parametrize("missing_config", [False, True])
def test_single_department_enable_commits_autofill_before_cache_and_events(
    department_api, spec, department, missing_config, monkeypatch,
):
    api = department_api
    camera = create_camera(api, department=department)
    if missing_config:
        with api.factory.begin() as session:
            session.query(spec.orm_class).filter_by(camera_id=camera["camera_id"]).delete()
    response = save(api, spec.name, True)
    assert response.status_code == 200, response.text
    assert response.json()["config"]["enable"] is True
    assert api.observations == ["reload", f"{spec.name}_config_updated", f"{spec.name}_enabled"]
    cfg = api.cache.get_function_config(camera["camera_id"], spec.name)
    assert cfg["department"] == spec.departments[0]

    # 无报警能力的 Feature 只验证部门提交和运行时配置，不伪造报警结果。
    if spec.violation_type == 0:
        assert cfg["sql_enable"] is False
        return

    import AiVision.features._base.consumer as consumer_module
    requests = []
    monkeypatch.setattr(consumer_module.alarm_dispatcher, "maybe_dispatch", lambda req, **_: requests.append(req))
    consumer = SimpleNamespace(feature_name=spec.name, spec=spec, frame_cache={},
        config_cache={camera["camera_id"]: cfg}, _should_alarm=lambda *_: True)
    BaseFunctionConsumer._handle_alarm(consumer, camera["camera_id"], [], np.zeros((4, 4, 3), np.uint8))
    assert len(requests) == 1
    assert (requests[0].department, requests[0].feature_name, requests[0].violation_type) == (
        spec.departments[0], spec.name, spec.violation_type,
    )


@pytest.mark.parametrize("department", [None, ""])
@pytest.mark.parametrize("missing_config", [False, True])
def test_multi_department_requires_explicit_choice_without_writes(department_api, department, missing_config):
    api = department_api
    camera = create_camera(api, department=department)
    spec = get_spec("detect_phone")
    if missing_config:
        with api.factory.begin() as session:
            session.query(spec.orm_class).filter_by(camera_id=camera["camera_id"]).delete()
    response = save(api, spec.name, True)
    assert response.status_code == 400
    assert "请先明确选择摄像头所属部门" in response.json()["detail"]
    assert api.observations == []
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department == department
        cfg = session.query(spec.orm_class).filter_by(camera_id=camera["camera_id"]).first()
        if missing_config:
            assert cfg is None
        else:
            assert cfg.enable is False


@pytest.mark.parametrize("department", get_spec("detect_phone").departments)
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
        assert session.get(AiCameraConfig, other["camera_id"]).department is None
        assert session.query(get_spec("detect_phone").orm_class).filter_by(camera_id=other["camera_id"]).one().enable is False


@pytest.mark.parametrize("spec", ORDINARY_FEATURES, ids=lambda spec: spec.name)
def test_mismatched_department_rejects_enable_but_allows_disabled_save(department_api, spec):
    api = department_api
    department = "general_electric" if spec.name == "detect_human_haoda" else "haoda_company"
    camera = create_camera(api, department=department)
    response = save(api, spec.name, True)
    assert response.status_code == 400
    assert "department 必须属于当前功能" in response.json()["detail"]
    assert api.observations == []
    assert save(api, spec.name, False).status_code == 200
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department == department
        assert session.query(spec.orm_class).filter_by(camera_id=camera["camera_id"]).one().enable is False


def test_autofill_is_rolled_back_on_other_validation_or_commit_failure(department_api, monkeypatch):
    api = department_api
    camera = create_camera(api)
    response = save(api, "detect_human", True, alarm={"horn": {"enable": True}})
    assert response.status_code == 400
    assert "喇叭" in response.json()["detail"]

    def fail_commit(_session):
        raise OperationalError("test commit", {}, RuntimeError("test failure"))

    with monkeypatch.context() as patch:
        patch.setattr(api.factory.class_, "commit", fail_commit)
        with pytest.raises(OperationalError):
            save(api, "detect_human", True)
    assert api.observations == []
    assert api.cache.get_camera_config(camera["camera_id"])["department"] is None
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department is None
        assert session.query(get_spec("detect_human").orm_class).filter_by(camera_id=camera["camera_id"]).one().enable is False


@pytest.mark.parametrize("enabled", [False, True])
def test_existing_enabled_legacy_config_can_be_saved_or_disabled_without_guessing(department_api, enabled):
    api = department_api
    camera = create_camera(api)
    with api.factory.begin() as session:
        session.query(get_spec("detect_phone").orm_class).filter_by(camera_id=camera["camera_id"]).one().enable = True
    assert save(api, "detect_phone", enabled).status_code == 200
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department is None
    if not enabled:
        assert save(api, "detect_phone", True).status_code == 400


def test_autofilled_department_is_reused_and_cannot_be_overwritten_by_next_feature(department_api):
    api = department_api
    camera = create_camera(api)
    assert save(api, "detect_human", True).status_code == 200
    assert save(api, "detect_phone", True).status_code == 200
    assert save(api, "detect_face", True).status_code == 400
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department == "general_electric"


def test_enable_rechecks_department_after_camera_lookup(department_api, monkeypatch):
    api = department_api
    camera = create_camera(api)
    original_lookup = FeatureConfigManager._get_camera_by_key

    def lookup_then_update(session, key):
        row = original_lookup(session, key)
        # 模拟首次查到空部门后，另一个请求已经提交了部门选择。
        with api.factory.begin() as other_session:
            other_session.get(AiCameraConfig, camera["camera_id"]).department = "general_electric"
        return row

    monkeypatch.setattr(FeatureConfigManager, "_get_camera_by_key", staticmethod(lookup_then_update))
    response = save(api, "detect_face", True)
    assert response.status_code == 400
    assert "department 必须属于当前功能" in response.json()["detail"]
    assert api.observations == []
    with api.factory() as session:
        assert session.get(AiCameraConfig, camera["camera_id"]).department == "general_electric"
        assert session.query(get_spec("detect_face").orm_class).filter_by(camera_id=camera["camera_id"]).one().enable is False
