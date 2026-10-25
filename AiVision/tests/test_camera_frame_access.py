"""预览身份查询只访问摄像头主表，完整详情仍保留功能元数据。"""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def camera_database(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "tests", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "tests", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    from AiVision.cameras import config_manager
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.core.db import Base

    specs = config_manager.all_specs()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(config_manager, "get_session", factory)
    with factory.begin() as session:
        session.add_all([
            AiCameraConfig(id=1, name="入口", shm_name="camera_1", url="rtsp://test.invalid/one",
                           department="general_electric"),
            AiCameraConfig(id=2, name="旧采集点", shm_name="legacy_stream", url="rtsp://test.invalid/two",
                           department="electronics_electrician"),
            AiCameraConfig(id=3, name="无共享内存", shm_name="", url="rtsp://test.invalid/three"),
            AiCameraConfig(id=4, name="别名冲突", shm_name="camera_2", url="rtsp://test.invalid/four",
                           department="general_electric"),
        ])
        session.add(specs["blocks"].orm_class(camera_id=1, enable=True, sort_order=17))

    selects = []

    @event.listens_for(engine, "before_cursor_execute")
    def record_read_tables(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(tuple(table.name for table in context.compiled.statement.get_final_froms()))

    yield SimpleNamespace(
        manager=config_manager.CameraConfigManager(), session=factory,
        camera=AiCameraConfig, specs=specs, selects=selects,
    )
    engine.dispose()


@pytest.mark.parametrize("key, camera_id, shm_name, department, queries", [
    (1, 1, "camera_1", "general_electric", 1),
    ("camera_1", 1, "camera_1", "general_electric", 1),
    (" camera_1 ", 1, "camera_1", "general_electric", 1),
    ("入口", 1, "camera_1", "general_electric", 2),
    ("1", 1, "camera_1", "general_electric", 3),
    (2, 2, "legacy_stream", "electronics_electrician", 1),
    ("legacy_stream", 2, "legacy_stream", "electronics_electrician", 1),
    ("旧采集点", 2, "legacy_stream", "electronics_electrician", 2),
    ("2", 2, "legacy_stream", "electronics_electrician", 3),
    ("camera_2", 4, "camera_2", "general_electric", 1),
    (3, 3, "camera_3", None, 1),
    ("camera_3", 3, "camera_3", None, 3),
])
def test_identity_preserves_aliases_without_reading_feature_tables(
    camera_database, key, camera_id, shm_name, department, queries,
):
    assert camera_database.manager.get_camera_identity(key) == {
        "camera_id": camera_id, "shm_name": shm_name, "department": department,
    }
    assert camera_database.selects == [("ai_camera_config",)] * queries


@pytest.mark.parametrize("key, queries", [("", 0), ("  ", 0), ("missing", 2), (999, 1), ("camera_999", 3)])
def test_missing_identity_does_not_read_feature_tables(camera_database, key, queries):
    assert camera_database.manager.get_camera_identity(key) is None
    assert camera_database.selects == [("ai_camera_config",)] * queries


@pytest.mark.parametrize("operation", ["get_camera", "list_cameras"])
def test_complete_camera_reads_keep_feature_states_and_orders(camera_database, operation):
    manager = camera_database.manager
    camera = manager.get_camera("camera_1") if operation == "get_camera" else manager.list_cameras()[0]
    assert camera["camera_id"] == 1
    assert camera["url"] == "rtsp://test.invalid/one"
    assert camera["functions"]["blocks"] is True
    assert camera["feature_sort_orders"]["blocks"] == 17
    assert set(camera["functions"]) == set(camera_database.specs)
    assert len(camera_database.selects) == len(camera_database.specs) + 1
    assert set(camera_database.selects) == {
        ("ai_camera_config",),
        *((spec.orm_class.__tablename__,) for spec in camera_database.specs.values()),
    }


def test_identity_reads_latest_department_and_does_not_cache_removed_camera(camera_database):
    manager = camera_database.manager
    assert manager.get_camera_identity("camera_1")["department"] == "general_electric"
    with camera_database.session.begin() as session:
        session.get(camera_database.camera, 1).department = "electronics_electrician"
    camera_database.selects.clear()
    assert manager.get_camera_identity("camera_1")["department"] == "electronics_electrician"
    assert camera_database.selects == [("ai_camera_config",)]
    with camera_database.session.begin() as session:
        session.delete(session.get(camera_database.camera, 1))
    assert manager.get_camera_identity("camera_1") is None
