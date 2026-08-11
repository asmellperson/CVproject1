import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import (
    AppConfig,
    ClassConfig,
    ModelConfig,
    RoomConfig,
    RuleConfig,
    RuntimeConfig,
    VideoConfig,
    WeChatConfig,
)
from src.state import AppState
from src.types import Detection


def _config() -> AppConfig:
    return AppConfig(
        video=VideoConfig(source="rtsp://camera"),
        models=ModelConfig(detector_model="models/test.pt"),
        room=RoomConfig(),
        rules=RuleConfig(),
        classes=ClassConfig(),
        runtime=RuntimeConfig(),
        wechat=WeChatConfig(enable=False),
    )


def test_status_reports_guards_separately_from_all_detected_people():
    state = AppState(_config(), config_path="test.yaml")
    visitor = Detection(cls_id=0, conf=0.91, bbox=(0, 0, 20, 40), track_id=1)
    guard = Detection(cls_id=0, conf=0.87, bbox=(30, 0, 50, 40), track_id=2)

    state.update_frame(
        np.zeros((64, 64, 3), dtype=np.uint8),
        frame_count=1,
        fps=6.5,
        timestamp_s=1.0,
        persons=[visitor, guard],
        guards=[guard],
        guard_confidence=0.93,
        phones=[],
        pose_features={},
        decisions={
            "absent": SimpleNamespace(active=False),
            "phone": SimpleNamespace(active=False),
            "prone_sleep": SimpleNamespace(active=False),
            "vehicle_unattended": SimpleNamespace(active=False),
        },
        pose_enabled=False,
    )

    status = state.get_status()
    assert status["counts"]["persons"] == 2
    assert status["counts"]["guards"] == 1
    assert len(status["persons"]) == 2
    assert len(status["guards"]) == 1
    assert status["metrics"]["guard_confidence"] == 0.93
