# 文件说明：包含告警的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import sys
from datetime import datetime
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unified_backend.app import (  # noqa: E402
    ALARM_TYPE_META,
    DEPARTMENT_EVENT_TYPES,
    _build_alarm_statistics,
    _normalize_aivision_alarm,
)


LOGISTICS_FEATURES = (
    ("detect_logistics_single_person", "general_electric"),
    (
        "detect_logistics_single_person_electronics_electrician",
        "electronics_electrician",
    ),
    (
        "detect_logistics_single_person_electrical_components",
        "electrical_components",
    ),
    (
        "detect_logistics_single_person_precious_metal_recycling",
        "precious_metal_recycling",
    ),
)


# 功能：实现 `_channel_alarm` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `**overrides`（未显式标注）：`overrides` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_logistics_channel_alarms.py` 的
#         `test_aivision_channel_alarm_keeps_channel_identity_and_evidence`
#         调用本符号；`unified_backend/tests/test_logistics_channel_alarms.py` 的 `test_malformed_channel_metadata_degrades_safely`
#         调用本符号；`unified_backend/tests/test_logistics_channel_alarms.py` 的
#         `test_malformed_nested_channel_metadata_does_not_leak_invalid_shapes`
#         调用本符号；`unified_backend/tests/test_logistics_channel_alarms.py` 的
#         `test_camera_id_metadata_only_accepts_unique_positive_decimal_ids` 调用本符号；另有 3 处静态调用
#   - 内部调用：`datetime.now().isoformat`、`datetime.now`、`alarm.update`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _channel_alarm(**overrides):
    alarm = {
        "id": "42",
        "event_type": "detect_logistics_single_person",
        "event_label": "物流通道单人检测",
        "subject_type": "logistics_channel",
        "subject_id": "3",
        "subject_name": "一号物流通道",
        "reason": "multiple",
        "created_at": datetime.now().isoformat(sep=" "),
        "metadata": {
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
    }
    alarm.update(overrides)
    return alarm


# 功能：验证 `test_aivision_channel_alarm_keeps_channel_identity_and_evidence` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_normalize_aivision_alarm`、`_channel_alarm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_aivision_channel_alarm_keeps_channel_identity_and_evidence():
    normalized = _normalize_aivision_alarm(_channel_alarm())

    assert normalized["id"] == "aivision:42"
    assert normalized["subject_type"] == "logistics_channel"
    assert normalized["subject_id"] == "3"
    assert normalized["camera_no"] == "logistics_channel_3"
    assert normalized["camera_name"] == "一号物流通道"
    assert normalized["channel_id"] == "3"
    assert normalized["channel_name"] == "一号物流通道"
    assert normalized["reason"] == "multiple"
    assert normalized["status"] == "multiple"
    assert normalized["camera_ids"] == [10, 11]
    assert normalized["camera_names"] == {"10": "东侧", "11": "西侧"}
    assert normalized["camera_counts"] == {"10": 2, "11": 1}
    assert normalized["camera_states"]["10"]["status"] == "multiple"
    assert normalized["offending_camera_ids"] == [10]
    assert normalized["evidence_error"] == "channel_frame_unavailable"
    assert normalized["metadata"]["channel_id"] == 3


# 功能：验证 `test_legacy_camera_alarm_contract_remains_compatible` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_normalize_aivision_alarm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_legacy_camera_alarm_contract_remains_compatible():
    normalized = _normalize_aivision_alarm({
        "id": "7",
        "event_type": "detect_human",
        "camera_no": "camera_7",
        "camera_name": "七号摄像头",
        "reason": "人体逗留 - 七号摄像头",
    })

    assert normalized["id"] == "aivision:7"
    assert normalized["source_id"] == "7"
    assert normalized["camera_no"] == "camera_7"
    assert normalized["camera_name"] == "七号摄像头"
    assert normalized["reason"] == "人体逗留 - 七号摄像头"
    assert normalized["image_url"] == "/api/aivision/alarms/7/image"
    assert normalized["video_url"] is None
    assert normalized["metadata"] == {}
    assert normalized["channel_id"] is None


# 功能：验证 `test_human_dwell_alarm_names_are_consistent_across_departments` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_human_dwell_alarm_names_are_consistent_across_departments():
    assert ALARM_TYPE_META["detect_human"]["name"] == "人员违规逗留检测"
    assert ALARM_TYPE_META["detect_human_haoda"]["name"] == "人员违规逗留检测（皓达公司）"


# 功能：验证 `test_malformed_channel_metadata_degrades_safely` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `metadata`（未显式标注）：`metadata` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_normalize_aivision_alarm`、`_channel_alarm`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("metadata", [None, "broken", [], 17])
def test_malformed_channel_metadata_degrades_safely(metadata):
    normalized = _normalize_aivision_alarm(_channel_alarm(metadata=metadata))

    assert normalized["metadata"] == {}
    assert normalized["camera_ids"] == []
    assert normalized["camera_names"] == {}
    assert normalized["camera_counts"] == {}
    assert normalized["camera_states"] == {}
    assert normalized["offending_camera_ids"] == []
    assert normalized["camera_name"] == "一号物流通道"


# 功能：验证 `test_malformed_nested_channel_metadata_does_not_leak_invalid_shapes` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_normalize_aivision_alarm`、`_channel_alarm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_malformed_nested_channel_metadata_does_not_leak_invalid_shapes():
    normalized = _normalize_aivision_alarm(_channel_alarm(metadata={
        "channel_id": 3,
        "camera_ids": "10,11",
        "camera_names": ["东侧"],
        "camera_counts": [2, 1],
        "camera_states": {"10": "multiple", "11": {"status": "normal"}},
        "offending_camera_ids": {10},
    }))

    assert normalized["camera_ids"] == []
    assert normalized["camera_names"] == {}
    assert normalized["camera_counts"] == {}
    assert normalized["camera_states"] == {"11": {"status": "normal"}}
    assert normalized["offending_camera_ids"] == []


# 功能：验证 `test_camera_id_metadata_only_accepts_unique_positive_decimal_ids` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `subject_type`（未显式标注）：`subject_type` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_normalize_aivision_alarm`、`_channel_alarm`、`list`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("subject_type", ["logistics_channel", "camera"])
def test_camera_id_metadata_only_accepts_unique_positive_decimal_ids(subject_type):
    raw_ids = [10.9, -1, 0, True, "10", "010", " 11 ", 11, "-2", "+3", "1e2", "", None]
    normalized = _normalize_aivision_alarm(_channel_alarm(
        subject_type=subject_type,
        metadata={
            "channel_id": 3,
            "camera_ids": raw_ids,
            "offending_camera_ids": list(raw_ids),
        },
    ))

    assert normalized["camera_ids"] == [10, 11]
    assert normalized["offending_camera_ids"] == [10, 11]


# 功能：验证 `test_oversized_camera_id_metadata_degrades_without_failure` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `subject_type`（未显式标注）：`subject_type` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`str`、`_normalize_aivision_alarm`、`_channel_alarm`、`list`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("subject_type", ["logistics_channel", "camera"])
def test_oversized_camera_id_metadata_degrades_without_failure(subject_type):
    upper_bound = 2**31 - 1
    raw_ids = ["9" * 5000, upper_bound, str(upper_bound + 1)]

    normalized = _normalize_aivision_alarm(_channel_alarm(
        subject_type=subject_type,
        metadata={
            "channel_id": 3,
            "camera_ids": raw_ids,
            "offending_camera_ids": list(raw_ids),
        },
    ))

    assert normalized["camera_ids"] == [upper_bound]
    assert normalized["offending_camera_ids"] == [upper_bound]


# 功能：验证 `test_all_logistics_alarm_features_have_type_and_department_mapping` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
#   - `department`（未显式标注）：业务部门名称或标识
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_normalize_aivision_alarm`、`_channel_alarm`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(("feature_name", "department"), LOGISTICS_FEATURES)
def test_all_logistics_alarm_features_have_type_and_department_mapping(
    feature_name,
    department,
):
    normalized = _normalize_aivision_alarm(
        _channel_alarm(event_type=feature_name)
    )

    assert normalized["event_type"] == feature_name
    assert feature_name in DEPARTMENT_EVENT_TYPES[department]


# 功能：验证 `test_statistics_group_channel_alarms_by_channel_subject` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_normalize_aivision_alarm`、`_channel_alarm`、`_build_alarm_statistics`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_statistics_group_channel_alarms_by_channel_subject():
    first = _normalize_aivision_alarm(_channel_alarm(id="1"))
    second = _normalize_aivision_alarm(_channel_alarm(id="2", reason="empty"))

    statistics = _build_alarm_statistics([first, second], days=1)

    assert statistics["summary"]["total"] == 2
    assert statistics["summary"]["active_cameras"] == 1
    assert statistics["by_camera"] == [
        {
            "camera_no": "logistics_channel_3",
            "name": "一号物流通道",
            "value": 2,
        }
    ]
    assert statistics["by_type"][0]["event_type"] == (
        "detect_logistics_single_person"
    )
