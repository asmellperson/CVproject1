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
