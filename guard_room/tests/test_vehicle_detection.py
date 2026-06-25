import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import AppConfig
from src.db import configure_for_tests
from src.runtime import GuardRoomRuntime
from src.service import GuardRoomService
from src.types import Detection
from src.vehicle_behavior import VehicleBehaviorEngine


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
            },
        },
    )
    cfg = service.build_app_config(site["id"])

    assert cfg.runtime.vehicle_camera_id == "cam2"
    assert cfg.rules.vehicle_roi == [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]]
    assert cfg.rules.vehicle_exit_direction == "right"
    assert cfg.rules.vehicle_direction_min_delta_ratio == 0.05


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


def test_detect_vehicles_filters_configured_coco_vehicle_classes():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    runtime = GuardRoomRuntime(config=cfg, state=None)

    class FakeTensor:
        def __init__(self, value):
            self.value = value

        def cpu(self):
            return self

        def numpy(self):
            return self.value

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

    class FakeResult:
        boxes = FakeBoxes()

    class FakeDetector:
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


def test_vehicle_detection_runs_only_on_configured_camera():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.runtime.vehicle_camera_id = "cam2"
    runtime = GuardRoomRuntime(config=cfg, state=None)

    assert runtime._vehicle_detection_enabled_for_camera("cam1") is False
    assert runtime._vehicle_detection_enabled_for_camera("cam2") is True


def test_filter_vehicles_by_roi_ignores_unrelated_vehicles():
    cfg = AppConfig.from_yaml(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml")
    cfg.rules.vehicle_roi = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]
    runtime = GuardRoomRuntime(config=cfg, state=None)

    inside = Detection(cls_id=cfg.classes.vehicle_car, conf=0.9, bbox=(180, 160, 240, 240), track_id=None)
    outside = Detection(cls_id=cfg.classes.vehicle_car, conf=0.9, bbox=(10, 10, 80, 80), track_id=None)

    assert runtime._filter_vehicles_by_roi([inside, outside], (400, 400, 3)) == [inside]
