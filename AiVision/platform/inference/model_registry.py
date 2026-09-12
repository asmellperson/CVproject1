"""固定模型注册配置；用户只配置本机权重路径。"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from AiVision.platform.face_library.constants import DEFAULT_DETECTION_THRESHOLD

from .workers.yolo_detector import YoloDetectorWorker
from .workers.face_recognizer import FaceRecognizerWorker


@dataclass(frozen=True)
class ModelSpec:
    name: str
    worker_class: type
    type_label: str
    class_filter: tuple[int, ...] | None = None
    conf: float = 0.3
    iou: float = 0.5
    type: str = "yolo"

# 固定模型注册表
MODEL_SPECS = MappingProxyType({
    spec.name: spec for spec in (
        ModelSpec("yolo_human", YoloDetectorWorker, "person", (0,)),
        ModelSpec("yolo_phone", YoloDetectorWorker, "phone", (1,)),
        ModelSpec("yolo_face", YoloDetectorWorker, "face", conf=0.6),
        ModelSpec("insightface", FaceRecognizerWorker, "face_identity", conf=DEFAULT_DETECTION_THRESHOLD, type="insightface"),
    )
})


def get_model_spec(name: str) -> ModelSpec:
    return MODEL_SPECS[name]
