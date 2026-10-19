"""摄像头标识由数据库主键生成，并在非法输入或冲突时完整回滚。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def store(monkeypatch, tmp_path):
    """使用内存数据库，隔离现场配置和摄像头启动通知。"""
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "test",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path), "AUTO_CREATE_DB": "false",
    }.items():
        monkeypatch.setenv(key, value)
    from AiVision.cameras import config_manager
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.core.system_config import AiSystemConfig
    from AiVision.api.routes import cameras

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    AiCameraConfig.__table__.create(engine)
    AiSystemConfig.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(config_manager, "get_session", factory)
    monkeypatch.setattr(config_manager, "session_scope", factory.begin)
    monkeypatch.setattr(config_manager, "all_specs", lambda: {})
    manager = config_manager.CameraConfigManager()
    monkeypatch.setattr(manager, "notify_camera_created", Mock())
    app = FastAPI()
    app.include_router(cameras.router)
    app.dependency_overrides[cameras.require_admin] = lambda: {"role": "admin"}
    app.dependency_overrides[cameras.get_camera_config_manager] = lambda: manager
    with TestClient(app) as client:
        yield SimpleNamespace(manager=manager, factory=factory, camera=AiCameraConfig, client=client)
    engine.dispose()


def payload(name="入口"):
    """调用方只提供设备信息，不根据名称或时间戳猜测共享内存标识。"""
    return {"name": name, "url": "rtsp://example.invalid/live", "department": "general_electric", "fps": 5}


def test_platform_creation_uses_database_id_without_client_shm_name(store):
    for name in ("一厂入口", "123-旧格式名称"):
        response = store.client.post("/api/cameras", json=payload(name))
        assert response.status_code == 201
        camera = response.json()
        assert camera["shm_name"] == f"camera_{camera['camera_id']}"
        assert camera["name"] == name
        assert camera["department"] == "general_electric"
        assert camera["enabled"] is True
    with store.factory() as session:
        assert session.query(store.camera).count() == 2
        assert all(row.shm_name == f"camera_{row.id}" for row in session.query(store.camera))


@pytest.mark.parametrize("shm_name,status_code", [("entrance_abc123", 422), ("camera_99999", 400)])
def test_api_rejects_custom_or_mismatched_name_without_partial_camera(store, shm_name, status_code):
    response = store.client.post("/api/cameras", json={**payload(), "shm_name": shm_name})
    assert response.status_code == status_code
    with store.factory() as session:
        assert session.query(store.camera).count() == 0
    store.manager.notify_camera_created.assert_not_called()


def test_matching_explicit_name_is_accepted(store):
    response = store.client.post("/api/cameras", json={**payload(), "shm_name": "camera_1"})
    assert response.status_code == 201
    assert response.json()["camera_id"] == 1
    assert response.json()["shm_name"] == "camera_1"


def test_shared_creation_rejects_custom_name_and_preserves_existing_camera(store):
    original = store.manager.create_camera(payload())
    with pytest.raises(ValueError, match="摄像头 ID 一致"):
        with store.factory.begin() as session:
            store.manager.create_camera_record(session, {**payload("第二台"), "shm_name": "old_random_name"})
    with store.factory() as session:
        rows = session.query(store.camera).all()
        assert len(rows) == 1
        assert rows[0].shm_name == original["shm_name"]
        assert rows[0].name == original["name"]
        assert rows[0].department == original["department"]


def test_legacy_collision_rolls_back_instead_of_overwriting_or_adding_suffix(store):
    with store.factory.begin() as session:
        session.add(store.camera(id=1, name="既有摄像头", url="rtsp://example.invalid/existing",
                                 shm_name="camera_2", department="general_electric", enable=True))
    with pytest.raises(ValueError, match="shm_name 已存在"):
        store.manager.create_camera(payload("新摄像头"))
    with store.factory() as session:
        rows = session.query(store.camera).all()
        assert [(row.id, row.name, row.shm_name) for row in rows] == [(1, "既有摄像头", "camera_2")]
    store.manager.notify_camera_created.assert_not_called()
