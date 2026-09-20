"""网关保留 AiVision 正式报警语义，处置和统计不重建报警字段。"""
from copy import deepcopy
from datetime import datetime

import pytest

from AiVision.api.routes.alarms import AlarmEventResponse, _event_dict
from AiVision.alarms.records.orm import AiAlarmEvent
from AiVision.departments.department_registry import DEPARTMENT_SPECS
from unified_backend.app import _build_alarm_statistics, _filter_alarms, _normalize_aivision_alarm


def native_alarm(**overrides):
    values = dict(
        id=42, violation_type=6, feature_name="detect_logistics_single_person",
        department="general_electric", subject_type="logistics_channel", subject_id="3",
        subject_name="一号物流通道", reason="multiple", create_time=datetime.now(),
        image_path="evidence.jpg", video_status="ready",
        event_metadata={
            "channel_id": 3, "channel_name": "一号物流通道", "camera_ids": [10, 11],
            "camera_counts": {"10": 2, "11": 1},
            "camera_states": {
                "10": {"camera_name": "东侧", "status": "multiple"},
                "11": {"camera_name": "西侧", "status": "normal"},
            },
            "offending_camera_ids": [10], "evidence_error": "channel_frame_unavailable",
        },
    )
    values.update(overrides)
    return AlarmEventResponse.model_validate(_event_dict(AiAlarmEvent(**values))).model_dump()


@pytest.mark.parametrize("video_status", [None, "pending", "ready", "failed"])
def test_channel_alarm_preserves_every_native_field(video_status):
    alarm = native_alarm(video_status=video_status)
    before = deepcopy(alarm)
    result = _normalize_aivision_alarm(alarm)

    assert alarm == before
    assert {key: result[key] for key in alarm if key != "id"} == {
        key: value for key, value in alarm.items() if key != "id"
    }
    assert result["id"] == "aivision:42" and result["source_id"] == "42"
    assert result["source"] == "aivision"
    assert result["video_url"] == ("/api/alarms/42/video" if video_status == "ready" else None)
    assert result["camera_names"] == {"10": "东侧", "11": "西侧"}
    assert result["offending_camera_ids"] == [10]


@pytest.mark.parametrize("subject_type,feature,violation", [
    ("camera", "detect_human", 5),
    ("guard_site", "guard_behavior", 8),
    ("security_inspection_roi", "security_inspection", 12),
    ("face_person", "recognize_face", 7),
    ("unknown_face", "recognize_face", 7),
])
def test_native_subject_and_camera_are_not_rewritten(subject_type, feature, violation):
    alarm = native_alarm(
        subject_type=subject_type, subject_id="7:station-one", subject_name="检测主体",
        violation_type=violation, feature_name=feature, camera_no="camera_7",
        event_metadata={"camera_name": "七号摄像头"},
    )
    result = _normalize_aivision_alarm(alarm)
    for field in ("subject_type", "subject_id", "subject_name", "camera_no", "camera_name", "reason"):
        assert result[field] == alarm[field]


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_department_filter_preserves_alarm_ownership(department):
    alarms = [_normalize_aivision_alarm(native_alarm(id=index + 1, department=scope))
              for index, scope in enumerate(DEPARTMENT_SPECS)]
    visible = _filter_alarms(alarms, user={"role": "viewer", "departments": [department]})
    assert len(visible) == 1
    assert visible[0]["department"] == department
    assert visible[0]["event_type"] == visible[0]["feature_name"] == "detect_logistics_single_person"


def test_statistics_use_native_label_and_subject():
    alarms = [_normalize_aivision_alarm(native_alarm(id=number)) for number in (1, 2)]
    for alarm in alarms:
        alarm["event_label"] = "上游提供的名称"
    stats = _build_alarm_statistics(alarms, days=1)
    assert stats["summary"]["total"] == 2 and stats["summary"]["active_subjects"] == 1
    assert stats["by_type"] == [{"event_type": "detect_logistics_single_person", "name": "上游提供的名称", "value": 2}]
    assert stats["by_subject"] == [{
        "subject_type": "logistics_channel", "subject_id": "3", "subject_name": "一号物流通道", "value": 2,
    }]


def test_gateway_does_not_reconstruct_fields_from_metadata():
    alarm = native_alarm()
    alarm.update(subject_id=None, subject_name=None, channel_name=None, reason="", camera_names={})
    result = _normalize_aivision_alarm(alarm)
    for field in ("subject_id", "subject_name", "channel_name", "reason", "camera_names"):
        assert result[field] == alarm[field]
