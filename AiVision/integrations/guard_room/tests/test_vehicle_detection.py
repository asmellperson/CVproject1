# 文件说明：包含`test_vehicle_detection` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import AppConfig
from src.db import configure_for_tests
from src.runtime import GuardRoomRuntime
from src.service import GuardRoomService
from src.types import Detection
from src.vehicle_behavior import VehicleBehaviorEngine


# 功能：验证 `test_site_config_persists_vehicle_detector_model_from_db` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`configure_for_tests`、`GuardRoomService`、`service.ensure_schema`、`service.create_site`、`service.build_app_config`、`isinstance`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_site_config_persists_vehicle_detector_model_from_db(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_vehicle.db'}")
    service = GuardRoomService()
    service.ensure_schema()

    site = service.create_site(
        "车辆检测保安室",
        config={"models": {"vehicle_detector_model": "models/yolo11n.pt"}},
    )
    cfg = service.build_app_config(site["id"])

    assert isinstance(cfg, AppConfig)
    assert cfg.models.vehicle_detector_model == "models/yolo11n.pt"


# 功能：验证 `test_site_config_persists_vehicle_camera_and_roi_from_db` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`configure_for_tests`、`GuardRoomService`、`service.ensure_schema`、`service.create_site`、`service.build_app_config`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_site_config_persists_vehicle_camera_and_roi_from_db(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_vehicle_roi.db'}")
    service = GuardRoomService()
    service.ensure_schema()

    site = service.create_site(
        "车辆 ROI 保安室",
        config={
            "runtime": {"vehicle_camera_id": "cam2"},
            "rules": {
                "vehicle_roi": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]],
                "vehicle_exit_direction": "right",
                "vehicle_direction_min_delta_ratio": 0.05,
                "vehicle_reassociate_seconds": 12,
            },
        },
    )
    cfg = service.build_app_config(site["id"])

    assert cfg.runtime.vehicle_camera_id == "cam2"
    assert cfg.rules.vehicle_roi == [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]]
    assert cfg.rules.vehicle_exit_direction == "right"
    assert cfg.rules.vehicle_direction_min_delta_ratio == 0.05
    assert cfg.rules.vehicle_reassociate_seconds == 12


# 功能：验证 `test_vehicle_behavior_does_not_alarm_when_guard_appears_before_vehicle_leaves` 对应的`test_vehicle_detection`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`VehicleBehaviorEngine`、`Detection`、`engine.update`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vehicle_behavior_does_not_alarm_when_guard_appears_before_vehicle_leaves():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_near_px = 80
    engine = VehicleBehaviorEngine(cfg)

    guard = Detection(cls_id=cfg.classes.person, conf=0.92, bbox=(220, 160, 280, 360), track_id=7)
    vehicle = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(300, 130, 620, 420), track_id=None)

    assert engine.update(
        timestamp_s=0.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[vehicle],
    ).active is False

    assert engine.update(
        timestamp_s=1.0,
        frame_shape=(720, 1280, 3),
        guards=[guard],
        vehicles=[vehicle],
    ).active is False

    assert engine.update(
        timestamp_s=2.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False


# 功能：验证 `test_vehicle_behavior_keeps_checked_state_after_short_vehicle_detection_drop` 对应的`test_vehicle_detection`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`VehicleBehaviorEngine`、`Detection`、`engine.update`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vehicle_behavior_keeps_checked_state_after_short_vehicle_detection_drop():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_exit_direction = "right"
    cfg.rules.vehicle_near_px = 80
    cfg.rules.vehicle_occlusion_seconds = 2.0
    engine = VehicleBehaviorEngine(cfg)

    guard = Detection(cls_id=cfg.classes.person, conf=0.92, bbox=(220, 160, 280, 360), track_id=7)
    checked = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(300, 130, 540, 420), track_id=None)
    reappeared = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(650, 130, 890, 420), track_id=None)
    leaving = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(850, 130, 1090, 420), track_id=None)

    assert engine.update(
        timestamp_s=0.0,
        frame_shape=(720, 1280, 3),
        guards=[guard],
        vehicles=[checked],
    ).active is False
    assert engine.update(
        timestamp_s=3.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False
    assert engine.update(
        timestamp_s=5.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    assert engine.update(
        timestamp_s=6.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[reappeared],
    ).active is False
    assert engine.update(
        timestamp_s=7.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[leaving],
    ).active is False
    assert engine.update(
        timestamp_s=9.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    decision = engine.update(
        timestamp_s=11.4,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    )

    assert decision.active is False


# 功能：验证 `test_vehicle_behavior_reassociates_checked_vehicle_that_reappears_along_exit_direction` 对应的`test_vehicle_detection`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`VehicleBehaviorEngine`、`Detection`、`engine.update`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vehicle_behavior_reassociates_checked_vehicle_that_reappears_along_exit_direction():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_exit_direction = "right"
    cfg.rules.vehicle_near_px = 80
    cfg.rules.vehicle_occlusion_seconds = 2.0
    engine = VehicleBehaviorEngine(cfg)

    guard = Detection(cls_id=cfg.classes.person, conf=0.92, bbox=(220, 160, 280, 360), track_id=7)
    checked = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(300, 130, 540, 420), track_id=None)
    reappeared = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(900, 130, 1140, 420), track_id=None)
    leaving = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(980, 130, 1220, 420), track_id=None)

    assert engine.update(
        timestamp_s=0.0,
        frame_shape=(720, 1280, 3),
        guards=[guard],
        vehicles=[checked],
    ).active is False
    assert engine.update(
        timestamp_s=3.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False
    assert engine.update(
        timestamp_s=5.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    assert engine.update(
        timestamp_s=6.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[reappeared],
    ).active is False
    assert engine.update(
        timestamp_s=7.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[leaving],
    ).active is False
    assert engine.update(
        timestamp_s=9.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    decision = engine.update(
        timestamp_s=11.4,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    )

    assert decision.active is False


# 功能：验证 `test_vehicle_behavior_does_not_reuse_checked_state_after_reassociate_window` 对应的`test_vehicle_detection`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`VehicleBehaviorEngine`、`Detection`、`engine.update`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vehicle_behavior_does_not_reuse_checked_state_after_reassociate_window():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_exit_direction = "right"
    cfg.rules.vehicle_near_px = 80
    cfg.rules.vehicle_occlusion_seconds = 2.0
    cfg.rules.vehicle_reassociate_seconds = 1.0
    engine = VehicleBehaviorEngine(cfg)

    guard = Detection(cls_id=cfg.classes.person, conf=0.92, bbox=(220, 160, 280, 360), track_id=7)
    checked = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(300, 130, 540, 420), track_id=None)
    reappeared = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(650, 130, 890, 420), track_id=None)
    leaving = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(850, 130, 1090, 420), track_id=None)

    assert engine.update(
        timestamp_s=0.0,
        frame_shape=(720, 1280, 3),
        guards=[guard],
        vehicles=[checked],
    ).active is False
    assert engine.update(
        timestamp_s=3.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False
    assert engine.update(
        timestamp_s=5.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    assert engine.update(
        timestamp_s=7.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[reappeared],
    ).active is False
    assert engine.update(
        timestamp_s=8.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[leaving],
    ).active is False
    assert engine.update(
        timestamp_s=10.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    decision = engine.update(
        timestamp_s=12.4,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    )

    assert decision.active is True
    assert "车辆停留期间未见保安靠近" in decision.reason


# 功能：验证 `test_vehicle_behavior_alarms_when_vehicle_leaves_without_guard_nearby` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`VehicleBehaviorEngine`、`Detection`、`engine.update`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vehicle_behavior_alarms_when_vehicle_leaves_without_guard_nearby():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_near_px = 80
    engine = VehicleBehaviorEngine(cfg)

    vehicle = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(300, 130, 620, 420), track_id=None)

    assert engine.update(
        timestamp_s=0.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[vehicle],
    ).active is False

    assert engine.update(
        timestamp_s=4.5,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    decision = engine.update(
        timestamp_s=6.6,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    )

    assert decision.active is True
    assert decision.track_id is None
    assert "车辆停留期间未见保安靠近" in decision.reason


# 功能：验证 `test_vehicle_behavior_ignores_vehicle_moving_against_configured_exit_direction` 对应的`test_vehicle_detection`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`VehicleBehaviorEngine`、`Detection`、`engine.update`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vehicle_behavior_ignores_vehicle_moving_against_configured_exit_direction():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_exit_direction = "right"
    engine = VehicleBehaviorEngine(cfg)

    entering_start = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(700, 130, 940, 420), track_id=None)
    entering_end = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(300, 130, 540, 420), track_id=None)

    assert engine.update(
        timestamp_s=0.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[entering_start],
    ).active is False
    assert engine.update(
        timestamp_s=1.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[entering_end],
    ).active is False

    assert engine.update(
        timestamp_s=4.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    decision = engine.update(
        timestamp_s=6.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    )

    assert decision.active is False


# 功能：验证 `test_vehicle_behavior_alarms_for_configured_exit_direction` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`VehicleBehaviorEngine`、`Detection`、`engine.update`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vehicle_behavior_alarms_for_configured_exit_direction():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_exit_direction = "right"
    cfg.rules.vehicle_near_px = 80
    engine = VehicleBehaviorEngine(cfg)

    exit_start = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(300, 130, 540, 420), track_id=None)
    exit_end = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(700, 130, 940, 420), track_id=None)

    assert engine.update(
        timestamp_s=0.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[exit_start],
    ).active is False
    assert engine.update(
        timestamp_s=1.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[exit_end],
    ).active is False

    assert engine.update(
        timestamp_s=4.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    decision = engine.update(
        timestamp_s=6.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    )

    assert decision.active is True
    assert "车辆停留期间未见保安靠近" in decision.reason


# 功能：验证 `test_vehicle_behavior_uses_vertical_exit_direction_for_gate_top_camera` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`VehicleBehaviorEngine`、`Detection`、`engine.update`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vehicle_behavior_uses_vertical_exit_direction_for_gate_top_camera():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_exit_direction = "down"
    engine = VehicleBehaviorEngine(cfg)

    entering_start = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(480, 520, 760, 700), track_id=None)
    entering_end = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(480, 180, 760, 360), track_id=None)
    assert engine.update(
        timestamp_s=0.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[entering_start],
    ).active is False
    assert engine.update(
        timestamp_s=1.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[entering_end],
    ).active is False
    assert engine.update(
        timestamp_s=4.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False
    assert engine.update(
        timestamp_s=6.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    exit_start = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(480, 180, 760, 360), track_id=None)
    exit_end = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(480, 520, 760, 700), track_id=None)
    assert engine.update(
        timestamp_s=10.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[exit_start],
    ).active is False
    assert engine.update(
        timestamp_s=11.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[exit_end],
    ).active is False
    assert engine.update(
        timestamp_s=14.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    decision = engine.update(
        timestamp_s=16.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    )

    assert decision.active is True


# 功能：验证 `test_vehicle_behavior_does_not_merge_entering_vehicle_with_unrelated_bottom_detection` 对应的`test_vehicle_detection`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`VehicleBehaviorEngine`、`Detection`、`engine.update`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vehicle_behavior_does_not_merge_entering_vehicle_with_unrelated_bottom_detection():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_exit_direction = "down"
    engine = VehicleBehaviorEngine(cfg)

    entering_start = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(480, 520, 760, 700), track_id=None)
    entering_end = Detection(cls_id=cfg.classes.vehicle_car, conf=0.88, bbox=(480, 160, 760, 340), track_id=None)
    unrelated_bottom = Detection(cls_id=cfg.classes.vehicle_car, conf=0.9, bbox=(360, 600, 960, 715), track_id=None)

    assert engine.update(
        timestamp_s=0.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[entering_start],
    ).active is False
    assert engine.update(
        timestamp_s=1.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[entering_end],
    ).active is False
    assert engine.update(
        timestamp_s=2.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[unrelated_bottom],
    ).active is False
    assert engine.update(
        timestamp_s=5.0,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    ).active is False

    decision = engine.update(
        timestamp_s=7.2,
        frame_shape=(720, 1280, 3),
        guards=[],
        vehicles=[],
    )

    assert decision.active is False


# 功能：验证 `test_detect_vehicles_filters_configured_coco_vehicle_classes` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`GuardRoomRuntime`、`__import__('numpy').zeros`、`__import__`、`runtime._detect_vehicles`、`FakeDetector`、`Detection`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_detect_vehicles_filters_configured_coco_vehicle_classes():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    runtime = GuardRoomRuntime(config=cfg, state=None)

    # 功能：定义 `FakeTensor` 类，封装`test_vehicle_detection` 模块相关的状态、约束与操作
    # 参数：
    #   - `value`（未显式标注）：待转换、校验或写入的值
    # 返回：FakeTensor；返回新建的 `FakeTensor` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
    #         `test_detect_vehicles_filters_configured_coco_vehicle_classes::FakeBoxes` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeTensor:
        # 功能：初始化或配置 `__init__` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `value`（未显式标注）：待转换、校验或写入的值
        # 返回：None；初始化当前实例，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：会更新当前实例的运行状态。
        def __init__(self, value):
            self.value = value

        # 功能：实现 `cpu` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：`AiVision/integrations/guard_room/src/pose.py` 的 `PoseEstimator::infer_frame`
        #         调用本符号；`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_detect_main`
        #         调用本符号；`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_detect_phones_in_person_regions`
        #         调用本符号；`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_detect_phones_full_frames_batch`
        #         调用本符号；另有 3 处静态调用
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def cpu(self):
            return self

        # 功能：实现 `numpy` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：`AiVision/platform/inference/workers/yolo_detector.py` 的 `YoloDetectorWorker::infer` 调用本符号
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def numpy(self):
            return self.value

    # 功能：定义 `FakeBoxes` 类，封装`test_vehicle_detection` 模块相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeBoxes；返回新建的 `FakeBoxes` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
    #         `test_detect_vehicles_filters_configured_coco_vehicle_classes::FakeResult` 实例化本符号
    #   - 内部调用：`FakeTensor`、`__import__('numpy').array`、`__import__`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeBoxes:
        xyxy = FakeTensor(
            __import__("numpy").array(
                [
                    [10, 20, 110, 120],
                    [200, 220, 260, 300],
                ]
            )
        )
        conf = FakeTensor(__import__("numpy").array([0.9, 0.4]))
        cls = FakeTensor(__import__("numpy").array([cfg.classes.vehicle_car, cfg.classes.person]))

    # 功能：定义 `FakeResult` 类，封装`test_vehicle_detection` 模块相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeResult；返回新建的 `FakeResult` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
    #         `test_detect_vehicles_filters_configured_coco_vehicle_classes::FakeDetector::predict` 实例化本符号
    #   - 内部调用：`FakeBoxes`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeResult:
        boxes = FakeBoxes()

    # 功能：定义 `FakeDetector` 类，封装`test_vehicle_detection` 模块相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeDetector；返回新建的 `FakeDetector` 实例。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeDetector:
        # 功能：实现 `predict` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`FakeResult`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def predict(self, **kwargs):
            assert kwargs["classes"] == [
                cfg.classes.vehicle_bicycle,
                cfg.classes.vehicle_car,
                cfg.classes.vehicle_motorcycle,
            ]
            return [FakeResult()]

    frame = __import__("numpy").zeros((480, 640, 3), dtype=__import__("numpy").uint8)

    vehicles = runtime._detect_vehicles(FakeDetector(), frame)

    assert vehicles == [
        Detection(cls_id=cfg.classes.vehicle_car, conf=0.9, bbox=(10, 20, 110, 120), track_id=None)
    ]


# 功能：验证 `test_vehicle_detection_runs_only_on_configured_camera` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`GuardRoomRuntime`、`runtime._vehicle_detection_enabled_for_camera`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vehicle_detection_runs_only_on_configured_camera():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.runtime.vehicle_camera_id = "cam2"
    runtime = GuardRoomRuntime(config=cfg, state=None)

    assert runtime._vehicle_detection_enabled_for_camera("cam1") is False
    assert runtime._vehicle_detection_enabled_for_camera("cam2") is True


# 功能：验证 `test_filter_vehicles_by_roi_ignores_unrelated_vehicles` 对应的`test_vehicle_detection` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig.from_yaml`、`Path(__file__).resolve`、`Path`、`GuardRoomRuntime`、`Detection`、`runtime._filter_vehicles_by_roi`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_filter_vehicles_by_roi_ignores_unrelated_vehicles():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_roi = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]
    runtime = GuardRoomRuntime(config=cfg, state=None)

    inside = Detection(cls_id=cfg.classes.vehicle_car, conf=0.9, bbox=(180, 160, 240, 240), track_id=None)
    outside = Detection(cls_id=cfg.classes.vehicle_car, conf=0.9, bbox=(10, 10, 80, 80), track_id=None)

    assert runtime._filter_vehicles_by_roi([inside, outside], (400, 400, 3)) == [inside]
