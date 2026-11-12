"""人员逗留外部报警接口回归，使用临时数据库和图片，不启动现场检测。"""
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest


OWN = "general_electric"
OTHER = "research_institute"
BASE = "/api/external/human-dwell"
BIG_ID = 9007199254741001


@pytest.fixture
def api(monkeypatch, tmp_path):
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "external_test",
        "MYSQL_DB_PASSWORD": "external_test", "MYSQL_DB_NAME": "external_test",
        "DATA_PATH": str(tmp_path), "AUTH_SECRET": "external-human-test-signing-key-0000",
    }.items():
        monkeypatch.setenv(key, value)

    import cv2
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from AiVision.api.app import create_app
    from AiVision.api.deps import get_department_service
    from AiVision.api.routes import alarms
    from AiVision.alarms.records.orm import AiAlarmEvent
    from AiVision.features.person_dwell import service

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    AiAlarmEvent.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    image = np.full((12, 20, 3), 150, dtype=np.uint8)
    image_path = tmp_path / "alarm.png"
    assert cv2.imwrite(str(image_path), image)
    with sessions() as session:
        for alarm_id, feature, kind, department, camera, stamp, path in [
            (101, "detect_human", 5, OWN, "camera_1", datetime(2026, 11, 10, 8), str(image_path)),
            (102, "detect_human", 5, OWN, "camera_2", datetime(2026, 11, 11, 9), ""),
            (103, "detect_human", 5, OTHER, "camera_3", datetime(2026, 11, 12, 10), str(image_path)),
            (104, "security_fence", 16, OWN, "camera_1", datetime(2026, 11, 12, 11), str(image_path)),
            (105, "tailgating", 17, OWN, "camera_1", datetime(2026, 11, 12, 11), str(image_path)),
            (BIG_ID, "detect_human", 5, OWN, "camera_1", datetime(2026, 11, 12, 10), str(image_path)),
            (107, "detect_human", 5, OWN, "camera_4", datetime(2026, 11, 12, 11), str(tmp_path / "missing.png")),
            (109, "detect_human", 5, OWN, "camera_1", datetime(2026, 11, 12, 10), str(image_path)),
        ]:
            session.add(AiAlarmEvent(
                id=alarm_id, feature_name=feature, violation_type=kind, department=department,
                camera_no=camera, subject_type="camera", subject_id=camera, subject_name="测试摄像头",
                reason="已保存的原因" if alarm_id == 102 else "", image_path=path,
                event_metadata={}, create_time=stamp,
            ))
        session.commit()
        # 模拟历史类型不一致记录，确保功能名和类型编号必须同时匹配。
        session.execute(AiAlarmEvent.__table__.insert().values(
            id=108, feature_name="detect_human", violation_type=17, department=OWN,
            image_path=str(image_path), create_time=datetime(2026, 11, 12, 12),
        ))
        session.commit()

    monkeypatch.setattr(service, "get_session", sessions)
    monkeypatch.setattr(alarms, "get_session", sessions)
    access = {OWN: ["detect_human"], OTHER: ["detect_human"], "haoda_company": ["security_fence"]}
    app = create_app()
    app.dependency_overrides[get_department_service] = lambda: SimpleNamespace(feature_access=lambda: access)
    # 不进入 lifespan，避免启动助手恢复流程或连接业务数据库。
    client = TestClient(app)
    try:
        yield SimpleNamespace(client=client, access=access, image=image, image_path=image_path)
    finally:
        client.close()
        engine.dispose()


def test_anonymous_history_returns_stable_alarm_fields(api):
    response = api.client.get(f"{BASE}/history", params={"department": OWN})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["total"] == 5
    assert [item["id"] for item in data["items"]] == ["107", str(BIG_ID), "109", "102", "101"]
    row = data["items"][1]
    assert row["feature_name"] == row["event_type"] == "detect_human"
    assert row["violation_type"] == 5
    assert row["event_label"] == "人员违规逗留检测"
    assert row["reason"] == "人员违规逗留检测 - 测试摄像头"
    assert row["camera_key"] == "camera_1" and row["camera_name"] == "测试摄像头"
    assert datetime.fromisoformat(row["created_at"]).tzinfo is not None
    assert row["image_url"] == f"{BASE}/alarms/{BIG_ID}/image?department={OWN}"
    assert "image_path" not in row and "video_path" not in row
    empty_image = next(item for item in data["items"] if item["id"] == "102")
    assert empty_image["reason"] == "已保存的原因" and empty_image["image_url"] is None


def test_history_image_url_returns_actual_png_without_login(api):
    import cv2

    row = api.client.get(f"{BASE}/history", params={"department": OWN}).json()["items"][1]
    response = api.client.get(row["image_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert response.content == api.image_path.read_bytes()
    np.testing.assert_array_equal(cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR), api.image)
    assert api.client.get(f"{BASE}/alarms/{BIG_ID}", params={"department": OWN}).json() == row


@pytest.mark.parametrize("alarm_id", [103, 104, 105, 108, 999])
@pytest.mark.parametrize("suffix", ["", "/image"])
def test_alarm_and_image_reject_other_department_feature_or_type(api, alarm_id, suffix):
    response = api.client.get(f"{BASE}/alarms/{alarm_id}{suffix}", params={"department": OWN})
    assert response.status_code == 404


@pytest.mark.parametrize("alarm_id", [102, 107])
def test_missing_image_reference_or_file_returns_404(api, alarm_id):
    response = api.client.get(f"{BASE}/alarms/{alarm_id}/image", params={"department": OWN})
    assert response.status_code == 404 and response.json()["detail"] == "alarm image not found"


def test_history_counts_before_pagination_and_filters_camera_and_time(api):
    data = api.client.get(f"{BASE}/history", params={"department": OWN, "limit": 1, "offset": 1}).json()
    assert data["total"] == 5 and [item["id"] for item in data["items"]] == [str(BIG_ID)]
    data = api.client.get(f"{BASE}/history", params={"department": OWN, "camera_key": "camera_1"}).json()
    assert data["total"] == 3 and [item["id"] for item in data["items"]] == [str(BIG_ID), "109", "101"]
    params = {"department": OWN,
              "start": datetime(2026, 11, 11, 9).astimezone(timezone.utc).isoformat(),
              "end": datetime(2026, 11, 12, 10).astimezone(timezone.utc).isoformat()}
    data = api.client.get(f"{BASE}/history", params=params).json()
    assert data["total"] == 1 and data["items"][0]["id"] == "102"
    data = api.client.get(f"{BASE}/history", params={"department": OTHER}).json()
    assert data["total"] == 1 and data["items"][0]["id"] == "103"


@pytest.mark.parametrize("params,status", [
    ({}, 422), ({"department": "一厂"}, 400), ({"department": "haoda_company"}, 403),
    ({"department": OWN, "limit": 501}, 422), ({"department": OWN, "offset": -1}, 422),
    ({"department": OWN, "start": "2026-11-12T10:00:00"}, 422),
    ({"department": OWN, "start": "2026-11-12T10:00:00+08:00", "end": "2026-11-11T10:00:00+08:00"}, 400),
])
def test_invalid_history_scope_or_parameters_are_rejected(api, params, status):
    assert api.client.get(f"{BASE}/history", params=params).status_code == status


def test_department_catalog_and_revocation_apply_to_all_resources(api):
    response = api.client.get(f"{BASE}/departments")
    assert response.status_code == 200
    assert {row["name"] for row in response.json()} == {OWN, OTHER}
    api.access[OWN] = []
    for path in ("/history", "/alarms/101", "/alarms/101/image"):
        assert api.client.get(BASE + path, params={"department": OWN}).status_code == 403
    assert api.client.post(f"{BASE}/history", json={"department": OTHER}).status_code == 405


def test_platform_and_notification_image_authentication_remain_in_place(api):
    assert api.client.get("/api/alarms/101/image").status_code == 401
    assert api.client.get("/api/public/alarms/101/image").status_code == 401
