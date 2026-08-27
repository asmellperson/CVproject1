import importlib
import sys
from datetime import datetime
from types import SimpleNamespace


sys.modules.pop("platform", None)
alarms = importlib.import_module("api.v2.alarms")


def _channel_row(**overrides):
    values = {
        "id": 42,
        "violation_type": 6,
        "camera_no": "logistics_channel:detect_logistics_single_person:3",
        "subject_type": "logistics_channel",
        "subject_id": "3",
        "subject_name": "一号物流通道",
        "reason": "multiple",
        "event_metadata": {
            "channel_id": 3,
            "channel_name": "一号物流通道",
            "camera_ids": [10, 11],
            "camera_counts": {"10": 2, "11": 1},
            "camera_states": {
                "10": {"camera_name": "东侧", "status": "multiple"},
                "11": {"camera_name": "西侧", "status": "normal"},
            },
            "offending_camera_ids": [10],
            "evidence_error": "channel_frame_unavailable",
        },
        "create_time": datetime(2026, 8, 7, 12, 0),
        "image_path": "/tmp/channel.png",
        "video_path": "/tmp/channel.mp4",
        "video_status": "ready",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_event_dict_and_response_schema_keep_channel_alarm_fields():
    event = alarms._event_dict(_channel_row(), {})
    response = alarms.AlarmListResponse.model_validate({"items": [event]})
    item = response.items[0]

    assert item.subject_type == "logistics_channel"
    assert item.subject_id == "3"
    assert item.subject_name == "一号物流通道"
    assert item.camera_no == "logistics_channel_3"
    assert item.camera_name == "一号物流通道"
    assert item.channel_id == "3"
    assert item.channel_name == "一号物流通道"
    assert item.reason == "multiple"
    assert item.status == "multiple"
    assert item.camera_ids == [10, 11]
    assert item.camera_names == {"10": "东侧", "11": "西侧"}
    assert item.camera_counts == {"10": 2, "11": 1}
    assert item.offending_camera_ids == [10]
    assert item.evidence_error == "channel_frame_unavailable"
    assert item.video_path == "/tmp/channel.mp4"
    assert item.video_status == "ready"


def test_event_dict_and_response_schema_keep_legacy_camera_fallbacks():
    row = SimpleNamespace(
        id=7,
        violation_type=5,
        camera_no="camera_7",
        create_time=None,
        image_path="/tmp/legacy.png",
    )
    event = alarms._event_dict(row, {"camera_7": "七号摄像头"})
    item = alarms.AlarmListResponse.model_validate({"items": [event]}).items[0]

    assert item.subject_type == "camera"
    assert item.subject_id == "camera_7"
    assert item.subject_name == "七号摄像头"
    assert item.event_label == "人员违规逗留检测"
    assert item.camera_no == "camera_7"
    assert item.camera_name == "七号摄像头"
    assert item.channel_id is None
    assert item.metadata == {}
    assert item.camera_ids == []


def test_event_dict_strictly_validates_both_camera_id_lists():
    raw_ids = [10.9, -1, 0, True, "10", "010", " 11 ", 11, "-2", "+3", "1e2", "", None]
    metadata = {
        "camera_ids": raw_ids,
        "offending_camera_ids": list(raw_ids),
    }

    event = alarms._event_dict(_channel_row(event_metadata=metadata), {})

    assert event["camera_ids"] == [10, 11]
    assert event["offending_camera_ids"] == [10, 11]


def test_event_dict_skips_oversized_camera_ids_without_response_failure():
    upper_bound = 2**31 - 1
    raw_ids = ["9" * 5000, upper_bound, str(upper_bound + 1)]
    row = _channel_row(event_metadata={
        "camera_ids": raw_ids,
        "offending_camera_ids": list(raw_ids),
    })

    event = alarms._event_dict(row, {})
    item = alarms.AlarmListResponse.model_validate({"items": [event]}).items[0]

    assert item.camera_ids == [upper_bound]
    assert item.offending_camera_ids == [upper_bound]
