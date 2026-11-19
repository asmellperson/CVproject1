"""高频状态查询的数据库预算、摄像头键与事业部授权。"""
import pytest


@pytest.fixture
def status_database(monkeypatch, tmp_path):
    for key, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "test",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path), "AUTH_SECRET": "camera-status-test-signing-key-0000",
    }.items():
        monkeypatch.setenv(key, value)
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from AiVision.cameras import config_manager
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.core.db import Base
    from AiVision.features.registry import all_specs

    specs = all_specs()
    fence = specs["security_fence"].orm_class
    tailgating = specs["tailgating"].orm_class
    engine = create_engine("sqlite://")
    # 只建目标状态使用的表，查询碰到任何其他功能表都会失败。
    Base.metadata.create_all(engine, tables=[AiCameraConfig.__table__, fence.__table__, tailgating.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(config_manager, "get_session", sessions)
    with sessions.begin() as session:
        for camera_id, name, key, department, enabled in (
            (1, "闸机一号", "gate_main", "general_electric", True),
            (2, "工位二号", "camera_1", "electronics_electrician", False),
            (3, "camera_2", "gate_other", "general_electric", True),
        ):
            session.add(AiCameraConfig(
                id=camera_id, name=name, shm_name=key, department=department,
                enable=enabled, url="rtsp://192.0.2.1/test-source",
            ))
        session.add(fence(camera_id=1, enable=True, timezone="Asia/Shanghai"))
        session.add(tailgating(camera_id=1, enable=True))
        session.add(tailgating(camera_id=2, enable=True))

    queries = []

    @event.listens_for(engine, "before_cursor_execute")
    def record_select(_connection, _cursor, sql, _parameters, _context, _executemany):
        if sql.lstrip().upper().startswith("SELECT"):
            queries.append(sql.lower())

    yield config_manager.CameraConfigManager(), queries, fence.__tablename__, tailgating.__tablename__
    engine.dispose()


def test_monitor_status_queries_only_current_camera_and_selected_switch(status_database):
    manager, queries, fence_table, tailgating_table = status_database
    result = manager.get_camera_for_status("gate_main", "tailgating")

    assert result == {
        "camera_id": 1, "shm_name": "gate_main", "name": "闸机一号", "department": "general_electric",
        "enabled": True, "functions": {"tailgating": True},
    }
    assert len(queries) == 2
    assert tailgating_table in queries[1] and fence_table not in queries[1]
    assert queries[1].split("from", 1)[0].strip() == f"select {tailgating_table}.enable as {tailgating_table}_enable"


def test_monitor_status_reuses_target_query_for_full_fence_configuration(status_database):
    manager, queries, fence_table, tailgating_table = status_database
    result = manager.get_camera_for_status("gate_main", "security_fence", include_feature_config=True)

    assert result["feature_config"]["value"]["timezone"] == "Asia/Shanghai"
    assert result["feature_config"]["enable"] is True
    assert result["functions"] == {"security_fence": True}
    assert len(queries) == 2
    assert fence_table in queries[1] and tailgating_table not in queries[1]

    no_config = manager.get_camera_for_status("gate_other", "security_fence", include_feature_config=True)
    assert no_config["feature_config"] is None
    assert no_config["functions"] == {"security_fence": False}


@pytest.mark.parametrize(("key", "camera_id"), [
    (" camera_1 ", 2), ("camera_2", 3), ("camera_3", 3), ("1", 1), (1, 1), ("不存在", None),
])
def test_monitor_status_keeps_existing_camera_key_precedence(status_database, key, camera_id):
    manager, _, _, _ = status_database
    result = manager.get_camera_for_status(key, "tailgating")
    assert (result["camera_id"] if result else None) == camera_id
    if camera_id == 2:
        assert result["enabled"] is False
        assert result["functions"] == {"tailgating": True}


def test_monitor_status_rechecks_actual_department_and_feature_assignment(status_database):
    from fastapi import HTTPException
    from AiVision.api.routes.cameras import get_camera_for_status

    manager, _, _, _ = status_database
    user = {
        "role": "viewer", "departments": ["general_electric", "electronics_electrician"],
        "feature_access": {"general_electric": ["tailgating"], "electronics_electrician": []},
    }

    assert get_camera_for_status(manager, "gate_main", user, "tailgating")["camera_id"] == 1
    with pytest.raises(HTTPException) as unassigned:
        get_camera_for_status(manager, "camera_1", user, "tailgating")
    assert unassigned.value.status_code == 403
    user["departments"] = ["electronics_electrician"]
    with pytest.raises(HTTPException) as unauthorized:
        get_camera_for_status(manager, "gate_main", user, "tailgating")
    assert unauthorized.value.status_code == 403
    with pytest.raises(HTTPException) as missing:
        get_camera_for_status(manager, "不存在", user, "tailgating")
    assert missing.value.status_code == 404
