"""同一个人员逗留功能的真实配置、状态、权限及报警隔离。"""
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from auth.auth import get_current_user
from AiVision.api.deps import get_current_orchestrator
from AiVision.api.routes import alarms, runtime
from AiVision.features.registry import all_specs
from AiVision.departments.department_registry import DEPARTMENT_SPECS

DEPARTMENTS = tuple(DEPARTMENT_SPECS)
from AiVision.features.person_dwell.spec import SPEC
from AiVision.features.person_dwell.consumer import HumanConsumer
from AiVision.features.person_dwell.schema import HumanConfigSchema
from AiVision.cameras.config_manager import camera_access_departments
from AiVision.cameras.orm import AiCameraConfig
from AiVision.alarms.records.orm import AiAlarmEvent
from test_feature_department_enable import department_api as department_api, create_camera, save
from test_horn_backend import backend as backend


def test_one_registered_human_feature_supports_all_departments():
    human_specs = [spec for spec in all_specs().values() if spec.consumer_cls is HumanConsumer]
    assert human_specs == [SPEC]
    assert SPEC.name == "detect_human"
    assert SPEC.config_schema is HumanConfigSchema
    assert SPEC.orm_class.__tablename__ == "ai_camera_config_detect_human"
    assert "departments" not in SPEC.__dataclass_fields__


def test_unowned_human_camera_does_not_grant_either_department_access():
    assert camera_access_departments({"department": None, "functions": {"detect_human": True}}) == set()


@pytest.fixture
def human_api(department_api, monkeypatch):
    api = department_api
    api.cameras = []
    for number, department in enumerate(DEPARTMENTS, 1):
        camera = create_camera(api, name=department, shm_name=department, department=department)
        response = save(api, SPEC.name, True, camera=department, value={
            "MAX_TIME": float(number * 10), "cap_interval": 0.2 + number * .1,
            "roi_pos": [[0., 0.], [0.1 + number * .1, 0.], [0.1 + number * .1, .8]],
            "alarm_interval": float(number * 20),
        }, alarm={"sql": {"enable": True}})
        assert response.status_code == 200, response.text
        api.cameras.append(camera)
    status = {
        "started": True, "running_models": ["yolo_human"], "running_consumers": [SPEC.name],
        "running_cameras": list(DEPARTMENTS),
        "inference": {"workers": {"private": "global totals"}, "consumers": {SPEC.name: {
            "totals": {"ok": 33}, "targets": [
                {"camera_id": camera["camera_id"], "counts": {"ok": number * 11}}
                for number, camera in enumerate(api.cameras, 1)
            ],
        }}},
    }
    api.app.include_router(runtime.router)
    api.app.dependency_overrides[get_current_orchestrator] = lambda: SimpleNamespace(
        runtime_status=lambda: status,
        get_feature_monitor_status=lambda key, feature: {"camera_key": key, "feature": feature},
        get_camera_frame_info=lambda key, feature: (np.zeros((10, 10, 3), dtype=np.uint8), 0),
    )
    engine = api.factory.kw["bind"]
    AiAlarmEvent.__table__.create(engine)
    with api.factory.begin() as session:
        for number, department in enumerate(DEPARTMENTS, 1):
            session.add(AiAlarmEvent(id=number, violation_type=5, feature_name=SPEC.name, department=department,
                                    camera_no=department, subject_type="camera", subject_id=department,
                                    subject_name=department, image_path="missing.png", create_time=datetime.now()))
    monkeypatch.setattr(alarms, "get_session", api.factory)
    api.app.include_router(alarms.router)
    api.app.include_router(alarms.public_router)
    return api


@pytest.mark.parametrize("department", DEPARTMENTS)
def test_config_status_frame_alarm_and_statistics_are_scoped(human_api, department, monkeypatch):
    api = human_api
    other = next(d for d in DEPARTMENTS if d != department)
    api.app.dependency_overrides[get_current_user] = lambda: {"role": "viewer", "departments": [department]}
    for key, expected in ((department, 200), (other, 403)):
        for path in (f"/api/features/detect_human/configs/{key}",
                     f"/api/features/detect_human/cameras/{key}/status",
                     f"/api/cameras/{key}/frame.jpg?feature=detect_human"):
            response = api.client.get(path)
            assert response.status_code == expected, (path, response.text)
        for enabled in (True, False):
            assert save(api, SPEC.name, enabled, camera=key).status_code == 403
        assert api.client.patch(f"/api/cameras/{key}", json={"enabled": False}).status_code == 403
    assert api.client.get(f"/api/cameras?department={other}").status_code == 403
    assert api.client.get("/api/cameras").status_code == 422
    cameras = api.client.get("/api/cameras", params={"department": department}).json()
    assert [camera["department"] for camera in cameras] == [department]
    status = api.client.get("/api/runtime/status").json()
    assert status["running_cameras"] == [department]
    assert len(status["inference"]["consumers"][SPEC.name]["targets"]) == 1
    assert "workers" not in status["inference"]
    events = api.client.get("/api/alarms?feature=detect_human").json()["items"]
    assert [event["department"] for event in events] == [department]
    stats = api.client.get("/api/alarms/statistics/summary?feature=detect_human").json()
    assert stats["summary"]["total"] == 1
    assert stats["by_type"] == [{"event_type": "detect_human", "name": SPEC.display_name, "value": 1}]
    assert api.client.get(f"/api/alarms?department={other}").status_code == 403
    other_id = DEPARTMENTS.index(other) + 1
    assert api.client.get(f"/api/alarms/{other_id}").status_code == 403
    for resource in ("image", "video"):
        assert api.client.get(f"/api/alarms/{other_id}/{resource}").status_code == 403
    # 公开路径不能绕过事业部权限；真实认证层没有登录时拒绝。
    assert api.client.get(f"/api/public/alarms/{other_id}/image").status_code == 401
    monkeypatch.setattr(alarms, "get_current_user", lambda _request: {"role": "viewer", "departments": [department]})
    assert api.client.get(f"/api/public/alarms/{other_id}/image").status_code == 403


def test_admin_config_and_enable_changes_only_affect_selected_camera(human_api):
    api = human_api
    before = api.client.get("/api/features/detect_human/configs/haoda_company").json()
    first, second = [camera["camera_id"] for camera in api.cameras[:2]]
    assert api.cache.get_function_config(first, SPEC.name)["MAX_TIME"] == 10
    assert api.cache.get_function_config(second, SPEC.name)["MAX_TIME"] == 20
    assert save(api, SPEC.name, False, camera="general_electric").status_code == 200
    assert api.client.get("/api/features/detect_human/configs/haoda_company").json() == before
    assert api.cache.get_function_config(second, SPEC.name)["enable"] is True
    assert api.client.patch("/api/cameras/haoda_company", json={"department": "research_institute"}).status_code == 200
    assert api.client.get("/api/alarms/statistics/summary?feature=detect_human").json()["summary"]["total"] == len(DEPARTMENTS)


def test_shared_human_requires_explicit_department_even_for_preexisting_enable(department_api):
    api = department_api
    camera = create_camera(api)
    with api.factory.begin() as session:
        session.get(AiCameraConfig, camera["camera_id"]).department = None
    assert save(api, SPEC.name, True).status_code == 400
    with api.factory.begin() as session:
        session.query(SPEC.orm_class).filter_by(camera_id=camera["camera_id"]).one().enable = True
    assert save(api, SPEC.name, True).status_code == 400
    assert save(api, SPEC.name, False).status_code == 200


@pytest.fixture
def human_evidence(human_api, tmp_path, monkeypatch):
    import cv2
    api = human_api
    image = tmp_path / "human.png"
    video = tmp_path / "human.mp4"
    assert cv2.imwrite(str(image), np.full((600, 800, 3), 127, dtype=np.uint8))
    video.write_bytes(b"test-video")
    with api.factory.begin() as session:
        for row in session.query(AiAlarmEvent):
            row.image_path = str(image)
            row.video_path = str(video)
            row.video_status = "ready"
    monkeypatch.setattr(alarms, "ensure_browser_compatible_mp4", lambda path: path)
    monkeypatch.setenv("AUTH_SECRET", "test-thumbnail-secret-with-at-least-32-characters")
    return api


@pytest.mark.parametrize("role,departments,expected", [
    (None, [], 401), ("viewer", ["general_electric"], 200),
    ("viewer", ["haoda_company"], 403), ("admin", ["all"], 200),
])
def test_human_evidence_access_matrix(human_evidence, monkeypatch, role, departments, expected):
    api = human_evidence
    if role is None:
        api.app.dependency_overrides.pop(get_current_user, None)
    else:
        user = {"role": role, "departments": departments}
        api.app.dependency_overrides[get_current_user] = lambda: user
        monkeypatch.setattr(alarms, "get_current_user", lambda _request: user)
    for resource in ("image", "video"):
        response = api.client.get(f"/api/alarms/1/{resource}")
        assert response.status_code == expected, response.text
    assert api.client.get("/api/alarms/1").status_code == expected
    assert api.client.get("/api/public/alarms/1/image").status_code == expected


def test_notification_link_only_grants_one_small_image_and_expires(human_evidence, monkeypatch, caplog):
    import cv2
    from AiVision.alarms.notifications import notification_image as thumbnails
    from AiVision.alarms.dispatcher import AlarmDispatcher
    from urllib.parse import urlsplit, parse_qs
    api = human_evidence
    api.app.dependency_overrides.pop(get_current_user, None)
    clock = [1_000_000.]
    monkeypatch.setattr(thumbnails.time, "time", lambda: clock[0])
    dispatcher = AlarmDispatcher()
    url, detail = dispatcher._alarm_card_urls(1, feature_name="detect_human", department="general_electric")
    split = urlsplit(url)
    path = split.path + "?" + split.query
    token = parse_qs(split.query)["thumbnail_token"][0]
    secret = "test-thumbnail-secret-with-at-least-32-characters"
    assert secret not in url and secret not in detail
    assert "thumbnail_token" not in detail
    response = api.client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    frame = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert frame.shape[:2] == (240, 320)
    assert api.client.get(path.replace("/1/", "/2/")).status_code == 403
    for resource in ("image", "video"):
        assert api.client.get(f"/api/alarms/1/{resource}?thumbnail_token={token}").status_code == 401
    assert api.client.get("/api/alarms/1", params={"thumbnail_token": token}).status_code == 401
    wrong_department = thumbnails.issue_thumbnail_token(1, "haoda_company")
    assert api.client.get(split.path, params={"thumbnail_token": wrong_department}).status_code == 403
    for bad in ("", "broken", token + "x", "9" * 101):
        rejected = api.client.get(split.path, params={"thumbnail_token": bad})
        assert rejected.status_code == 403
        assert secret not in rejected.text
    clock[0] += thumbnails.settings.alarm.wechat_thumbnail_ttl_seconds
    assert api.client.get(path).status_code == 403
    assert secret not in caplog.text


def test_notification_link_does_not_override_authenticated_department(human_evidence, monkeypatch):
    from AiVision.alarms.notifications.notification_image import issue_thumbnail_token
    api = human_evidence
    token = issue_thumbnail_token(1, "general_electric")
    url = f"/api/public/alarms/1/image?thumbnail_token={token}"
    for user, status in (({"role": "viewer", "departments": ["haoda_company"]}, 403),
                         ({"role": "viewer", "departments": ["general_electric"]}, 200),
                         ({"role": "admin"}, 200)):
        monkeypatch.setattr(alarms, "get_current_user", lambda _request: user)
        assert api.client.get(url, headers={"Authorization": "Bearer test-identity"}).status_code == status


def test_notification_link_revokes_after_department_or_key_change(human_evidence, monkeypatch):
    from AiVision.alarms.notifications.notification_image import issue_thumbnail_token
    api = human_evidence
    url = "/api/public/alarms/1/image?thumbnail_token=" + issue_thumbnail_token(1, "general_electric")
    with api.factory.begin() as session:
        session.get(AiAlarmEvent, 1).department = "haoda_company"
    assert api.client.get(url).status_code == 403
    with api.factory.begin() as session:
        session.get(AiAlarmEvent, 1).department = "general_electric"
    monkeypatch.setenv("AUTH_SECRET", "changed-test-secret-with-at-least-32-characters")
    assert api.client.get(url).status_code == 403


@pytest.mark.parametrize("alarm_id,department", [(1, "general_electric"), (6, "haoda_company")])
def test_human_wechat_queue_card_thumbnail_is_fetchable_without_login(human_evidence, monkeypatch, alarm_id, department):
    from AiVision.alarms.dispatcher import AlarmDispatcher, AlarmRequest
    from AiVision.alarms.notifications.wechat import WeChatNotifier
    from urllib.parse import urlsplit
    api = human_evidence
    dispatcher = AlarmDispatcher()
    dispatcher.wechat = WeChatNotifier(corp_id="test-corp", corp_secret="test-secret")
    monkeypatch.setattr(dispatcher.wechat, "_get_token", lambda: "test-token")
    messages = []
    def post(_url, **kwargs):
        messages.append(kwargs["json"])
        dispatcher._wechat_stop_event.set()
        return SimpleNamespace(status_code=200, json=lambda: {"errcode": 0})
    monkeypatch.setattr("AiVision.alarms.notifications.wechat.requests.post", post)
    request = AlarmRequest(feature_name="detect_human", department=department, camera_id=alarm_id,
                           cooldown_subject_type="camera", cooldown_subject_id=str(alarm_id),
                           camera_name="test-camera", frame=np.zeros((8, 8, 3)), violation_type=5, alarm_config={})
    dispatcher._wechat_queue.put((request, "test-recipient", SimpleNamespace(id=alarm_id)))
    dispatcher._wechat_loop()
    assert len(messages) == 1 and messages[0]["msgtype"] == "news"
    article = messages[0]["news"]["articles"][0]
    assert "thumbnail_token" not in article["url"]
    image = urlsplit(article["picurl"])
    assert api.client.get(image.path + "?" + image.query).status_code == 200


def test_notification_signing_requires_a_real_secret(monkeypatch):
    from AiVision.alarms.notifications.notification_image import issue_thumbnail_token, verify_thumbnail_token
    for secret in ("", "short", "x" * 31):
        monkeypatch.setenv("AUTH_SECRET", secret)
        with pytest.raises(ValueError, match="AUTH_SECRET"):
            issue_thumbnail_token(1, "general_electric")
        assert not verify_thumbnail_token("9999999999.invalid", 1, "general_electric")


@pytest.mark.parametrize("department", DEPARTMENTS)
def test_notification_thumbnail_accepts_all_official_departments(monkeypatch, department):
    from AiVision.alarms.notifications.notification_image import issue_thumbnail_token, verify_thumbnail_token

    monkeypatch.setenv("AUTH_SECRET", "notification-test-secret-at-least-32-characters")
    token = issue_thumbnail_token(1, department)
    assert verify_thumbnail_token(token, 1, department)
    for other in DEPARTMENTS:
        if other != department:
            assert not verify_thumbnail_token(token, 1, other)


@pytest.mark.parametrize("role", ["admin", "viewer"])
@pytest.mark.parametrize("department", DEPARTMENTS)
def test_camera_list_requires_explicit_department_for_every_account(human_api, department, role):
    api = human_api
    other = next(value for value in DEPARTMENTS if value != department)
    for authorized in ([department], [department, other]):
        api.app.dependency_overrides[get_current_user] = lambda: {"role": role, "departments": authorized}
        assert api.client.get("/api/cameras").status_code == 422
        for invalid in ("", "unknown", "ge", "general-electric", "通用电气"):
            assert api.client.get("/api/cameras", params={"department": invalid}).status_code == 400
        response = api.client.get("/api/cameras", params={"department": department})
        assert response.status_code == 200
        assert [camera["department"] for camera in response.json()] == [department]


@pytest.mark.parametrize("user", [
    {"role": "viewer", "departments": []},
    {"role": "viewer", "departments": ["all"]},
    {"role": "unknown", "departments": ["general_electric"]},
])
def test_unfiltered_alarm_queries_still_require_authorized_departments(human_api, user):
    human_api.app.dependency_overrides[get_current_user] = lambda: user
    for path in ("/api/alarms", "/api/alarms/statistics/summary"):
        assert human_api.client.get(path).status_code == 403
