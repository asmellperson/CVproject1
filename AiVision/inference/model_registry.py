"""固定逻辑模型目录，把业务名称映射到 Worker、类别和默认推理参数。

MODEL_SPECS 是只读注册表，物理权重路径另由 model_paths.py 管理。
Consumer 使用逻辑模型名投递任务；运行管理器据此选择 Worker 和共享权重分组。
修改类别 ID 时必须核对实际权重类别，增加注册项不会自动创建检测业务。
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from AiVision.features._shared import defaults
from AiVision.features.face_recognition.library.constants import DEFAULT_DETECTION_THRESHOLD, DEFAULT_NMS_THRESHOLD

from .workers.yolo_detector import YoloDetectorWorker
from .workers.face_recognizer import FaceRecognizerWorker
from .workers.face_detector import FaceDetectorWorker
from .workers.yolo_pose import YoloPoseWorker
from .workers.uniform_classifier import UniformClassifierWorker


@dataclass(frozen=True)
class ModelSpec:
    """一个逻辑模型的不可变定义。

    name 是队列和业务依赖使用的标识；worker_class 决定推理实现。
    class_filter=None 表示不过滤类别，class_labels 可按类别覆盖 type_label。
    conf/iou/imgsz 是任务未显式提供时的默认值；type 用于权重路径和模型类型校验。
    """
    name: str
    worker_class: type
    type_label: str
    class_filter: tuple[int, ...] | None = None
    conf: float = 0.3
    iou: float = 0.5
    type: str = "yolo"
    class_labels: tuple[tuple[int, str], ...] = ()
    imgsz: int = 640

# 固定模型注册表
MODEL_SPECS = MappingProxyType({
    spec.name: spec for spec in (
        ModelSpec("yolo_human", YoloDetectorWorker, "person", (0,)),
        ModelSpec("yolo_phone", YoloDetectorWorker, "phone", (1,)),
        ModelSpec("yolo_guard_person_phone", YoloDetectorWorker, "guard_object", (0, 1),
                  class_labels=((0, "person"), (1, "phone"))),
        ModelSpec("insightface_detection", FaceDetectorWorker, "face", conf=defaults.FACE_SCORE_THR,
                  iou=defaults.FACE_DETECTION_IOU_THR, type="insightface_detection"),
        ModelSpec("insightface", FaceRecognizerWorker, "face_identity", conf=DEFAULT_DETECTION_THRESHOLD,
                  iou=DEFAULT_NMS_THRESHOLD, type="insightface"),
        ModelSpec("guard_uniform", UniformClassifierWorker, "uniform", type="timm_classifier"),
        ModelSpec("yolo_guard_pose", YoloPoseWorker, "pose", type="yolo_pose"),
        ModelSpec("yolo_vehicle", YoloDetectorWorker, "vehicle", (2,)),
    )
})


def get_model_spec(name: str) -> ModelSpec:
    """按逻辑模型名返回固定定义，未注册名称抛出 KeyError。"""
    return MODEL_SPECS[name]
