"""
正式告警类型注册表。

orm.py存的是0，1，2...，  不是具体的检测功能，types.py的意义是将1对应成区域入侵，2对应成大门开关等

VIOLATION_TYPE_META 只描述告警性质；feature_name、department 由写入方明确提供并校验。
"""
from __future__ import annotations

from typing import TypedDict         # 告诉Python类型检查器，这个字典应该长这样


class AlarmTypeMeta(TypedDict):
    event_type: str                    # 比如detect_phone
    label: str                         # 比如手机检测


# 告警编号对应的事件类型与展示名称；合法编号以本注册表为准。
VIOLATION_TYPE_META: dict[int, AlarmTypeMeta] = {
    1: {"event_type": "blocks", "label": "区域入侵"},
    2: {"event_type": "detect_door", "label": "大门开关"},
    3: {"event_type": "detect_phone", "label": "手机检测"},
    4: {"event_type": "detect_face", "label": "人脸逗留检测"},
    5: {"event_type": "detect_human", "label": "人员违规逗留检测"},
    6: {"event_type": "detect_logistics_single_person", "label": "物流通道单人检测"},
    7: {"event_type": "recognize_face", "label": "人脸身份识别"},
    8: {"event_type": "guard_absent", "label": "保安离岗"},
    9: {"event_type": "guard_phone_use", "label": "保安玩手机"},
    10: {"event_type": "guard_prone_sleep", "label": "保安趴睡"},
    11: {"event_type": "guard_vehicle_inspection_missing", "label": "车辆出厂检查异常"},
    12: {"event_type": "security_inspection", "label": "安检流程不规范"},
    13: {"event_type": "agv_person_check", "label": "AGV运货区域有人"},
}

# 未知类型的默认显示信息
DEFAULT_ALARM_TYPE_META: AlarmTypeMeta = {
    "event_type": "unknown",
    "label": "未知报警",
}
