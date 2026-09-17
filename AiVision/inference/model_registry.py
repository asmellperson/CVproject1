"""固定模型注册配置；用户只配置本机权重路径。"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from AiVision.features._shared import defaults
from AiVision.features.face_recognition.library.constants import DEFAULT_DETECTION_THRESHOLD

from .workers.yolo_detector import YoloDetectorWorker
from .workers.face_recognizer import FaceRecognizerWorker
from .workers.face_detector import FaceDetectorWorker
from .workers.yolo_pose import YoloPoseWorker
from .workers.uniform_classifier import UniformClassifierWorker


@dataclass(frozen=True)
class ModelSpec:
    name: str
    worker_class: type
    type_label: str
    class_filter: tuple[int, ...] | None = None
    conf: float = 0.3
    iou: float = 0.5
    type: str = "yolo"
    class_labels: tuple[tuple[int, str], ...] = ()

# 固定模型注册表
MODEL_SPECS = MappingProxyType({
    spec.name: spec for spec in (
        ModelSpec("yolo_human", YoloDetectorWorker, "person", (0,)),
        ModelSpec("yolo_phone", YoloDetectorWorker, "phone", (1,)),
        ModelSpec("yolo_guard_person_phone", YoloDetectorWorker, "guard_object", (0, 1),
                  class_labels=((0, "person"), (1, "phone"))),
        ModelSpec("insightface_detection", FaceDetectorWorker, "face", conf=defaults.FACE_SCORE_THR,
                  iou=defaults.DETECTION_IOU_THR, type="insightface_detection"),
        ModelSpec("insightface", FaceRecognizerWorker, "face_identity", conf=DEFAULT_DETECTION_THRESHOLD, type="insightface"),
        ModelSpec("guard_uniform", UniformClassifierWorker, "uniform", type="timm_classifier"),
        ModelSpec("yolo_guard_pose", YoloPoseWorker, "pose", type="yolo_pose"),
        ModelSpec("yolo_vehicle", YoloDetectorWorker, "vehicle", (1, 2, 3)),
    )
})


def get_model_spec(name: str) -> ModelSpec:
    return MODEL_SPECS[name]
