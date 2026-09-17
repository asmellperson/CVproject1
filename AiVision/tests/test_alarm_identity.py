"""当前告警的正式字段约束、生产入口归属和查询隔离。"""
from dataclasses import replace
from types import MethodType, SimpleNamespace
from AiVision.departments.department_registry import DEPARTMENT_SPECS

import numpy as np
import pytest

from AiVision.alarms.dispatcher import AlarmDispatcher, AlarmRequest
from AiVision.features.registry import all_specs
from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.alarms.records.orm import AiAlarmEvent
from AiVision.alarms.types import VIOLATION_TYPE_META
from AiVision.alarms.validation import validate_alarm_identity
from AiVision.features import registry
from AiVision.api.routes.logistics_channels import _channel_alarm_query, _alarm_dict
from AiVision.tests.test_violation_writer import writer_db


def identity():
    return dict(violation_type=1, feature_name="blocks", department="research_institute")


def request(**values):
    return AlarmRequest(camera_id=1, camera_name="camera", frame=np.zeros((4, 4, 3), np.uint8), alarm_config={},
                        cooldown_subject_type="camera", cooldown_subject_id="1", **values)


@pytest.mark.parametrize("changes", [
    {"violation_type": value} for value in [0, 7, 8, 9, 10, True, 1.0, "1", None]
] + [
    {"feature_name": ""}, {"feature_name": "unknown"}, {"feature_name": " blocks "},
    {"department": None}, {"department": ""}, {"department": "unknown"},
    {"feature_name": "detect_human"},
])
def test_all_new_alarm_boundaries_reject_invalid_identity(writer_db, changes):
    writer, _, _ = writer_db
    values = identity() | changes
    with pytest.raises(ValueError):
        request(**values)
    with pytest.raises(ValueError):
        AiAlarmEvent(image_path="unused.png", **values)
    for method in (writer.enqueue, writer.save_now):
        with pytest.raises(ValueError):
            method(frame=np.zeros((4, 4, 3), np.uint8), camera_no="camera", **values)
    assert writer._queue.empty()
    assert list(writer._data_path.rglob("*.png")) == []


@pytest.mark.parametrize("missing", ["violation_type", "feature_name", "department"])
def test_new_alarm_identity_is_required(writer_db, missing):
    writer, _, _ = writer_db
    values = identity()
    del values[missing]
    for build in (request, AiAlarmEvent):
        with pytest.raises(TypeError):
            build(**values)
    for method in (writer.enqueue, writer.save_now):
        with pytest.raises(TypeError):
            method(frame=np.zeros((4, 4, 3), np.uint8), camera_no="camera", **values)


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_recognition_alarm_identity_is_accepted_at_all_write_boundaries(writer_db, department):
    writer, factory, _ = writer_db
    values = dict(violation_type=7, feature_name="recognize_face", department=department)
    assert request(**values).violation_type == 7
    with factory.begin() as session:
        session.add(AiAlarmEvent(image_path="recognition.png", **values))
    result = writer.save_now(frame=np.zeros((4, 4, 3), np.uint8), camera_no="camera", **values)
    assert result and result.id
    writer.enqueue(frame=np.zeros((4, 4, 3), np.uint8), camera_no="camera", **values)
    assert not writer._queue.empty()
    for violation_type in [0, max(VIOLATION_TYPE_META) + 1, True, 7.0, "7"]:
        with pytest.raises(ValueError):
            request(**(values | {"violation_type": violation_type}))


def test_orm_revalidates_identity_before_insert(writer_db):
    _, factory, _ = writer_db
    row = AiAlarmEvent(image_path="unused.png", **identity())
    row.department = ""
    with factory() as session:
        session.add(row)
        with pytest.raises(ValueError, match="department"):
            session.commit()
        session.rollback()
        assert session.query(AiAlarmEvent).count() == 0


@pytest.mark.parametrize("spec", [spec for spec in all_specs().values() if not spec.name.startswith("detect_logistics") and len(spec.alarm_types) == 1], ids=lambda spec: spec.name)
def test_regular_features_skip_camera_without_department(monkeypatch, spec):
    import AiVision.features._shared.consumer as module
    captured = []
    monkeypatch.setattr(module.alarm_dispatcher, "maybe_dispatch", lambda req, **_: captured.append(req))
    consumer = SimpleNamespace(feature_name=spec.name, spec=spec, frame_cache={},
        config_cache={1: {**spec.config_schema().value.model_dump(), "department": None, "name": "camera-1"}}, _should_alarm=lambda *_: True, _alarm_context=lambda *_: {})
    BaseFunctionConsumer._handle_alarm(consumer, 1, [], np.zeros((4, 4, 3), np.uint8))
    assert captured == []


def test_ambiguous_camera_department_is_not_guessed(monkeypatch):
    import AiVision.features._shared.consumer as module
    captured, errors = [], []
    monkeypatch.setattr(module.alarm_dispatcher, "maybe_dispatch", lambda req, **_: captured.append(req))
    monkeypatch.setattr(module.logger, "error", errors.append)
    consumer = SimpleNamespace(feature_name="detect_human", spec=all_specs()["detect_human"],
        config_cache={1: {}}, _should_alarm=lambda *_: True, _alarm_context=lambda *_: {})
    BaseFunctionConsumer._handle_alarm(consumer, 1, [], np.zeros((4, 4, 3), np.uint8))
    assert not captured
    assert any("摄像头所属事业部/公司无效" in message for message in errors)


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
@pytest.mark.parametrize("spec", [spec for spec in all_specs().values() if not spec.name.startswith("detect_logistics") and len(spec.alarm_types) == 1], ids=lambda spec: spec.name)
def test_all_features_use_camera_explicit_department(monkeypatch, department, spec):
    import AiVision.features._shared.consumer as module
    captured = []
    monkeypatch.setattr(module.alarm_dispatcher, "maybe_dispatch", lambda req, **_: captured.append(req))
    consumer = SimpleNamespace(feature_name=spec.name, spec=spec, frame_cache={},
        config_cache={1: {**spec.config_schema().value.model_dump(), "department": department}}, _should_alarm=lambda *_: True, _alarm_context=lambda *_: {})
    consumer._alarm_violation_type = MethodType(BaseFunctionConsumer._alarm_violation_type, consumer)
    BaseFunctionConsumer._handle_alarm(consumer, 1, [], np.zeros((4, 4, 3), np.uint8))
    assert len(captured) == 1
    assert captured[0].department == department
    assert captured[0].violation_type == spec.alarm_types[0]
    assert (captured[0].cooldown_subject_type, captured[0].cooldown_subject_id) == ("camera", "1")


@pytest.mark.parametrize("violation_type", [1, 2])
def test_composite_feature_identity_is_accepted_at_all_write_boundaries(monkeypatch, writer_db, violation_type):
    spec = replace(all_specs()["blocks"], name="composite", alarm_types=(1, 2))
    monkeypatch.setattr(registry, "_REGISTRY", registry._build_registry((spec,)))
    writer, factory, _ = writer_db
    values = identity() | {"feature_name": spec.name, "violation_type": violation_type}
    validate_alarm_identity(**values)
    assert request(**values).violation_type == violation_type
    with factory.begin() as session:
        session.add(AiAlarmEvent(image_path="composite.png", **values))
    assert writer.save_now(frame=np.zeros((4, 4, 3), np.uint8), camera_no="camera", **values).id
    writer.enqueue(frame=np.zeros((4, 4, 3), np.uint8), camera_no="camera", **values)
    assert not writer._queue.empty()
    with pytest.raises(ValueError, match="FeatureSpec"):
        validate_alarm_identity(**(values | {"violation_type": 3}))


@pytest.mark.parametrize("spec", all_specs().values(), ids=lambda spec: spec.name)
def test_alarm_identity_requires_feature_ownership(spec):
    for alarm_type in spec.alarm_types:
        validate_alarm_identity(alarm_type, spec.name, "research_institute")
    other_type = next(value for value in VIOLATION_TYPE_META if value not in spec.alarm_types)
    with pytest.raises(ValueError, match="FeatureSpec"):
        validate_alarm_identity(other_type, spec.name, "research_institute")


@pytest.mark.parametrize("alarm_types", [(), (1, 2)])
def test_consumer_requires_explicit_alarm_type_selection(monkeypatch, alarm_types):
    import AiVision.features._shared.consumer as module
    spec = replace(all_specs()["blocks"], name="composite", alarm_types=alarm_types)
    consumer = SimpleNamespace(feature_name=spec.name, spec=spec, frame_cache={},
        config_cache={1: {"department": "research_institute", "alarm_interval": 5}},
        _should_alarm=lambda *_: True, _alarm_context=lambda *_: {})
    consumer._alarm_violation_type = MethodType(BaseFunctionConsumer._alarm_violation_type, consumer)
    captured = []
    monkeypatch.setattr(module.alarm_dispatcher, "maybe_dispatch", lambda req, **_: captured.append(req))
    with pytest.raises(RuntimeError, match="复合 Feature 必须覆盖"):
        BaseFunctionConsumer._handle_alarm(consumer, 1, (True, {}), np.zeros((4, 4, 3), np.uint8))
    assert not captured


def test_composite_consumer_selects_type_from_event(monkeypatch):
    import AiVision.features._shared.consumer as module
    spec = replace(all_specs()["blocks"], name="composite", alarm_types=(1, 2))
    monkeypatch.setattr(registry, "_REGISTRY", registry._build_registry((spec,)))
    consumer = SimpleNamespace(feature_name=spec.name, spec=spec, frame_cache={},
        config_cache={1: {"department": "research_institute", "alarm_interval": 5}},
        _should_alarm=lambda *_: True, _alarm_context=lambda *_: {})
    consumer._alarm_violation_type = lambda camera_id, result, cfg: result[1]["alarm_type"]
    captured = []
    monkeypatch.setattr(module.alarm_dispatcher, "maybe_dispatch", lambda req, **_: captured.append(req))
    for alarm_type in spec.alarm_types:
        BaseFunctionConsumer._handle_alarm(consumer, 1, (True, {"alarm_type": alarm_type}), np.zeros((4, 4, 3), np.uint8))
    assert [req.violation_type for req in captured] == [1, 2]


@pytest.mark.parametrize("subject_type,subject_id,subject_name", [
    ("face_person", "17", "测试人员"), ("unknown_face", "", "未知人员"),
])
def test_face_business_subject_persists_independently_from_camera_cooldown(
    writer_db, subject_type, subject_id, subject_name,
):
    writer, factory, _ = writer_db
    req = request(violation_type=7, feature_name="recognize_face", department="research_institute",
                  subject_type=subject_type, subject_id=subject_id, subject_name=subject_name)
    assert AlarmDispatcher._cooldown_key(req) == ("camera", "1", 7)
    record = AlarmDispatcher._write_violation(writer.save_now, req)
    with factory() as session:
        row = session.get(AiAlarmEvent, record.id)
        assert (row.subject_type, row.subject_id, row.subject_name) == (subject_type, subject_id, subject_name)
        assert row.violation_type == 7


def test_channel_queries_use_feature_field_and_never_type_inference(writer_db):
    _, factory, _ = writer_db
    specs = [spec for spec in all_specs().values() if spec.name.startswith("detect_logistics")]
    with factory() as session:
        for spec in specs:
            session.add(AiAlarmEvent(violation_type=6, feature_name=spec.name, department="haoda_company",
                image_path=f"{spec.name}.png", subject_type="logistics_channel", subject_id="1", subject_name=spec.name))
        session.commit()
        # 各部门物流复用类型 6，查询仍必须严格按 feature_name 隔离。
        for spec in specs:
            rows = _channel_alarm_query(session, spec.name, 1).all()
            assert len(rows) == 1
            assert _alarm_dict(rows[0])["feature_name"] == spec.name
        # 用底层 SQL 模拟损坏记录；metadata 和 type 都不能替代缺失的正式字段。
        from sqlalchemy import text
        session.execute(text("UPDATE ai_violation_image SET feature_name = NULL WHERE feature_name = :feature"), {"feature": specs[0].name})
        session.commit()
        assert _channel_alarm_query(session, specs[0].name, 1).count() == 0


@pytest.mark.parametrize('violation_type', (8, 9, 10, 11))
def test_guard_site_identity_enters_shared_writer(writer_db, violation_type):
    writer, factory, _ = writer_db
    values = dict(violation_type=violation_type, feature_name='guard_behavior', department='general_electric',
                  subject_type='guard_behavior_site', subject_id='1', subject_name='南门保安室')
    req = AlarmRequest(camera_id=63, camera_name='南门', frame=np.zeros((4, 4, 3), np.uint8),
                       alarm_config={}, cooldown_subject_type='guard_behavior_site', cooldown_subject_id='1', **values)
    assert AlarmDispatcher()._cooldown_key(req) == ('guard_behavior_site', '1', violation_type)
    row = writer.save_now(frame=req.frame, camera_no='camera_63', **values)
    with factory() as session:
        record = session.get(AiAlarmEvent, row.id)
        assert record.violation_type == violation_type
        assert record.subject_type == 'guard_behavior_site' and record.subject_id == '1'
