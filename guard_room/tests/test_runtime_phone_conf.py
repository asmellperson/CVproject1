import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import AppConfig, ClassConfig, ModelConfig, RoomConfig, RuleConfig, RuntimeConfig, VideoConfig, WeChatConfig
from src.runtime import GuardRoomRuntime
from src.state import AppState
from src.types import Detection


class _Boxes:
    xyxy = None
    conf = None


class _Result:
    boxes = _Boxes()


class FakeDetector:
    def __init__(self):
        self.conf = None

    def predict(self, **kwargs):
        self.conf = kwargs["conf"]
        return [_Result()]


def test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf():
    cfg = AppConfig(
        video=VideoConfig(source="rtsp://camera"),
        models=ModelConfig(
            detector_model="models/person_phone.pt",
            detector_conf=0.5,
            phone_conf=0.35,
            device="cpu",
        ),
        room=RoomConfig(),
        rules=RuleConfig(),
        classes=ClassConfig(play_phone=1),
        runtime=RuntimeConfig(),
        wechat=WeChatConfig(enable=False),
    )
    runtime = GuardRoomRuntime(cfg, AppState(cfg, config_path="test.yaml"))
    detector = FakeDetector()

    runtime._detect_phones_in_person_regions(
        detector,
        np.zeros((120, 120, 3), dtype=np.uint8),
        [Detection(cls_id=0, conf=0.9, bbox=(30, 20, 70, 100), track_id=1)],
    )

    assert detector.conf == 0.35
