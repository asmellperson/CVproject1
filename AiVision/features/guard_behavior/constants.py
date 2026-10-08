"""新建保安室的默认值；不读取部署配置或注册全局报警元数据。"""
from types import MappingProxyType

from AiVision.features._shared.defaults import CAP_INTERVAL


MAX_CAMERAS_PER_SITE = 9
MIN_MODEL_IMGSZ = 32
MAX_MODEL_IMGSZ = 4096

GUARD_ABSENT_VIOLATION_TYPE = 8
GUARD_PHONE_USE_VIOLATION_TYPE = 9
GUARD_PRONE_SLEEP_VIOLATION_TYPE = 10
GUARD_VEHICLE_INSPECTION_MISSING_VIOLATION_TYPE = 11
GUARD_ALARM_TYPES = (
    GUARD_ABSENT_VIOLATION_TYPE,
    GUARD_PHONE_USE_VIOLATION_TYPE,
    GUARD_PRONE_SLEEP_VIOLATION_TYPE,
    GUARD_VEHICLE_INSPECTION_MISSING_VIOLATION_TYPE,
)

SITE_POLICY_DEFAULTS = MappingProxyType({
    "cap_interval": CAP_INTERVAL,
    "person_confidence_threshold": 0.25,
    "phone_confidence_threshold": 0.35,
    "uniform_confidence_threshold": 0.80,
    "vehicle_confidence_threshold": 0.35,
    "model_iou_threshold": 0.45,
    "person_phone_imgsz": 960,
    "phone_crop_imgsz": 640,
    "pose_imgsz": 640,
    "vehicle_imgsz": 960,
    "guard_hold_seconds": 1.3,
    "absent_alarm_seconds": 60.0,
    "phone_seconds": 3.7,
    "phone_window_seconds": 5.0,
    "phone_min_hits_in_window": 5,
    "phone_grace_seconds": 3.0,
    "phone_near_person_px": 250,
    "phone_near_head_px": 160,
    "prone_sleep_seconds": 300.0,
    "static_motion_threshold": 8.0,
    "prone_head_down_ratio_threshold": 0.22,
    "prone_bbox_height_ratio_threshold": 0.18,
    "prone_consecutive_frames": 8,
    "state_ttl_seconds": 20.0,
    "vehicle_inspection_enabled": False,
    "vehicle_camera_id": None,
    "vehicle_occlusion_seconds": 2.0,
    "vehicle_near_px": 160,
    "vehicle_exit_direction": "any",
    "vehicle_direction_min_delta_ratio": 0.03,
    "vehicle_reassociate_seconds": 10.0,
})

ALARM_INTERVAL_DEFAULTS = MappingProxyType({
    GUARD_ABSENT_VIOLATION_TYPE: 540.0,
    GUARD_PHONE_USE_VIOLATION_TYPE: 1200.0,
    GUARD_PRONE_SLEEP_VIOLATION_TYPE: 300.0,
    GUARD_VEHICLE_INSPECTION_MISSING_VIOLATION_TYPE: 300.0,
})
ALARM_POLICY_DEFAULTS = MappingProxyType({
    "sql_enable": False,
    "horn_enable": False,
    "horn_id": None,
    "horn_event_id": None,
    "wechat_enable": False,
    "wechat_user": "",
})


def require_alarm_type(violation_type: int) -> int:
    """只接受保安室支持的整数告警类型，排除布尔值及其他业务类型。"""
    if type(violation_type) is not int or violation_type not in GUARD_ALARM_TYPES:
        raise ValueError("保安室报警类型必须属于 GUARD_ALARM_TYPES")
    return violation_type


def default_alarm_interval(context) -> float:
    """ORM 插入时按本行报警类型选择默认间隔。"""
    return ALARM_INTERVAL_DEFAULTS[require_alarm_type(context.get_current_parameters()["violation_type"])]
