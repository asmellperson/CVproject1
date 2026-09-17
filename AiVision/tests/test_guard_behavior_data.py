"""保安行为数据层的真实事务、外键和成员约束测试。"""
from itertools import count
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from AiVision.alarms.devices.orm import AiHornConfig
from AiVision.cameras.orm import AiCameraConfig
from AiVision.core import db
from AiVision.core.schema import assert_table_matches
from AiVision.features._shared.orm import CameraFeatureConfigBase, FeatureConfigBase
from AiVision.features.guard_behavior import service as service_module
from AiVision.features.guard_behavior.constants import (
    ALARM_INTERVAL_DEFAULTS, ALARM_POLICY_DEFAULTS, GUARD_ALARM_TYPES,
    MAX_CAMERAS_PER_SITE, SITE_POLICY_DEFAULTS,
)
from AiVision.features.guard_behavior.orm import (
    GuardBehaviorAlarmPolicy, GuardBehaviorCameraConfig, GuardBehaviorSite,
    GuardBehaviorSiteCamera, GuardBehaviorSitePolicy,
)
from AiVision.features.guard_behavior.schema import GuardBehaviorMemberResponse
from AiVision.features.guard_behavior.service import GuardBehaviorService


DEPARTMENT = "general_electric"
OTHER_DEPARTMENT = "electronics_electrician"
GUARD_MODELS = (GuardBehaviorSite, GuardBehaviorSiteCamera, GuardBehaviorCameraConfig,
                GuardBehaviorSitePolicy, GuardBehaviorAlarmPolicy)


@pytest.fixture
def data_db(monkeypatch):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    sessions = []

    class ObservedSession(Session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.committed = self.rolled_back = self.closed = False
            sessions.append(self)

        def commit(self):
            super().commit()
            self.committed = True

        def rollback(self):
            super().rollback()
            self.rolled_back = True

        def close(self):
            super().close()
            self.closed = True

    tables = [AiCameraConfig.__table__, AiHornConfig.__table__, *(model.__table__ for model in GUARD_MODELS)]
    db.Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, class_=ObservedSession, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(db, "get_session", factory)
    sequence = count(1)

    def camera(department=DEPARTMENT):
        index = next(sequence)
        with factory.begin() as session:
            row = AiCameraConfig(name=f"camera-{index}", shm_name=f"guard-test-{index}",
                                 url="rtsp://camera.invalid/stream", department=department,
                                 enable=False, fps=7, sort_order=100 + index)
            session.add(row)
            session.flush()
            return row.id

    yield SimpleNamespace(engine=engine, factory=factory, sessions=sessions,
                          service=GuardBehaviorService(), camera=camera)
    engine.dispose()


def test_runtime_configuration_is_detached_read_only_and_preserves_flags(data_db):
    db = data_db
    service = db.service
    site = service.create_site("runtime", DEPARTMENT)
    camera_id = db.camera()
    assert service.get_runtime_camera_config(camera_id) is None
    service.add_camera(site["id"], camera_id)
    service.update_camera_roi(site["id"], camera_id, {"vehicle_roi_pos": [[0., 0.], [1., 0.], [0., 1.]]})
    service.set_camera_enabled(site["id"], camera_id, False)
    service.update_site(site["id"], {"enabled": False})
    snapshot = service.get_runtime_camera_config(camera_id)
    assert snapshot == service.list_runtime_camera_configs()[0]
    assert snapshot.camera_id == camera_id and snapshot.camera_name == "camera-1"
    assert snapshot.shm_name == "guard-test-1" and snapshot.fps == 7
    assert snapshot.site_id == site["id"] and snapshot.site_name == "runtime"
    assert not snapshot.site_enabled and not snapshot.member_enabled and snapshot.feature_enabled
    assert snapshot.vehicle_roi_pos == ((0., 0.), (1., 0.), (0., 1.))
    assert db.sessions[-1].closed
    assert "url" not in snapshot.model_dump()
    with pytest.raises(ValueError):
        snapshot.camera_name = "mutated"
    with pytest.raises(ValueError):
        snapshot.policy.cap_interval = 5
    service.update_policy(site["id"], {"cap_interval": 0.5})
    assert snapshot.policy.cap_interval == SITE_POLICY_DEFAULTS["cap_interval"]
    assert service.get_runtime_camera_config(camera_id).policy.cap_interval == 0.5
    service.remove_camera(site["id"], camera_id)
    assert service.list_runtime_camera_configs() == []


def site(data_db, name="南门", department=DEPARTMENT):
    return data_db.service.create_site(name, department)["id"]


def test_site_runtime_config_contains_detached_members_and_all_policies(data_db):
    service = data_db.service
    site_id = site(data_db)
    cameras = [data_db.camera(), data_db.camera()]
    for camera_id in cameras:
        service.add_camera(site_id, camera_id)
    service.reorder_cameras(site_id, list(reversed(cameras)))
    service.set_camera_enabled(site_id, cameras[0], False)
    config = service.get_runtime_site_config(site_id)
    assert config == service.list_runtime_site_configs()[0]
    assert tuple(member.camera_id for member in config.members) == tuple(reversed(cameras))
    assert config.members[0].member_enabled and not config.members[1].member_enabled
    assert all(member.feature_enabled and not member.physical_enabled for member in config.members)
    assert sorted(policy.violation_type for policy in config.alarm_policies) == list(GUARD_ALARM_TYPES)
    assert data_db.sessions[-1].closed
    assert "rtsp" not in config.model_dump_json()
    with pytest.raises(ValueError):
        config.members[0].physical_enabled = True
    with pytest.raises(ValueError):
        config.alarm_policies[0].sql_enable = True
    service.update_policy(site_id, {"absent_alarm_seconds": 100.})
    assert config.policy.absent_alarm_seconds == SITE_POLICY_DEFAULTS["absent_alarm_seconds"]
    assert service.get_runtime_site_config(site_id).policy.absent_alarm_seconds == 100.
    service.delete_site(site_id)
    assert service.get_runtime_site_config(site_id) is None


def test_orm_uses_shared_base_exact_tables_fields_and_real_schema_validation(data_db):
    expected = {
        "ai_guard_behavior_site", "ai_guard_behavior_site_camera", "ai_camera_config_guard_behavior",
        "ai_guard_behavior_site_policy", "ai_guard_behavior_alarm_policy",
    }
    assert {model.__tablename__ for model in GUARD_MODELS} == expected
    assert all(issubclass(model, db.Base) and model.metadata is db.Base.metadata for model in GUARD_MODELS)
    assert issubclass(GuardBehaviorCameraConfig, CameraFeatureConfigBase)
    assert not issubclass(GuardBehaviorCameraConfig, FeatureConfigBase)
    assert set(GuardBehaviorCameraConfig.__table__.columns.keys()) == {
        "id", "camera_id", "enable", "vehicle_roi_pos", "created_at", "updated_at",
    }
    assert set(GuardBehaviorSitePolicy.__table__.columns.keys()) == {
        "id", "site_id", "created_at", "updated_at", *SITE_POLICY_DEFAULTS,
    }
    with data_db.engine.connect() as connection:
        for model in GUARD_MODELS:
            assert_table_matches(connection, model.__table__)
    inspector = inspect(data_db.engine)
    unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("ai_guard_behavior_site_camera")}
    assert unique == {("camera_id",), ("site_id", "camera_id")}
    fks = inspector.get_foreign_keys("ai_guard_behavior_site_policy")
    assert next(fk for fk in fks if fk["constrained_columns"] == ["vehicle_camera_id"])["options"]["ondelete"] == "SET NULL"


def test_create_site_is_complete_and_defaults_share_one_source(data_db):
    site_id = site(data_db)
    session = data_db.sessions[-1]
    assert session.committed and session.closed and not session.rolled_back
    with data_db.factory() as session:
        assert session.query(GuardBehaviorSite).count() == 1
        assert session.query(GuardBehaviorSitePolicy).count() == 1
        assert session.query(GuardBehaviorAlarmPolicy).count() == 4
    policy = data_db.service.get_policy(site_id)
    assert {key: policy[key] for key in SITE_POLICY_DEFAULTS} == dict(SITE_POLICY_DEFAULTS)
    alarms = data_db.service.list_alarm_policies(site_id)
    assert tuple(item["violation_type"] for item in alarms) == GUARD_ALARM_TYPES
    for alarm in alarms:
        assert alarm["alarm_interval"] == ALARM_INTERVAL_DEFAULTS[alarm["violation_type"]]
        assert {key: alarm[key] for key in ALARM_POLICY_DEFAULTS} == dict(ALARM_POLICY_DEFAULTS)


@pytest.mark.parametrize("failure", ["policy", "third_alarm", "commit"])
def test_create_failure_rolls_back_whole_structure_and_closes_session(data_db, monkeypatch, failure):
    def fail(*_):
        raise IntegrityError("private SQL", {}, RuntimeError("private database details"))

    if failure == "commit":
        monkeypatch.setattr(data_db.factory.class_, "commit", fail)
    else:
        target = GuardBehaviorSitePolicy if failure == "policy" else GuardBehaviorAlarmPolicy

        def before_insert(mapper, connection, row):
            if failure == "policy" or row.violation_type == GUARD_ALARM_TYPES[2]:
                fail()
        event.listen(target, "before_insert", before_insert)
    try:
        with pytest.raises(ValueError, match="配置写入冲突") as caught:
            site(data_db)
        assert "private" not in str(caught.value)
        assert data_db.sessions[-1].rolled_back and data_db.sessions[-1].closed
    finally:
        if failure != "commit":
            event.remove(target, "before_insert", before_insert)
    with data_db.factory() as session:
        for model in (GuardBehaviorSite, GuardBehaviorSitePolicy, GuardBehaviorAlarmPolicy):
            assert session.query(model).count() == 0


def test_department_names_updates_and_site_listing(data_db):
    service = data_db.service
    with pytest.raises(ValueError, match="department"):
        site(data_db, department="unknown")
    own = site(data_db)
    other = site(data_db, department=OTHER_DEPARTMENT)
    with pytest.raises(ValueError, match="已存在"):
        site(data_db)
    assert [item["id"] for item in service.list_sites(DEPARTMENT)] == [own]
    assert len(service.list_sites()) == 2
    for department in (DEPARTMENT, OTHER_DEPARTMENT):
        with pytest.raises(ValueError, match="department"):
            service.update_site(own, {"department": department})
    assert service.update_site(own, {"name": "  东门  ", "sort_order": 4, "enabled": False})["name"] == "东门"
    assert service.get_site(other)["name"] == "南门"
    with pytest.raises(ValueError):
        service.update_site(own, {"name": " "})
    assert all(session.closed for session in data_db.sessions)


def test_camera_membership_checks_preserves_physical_values_and_returns_readonly_identity(data_db):
    service = data_db.service
    own, other = site(data_db), site(data_db, "北门")
    camera_id, foreign = data_db.camera(), data_db.camera(OTHER_DEPARTMENT)
    with data_db.factory() as session:
        camera = session.get(AiCameraConfig, camera_id)
        before = {column.name: getattr(camera, column.name) for column in AiCameraConfig.__table__.columns}
    for site_id, candidate in ((9999, camera_id), (own, 9999), (own, foreign)):
        with pytest.raises(ValueError):
            service.add_camera(site_id, candidate)
    member = service.add_camera(own, camera_id)
    assert member["physical_enabled"] is False and member["member_enabled"] is True
    assert member["department"] == DEPARTMENT
    assert "url" not in member
    assert GuardBehaviorMemberResponse.model_validate(member).model_dump() == member
    for site_id in (own, other):
        with pytest.raises(ValueError, match="已属于"):
            service.add_camera(site_id, camera_id)
    with data_db.factory() as session:
        camera = session.get(AiCameraConfig, camera_id)
        assert before == {column.name: getattr(camera, column.name) for column in AiCameraConfig.__table__.columns}
        assert session.query(GuardBehaviorCameraConfig).filter_by(camera_id=camera_id).one().enable is True


def test_nine_camera_limit_counts_disabled_members(data_db):
    site_id = site(data_db)
    cameras = [data_db.camera() for _ in range(MAX_CAMERAS_PER_SITE + 1)]
    for camera_id in cameras[:-1]:
        data_db.service.add_camera(site_id, camera_id)
    data_db.service.set_camera_enabled(site_id, cameras[0], False)
    with pytest.raises(ValueError, match="9"):
        data_db.service.add_camera(site_id, cameras[-1])
    assert len(data_db.service.list_site_cameras(site_id)) == 9


def test_failed_camera_config_insert_rolls_back_membership(data_db):
    site_id, camera_id = site(data_db), data_db.camera()

    def fail(*_):
        raise IntegrityError("private SQL", {}, RuntimeError("write failure"))
    event.listen(GuardBehaviorCameraConfig, "before_insert", fail)
    try:
        with pytest.raises(ValueError, match="配置写入冲突"):
            data_db.service.add_camera(site_id, camera_id)
        assert data_db.sessions[-1].rolled_back and data_db.sessions[-1].closed
    finally:
        event.remove(GuardBehaviorCameraConfig, "before_insert", fail)
    with data_db.factory() as session:
        assert session.query(GuardBehaviorSiteCamera).count() == 0
        assert session.query(GuardBehaviorCameraConfig).count() == 0
        assert session.get(AiCameraConfig, camera_id) is not None


def test_membership_lifecycle_and_site_delete_preserve_camera_and_roi(data_db):
    service = data_db.service
    site_id, camera_id = site(data_db), data_db.camera()
    service.add_camera(site_id, camera_id)
    polygon = [[0.1, 0.2], [0.8, 0.2], [0.8, 0.9], [0.1, 0.9]]
    service.update_camera_roi(site_id, camera_id, {"vehicle_roi_pos": polygon})
    assert not service.set_camera_enabled(site_id, camera_id, False)["member_enabled"]
    assert service.get_camera_roi(site_id, camera_id) == {
        "camera_id": camera_id, "enable": True, "vehicle_roi_pos": polygon,
    }
    service.remove_camera(site_id, camera_id)
    with data_db.factory() as session:
        config = session.query(GuardBehaviorCameraConfig).one()
        assert config.enable is False and config.vehicle_roi_pos == polygon
    service.add_camera(site_id, camera_id)
    assert service.get_camera_roi(site_id, camera_id)["vehicle_roi_pos"] == polygon
    assert service.delete_site(site_id)
    with data_db.factory() as session:
        assert session.get(AiCameraConfig, camera_id) is not None
        config = session.query(GuardBehaviorCameraConfig).one()
        assert config.enable is False and config.vehicle_roi_pos == polygon
        for model in (GuardBehaviorSite, GuardBehaviorSiteCamera, GuardBehaviorSitePolicy, GuardBehaviorAlarmPolicy):
            assert session.query(model).count() == 0
    assert service.delete_site(site_id) is False


def test_reorder_requires_complete_unique_set_and_changes_only_member_order(data_db):
    service = data_db.service
    site_id = site(data_db)
    cameras = [data_db.camera() for _ in range(3)]
    for camera_id in cameras:
        service.add_camera(site_id, camera_id)
    for ids in (cameras[:-1], [cameras[0]] * 3, [*cameras, 999], [*cameras[:-1], 999]):
        with pytest.raises(ValueError):
            service.reorder_cameras(site_id, ids)
    service.reorder_cameras(site_id, list(reversed(cameras)))
    members = service.list_site_cameras(site_id)
    assert [item["camera_id"] for item in members] == list(reversed(cameras))
    assert [item["sort_order"] for item in members] == [0, 1, 2]
    with data_db.factory() as session:
        assert [session.get(AiCameraConfig, key).sort_order for key in cameras] == [101, 102, 103]


def test_site_delete_also_removes_enabled_vehicle_policy_without_deleting_physical_cameras(data_db):
    site_id = site(data_db)
    cameras = [data_db.camera(), data_db.camera()]
    for camera_id in cameras:
        data_db.service.add_camera(site_id, camera_id)
    data_db.service.set_camera_enabled(site_id, cameras[1], False)
    data_db.service.update_policy(site_id, {"vehicle_inspection_enabled": True, "vehicle_camera_id": cameras[0]})
    assert data_db.service.delete_site(site_id)
    with data_db.factory() as session:
        assert session.query(AiCameraConfig).count() == 2
        assert session.query(GuardBehaviorCameraConfig).count() == 2
        assert all(not config.enable for config in session.query(GuardBehaviorCameraConfig))
        assert session.query(GuardBehaviorSitePolicy).count() == 0
        assert session.query(GuardBehaviorAlarmPolicy).count() == 0


def test_vehicle_selection_requires_existing_same_department_enabled_member(data_db):
    service = data_db.service
    site_id, other = site(data_db), site(data_db, "北门")
    own, foreign, unbound = data_db.camera(), data_db.camera(OTHER_DEPARTMENT), data_db.camera()
    service.add_camera(other, own)
    for camera_id in (None, 9999, foreign, unbound, own):
        with pytest.raises(ValueError):
            service.update_policy(site_id, {"vehicle_inspection_enabled": True, "vehicle_camera_id": camera_id})
    service.remove_camera(other, own)
    service.add_camera(site_id, own)
    service.set_camera_enabled(site_id, own, False)
    with pytest.raises(ValueError, match="成员必须启用"):
        service.update_policy(site_id, {"vehicle_inspection_enabled": True, "vehicle_camera_id": own})
    service.set_camera_enabled(site_id, own, True)
    service.update_policy(site_id, {"vehicle_inspection_enabled": True, "vehicle_camera_id": own})
    before = service.get_policy(site_id)
    for action in (lambda: service.remove_camera(site_id, own), lambda: service.set_camera_enabled(site_id, own, False)):
        with pytest.raises(ValueError, match="请先关闭或修改"):
            action()
    assert service.get_policy(site_id) == before
    assert service.update_policy(site_id, {"phone_seconds": 4.2})["vehicle_camera_id"] == own
    with pytest.raises(ValueError, match="必须为 None"):
        service.update_policy(site_id, {"vehicle_inspection_enabled": False})
    result = service.update_policy(site_id, {"vehicle_inspection_enabled": False, "vehicle_camera_id": None})
    assert result["phone_seconds"] == 4.2
    service.remove_camera(site_id, own)


def test_policy_checks_department_even_for_inconsistent_membership(data_db):
    site_id, camera_id = site(data_db), data_db.camera(OTHER_DEPARTMENT)
    with data_db.factory.begin() as session:
        session.add(GuardBehaviorSiteCamera(site_id=site_id, camera_id=camera_id))
    with pytest.raises(ValueError, match="department"):
        data_db.service.update_policy(site_id, {"vehicle_inspection_enabled": True, "vehicle_camera_id": camera_id})


def test_alarm_updates_are_partial_isolated_and_use_public_horn_binding(data_db, monkeypatch):
    service = data_db.service
    site_id = site(data_db)
    before = service.list_alarm_policies(site_id)
    calls = []
    original = service_module.validate_horn_binding

    def observe(session, *args):
        calls.append(args)
        return original(session, *args)
    monkeypatch.setattr(service_module, "validate_horn_binding", observe)
    with data_db.factory.begin() as session:
        horn = AiHornConfig(name="test-horn", url="http://horn.invalid", password="test-only", enable=True)
        session.add(horn)
        session.flush()
        horn_id = horn.id
    updated = service.update_alarm_policy(site_id, 9, {"alarm_interval": 99., "sql_enable": True,
                                                    "horn_enable": True, "horn_id": horn_id, "horn_event_id": 12})
    assert calls == [(True, horn_id, 12)]
    assert updated["alarm_interval"] == 99.
    after = service.list_alarm_policies(site_id)
    assert [row for row in before if row["violation_type"] != 9] == [row for row in after if row["violation_type"] != 9]
    for violation_type in (1, 12, True, "8"):
        with pytest.raises(ValueError):
            service.update_alarm_policy(site_id, violation_type, {})
    for payload in ({"horn_id": 9999}, {"horn_event_id": None}, {"horn_id": True}, {"violation_type": 10}):
        with pytest.raises(ValueError):
            service.update_alarm_policy(site_id, 9, payload)
    with data_db.factory.begin() as session:
        session.get(AiHornConfig, horn_id).enable = False
    with pytest.raises(ValueError, match="已停用"):
        service.update_alarm_policy(site_id, 9, {"wechat_enable": True})
    assert service.update_alarm_policy(site_id, 9, {"horn_enable": False})["horn_id"] == horn_id
    assert len(service.list_alarm_policies(site_id)) == 4


def test_database_unique_constraints_are_final_membership_protection(data_db):
    own, other, camera_id = site(data_db), site(data_db, "北门"), data_db.camera()
    data_db.service.add_camera(own, camera_id)
    for site_id in (own, other):
        with pytest.raises(IntegrityError), data_db.factory.begin() as session:
            session.add(GuardBehaviorSiteCamera(site_id=site_id, camera_id=camera_id))
    with pytest.raises(IntegrityError), data_db.factory.begin() as session:
        session.add(GuardBehaviorSitePolicy(site_id=own))
    for kind in (8, 12):
        with pytest.raises(IntegrityError), data_db.factory.begin() as session:
            session.add(GuardBehaviorAlarmPolicy(site_id=own, violation_type=kind, alarm_interval=10))
    assert len(data_db.service.list_site_cameras(own)) == 1
    assert data_db.service.list_site_cameras(other) == []


def test_fk_delete_actions_preserve_camera_configs_until_physical_camera_deleted(data_db):
    site_id, camera_id = site(data_db), data_db.camera()
    data_db.service.add_camera(site_id, camera_id)
    data_db.service.update_policy(site_id, {"vehicle_inspection_enabled": True, "vehicle_camera_id": camera_id})
    with data_db.factory.begin() as session:
        session.execute(text("DELETE FROM ai_camera_config WHERE id=:id"), {"id": camera_id})
    with data_db.factory() as session:
        assert session.query(GuardBehaviorSiteCamera).count() == 0
        assert session.query(GuardBehaviorCameraConfig).count() == 0
        assert session.query(GuardBehaviorSitePolicy).one().vehicle_camera_id is None
    stored = data_db.service.get_policy(site_id)
    assert stored["vehicle_camera_id"] is None
    assert stored["vehicle_inspection_enabled"] is True
    with pytest.raises(ValueError, match="vehicle_camera_id"):
        data_db.service.update_policy(site_id, {"phone_seconds": 4})
    assert data_db.service.update_policy(site_id, {"vehicle_inspection_enabled": False})["vehicle_camera_id"] is None


def test_new_guard_table_schema_drift_is_rejected(data_db):
    with data_db.engine.begin() as connection:
        connection.execute(text("ALTER TABLE ai_guard_behavior_site ADD COLUMN unexpected INTEGER"))
        with pytest.raises(ValueError, match="列不一致"):
            assert_table_matches(connection, GuardBehaviorSite.__table__)
