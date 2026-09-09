# 文件说明：包含告警、接口访问的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import importlib
from datetime import datetime
from types import SimpleNamespace

import pytest

from AiVision.platform.violation.orm import AiAlarmEvent


alarms = importlib.import_module("AiVision.api.alarms")


# 功能：实现 `_channel_row` 对应的告警、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `**overrides`（未显式标注）：`overrides` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_alarm_api.py` 的 `test_event_dict_and_response_schema_keep_channel_alarm_fields`
#         调用本符号；`AiVision/tests/test_alarm_api.py` 的 `test_event_dict_strictly_validates_both_camera_id_lists`
#         调用本符号；`AiVision/tests/test_alarm_api.py` 的 `test_event_dict_skips_oversized_camera_ids_without_response_failure` 调用本符号
#   - 内部调用：`datetime`、`values.update`、`SimpleNamespace`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _channel_row(**overrides):
    values = {
        "id": 42,
        "violation_type": 6,
        "feature_name": "detect_logistics_single_person",
        "department": "general_electric",
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


# 功能：验证 `test_event_dict_and_response_schema_keep_channel_alarm_fields` 对应的告警、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`alarms._event_dict`、`_channel_row`、`alarms.AlarmListResponse.model_validate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_event_dict_and_response_schema_keep_channel_alarm_fields():
    event = alarms._event_dict(_channel_row())
    response = alarms.AlarmListResponse.model_validate({"items": [event]})
    item = response.items[0]

    assert item.subject_type == "logistics_channel"
    assert item.subject_id == "3"
    assert item.subject_name == "一号物流通道"
    assert item.camera_no is None
    assert item.camera_name is None
    assert item.feature_name == "detect_logistics_single_person"
    assert item.department == "general_electric"
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
    assert item.image_url == "/api/alarms/42/image"


# 功能：验证 `test_event_dict_and_response_schema_use_camera_snapshot_fields` 对应的告警、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`SimpleNamespace`、`alarms._event_dict`、`alarms.AlarmListResponse.model_validate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_event_dict_and_response_schema_use_camera_snapshot_fields():
    row = SimpleNamespace(
        id=7,
        violation_type=5,
        feature_name="detect_human",
        department="general_electric",
        subject_type="camera",
        subject_id="7",
        subject_name="七号摄像头",
        camera_no="camera_7",
        create_time=None,
        image_path="/tmp/legacy.png",
    )
    event = alarms._event_dict(row)
    item = alarms.AlarmListResponse.model_validate({"items": [event]}).items[0]

    assert item.subject_type == "camera"
    assert item.subject_id == "7"
    assert item.subject_name == "七号摄像头"
    assert item.event_label == "人员违规逗留检测"
    assert item.camera_no == "camera_7"
    assert item.camera_name == "七号摄像头"
    assert item.feature_name == "detect_human"
    assert item.department == "general_electric"
    assert item.channel_id is None
    assert item.metadata == {}
    assert item.camera_ids == []


# 功能：验证 `test_event_dict_strictly_validates_both_camera_id_lists` 对应的告警、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`list`、`alarms._event_dict`、`_channel_row`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_event_dict_strictly_validates_both_camera_id_lists():
    raw_ids = [10.9, -1, 0, True, "10", "010", " 11 ", 11, "-2", "+3", "1e2", "", None]
    metadata = {
        "camera_ids": raw_ids,
        "offending_camera_ids": list(raw_ids),
    }

    event = alarms._event_dict(_channel_row(event_metadata=metadata))

    assert event["camera_ids"] == [10, 11]
    assert event["offending_camera_ids"] == [10, 11]


# 功能：验证 `test_event_dict_skips_oversized_camera_ids_without_response_failure` 对应的告警、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`str`、`_channel_row`、`list`、`alarms._event_dict`、`alarms.AlarmListResponse.model_validate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_event_dict_skips_oversized_camera_ids_without_response_failure():
    upper_bound = 2**31 - 1
    raw_ids = ["9" * 5000, upper_bound, str(upper_bound + 1)]
    row = _channel_row(event_metadata={
        "camera_ids": raw_ids,
        "offending_camera_ids": list(raw_ids),
    })

    event = alarms._event_dict(row)
    item = alarms.AlarmListResponse.model_validate({"items": [event]}).items[0]

    assert item.camera_ids == [upper_bound]
    assert item.offending_camera_ids == [upper_bound]


@pytest.mark.parametrize("unsupported_type", [7, 8, 9, 10])
def test_queries_do_not_recover_missing_ownership_from_old_types(unsupported_type):
    row = _channel_row(violation_type=unsupported_type, feature_name=None, department=None,
        event_metadata={"feature_name": "detect_human_haoda", "department": "haoda_company"})
    event = alarms._event_dict(row)
    assert event["violation_type"] == unsupported_type
    assert event["event_type"] == "unknown"
    assert event["feature_name"] is None
    assert event["department"] is None


def test_alarm_event_orm_renaming_keeps_historical_table_mapping():
    assert AiAlarmEvent.__tablename__ == "ai_violation_image"
    assert "feature_name" in AiAlarmEvent.__table__.columns
    assert "department" in AiAlarmEvent.__table__.columns


def test_backend_alarm_type_metadata_has_no_presentation_color():
    assert set(alarms._TYPE_META) == {1, 2, 3, 4, 5, 6}
    assert all("color" not in meta for meta in alarms._TYPE_META.values())


def test_alarm_statistics_uses_subject_contract_and_has_no_fake_week(monkeypatch):
    now = datetime.now()
    rows = [
        _channel_row(
            id=1,
            violation_type=6,
            feature_name="detect_logistics_single_person_electronics_electrician",
            department="electronics_electrician",
            create_time=now,
        ),
        _channel_row(id=2, create_time=now),
    ]

    class Query:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return rows

    class Session:
        def query(self, *_args):
            return Query()

        def close(self):
            return None

    monkeypatch.setattr(alarms, "get_session", Session)

    statistics = alarms.alarm_statistics(days=7)

    assert statistics["summary"]["total"] == 2
    assert statistics["summary"]["active_subjects"] == 1
    assert "week" not in statistics["summary"]
    assert "active_cameras" not in statistics["summary"]
    assert "by_camera" not in statistics
    assert statistics["by_subject"] == [{
        "subject_type": "logistics_channel",
        "subject_id": "3",
        "subject_name": "一号物流通道",
        "value": 2,
    }]
    assert statistics["by_type"] == [{
        "event_type": "detect_logistics_single_person",
        "name": "物流通道单人检测",
        "value": 2,
    }]
