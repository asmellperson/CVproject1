"""电子电工事业部的人脸身份识别能力。

人员库 CLI 导入本包时尚未加载 .env；首次访问 SPEC 或公开类时才加载
Consumer、ORM 和 Schema，保持原有导出和唯一 SPEC 实例。
"""
from threading import RLock

from AiVision.features._base.spec import FeatureSpec

__all__ = ["FeatureSpec", "FaceRecognitionConsumer", "FaceRecognitionConfig", "FaceRecognitionConfigSchema", "SPEC"]
_SPEC_LOCK = RLock()


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    with _SPEC_LOCK:
        if "SPEC" not in globals():
            from .consumer import FaceRecognitionConsumer
            from .orm import FaceRecognitionConfig
            from .schema import FaceRecognitionConfigSchema

            spec = FeatureSpec(
                name="recognize_face",
                display_name="人脸身份识别",
                consumer_cls=FaceRecognitionConsumer,
                orm_class=FaceRecognitionConfig,
                config_schema=FaceRecognitionConfigSchema,
                required_models=("insightface",),
                departments=("electronics_electrician",),
            )
            globals().update(
                FaceRecognitionConsumer=FaceRecognitionConsumer,
                FaceRecognitionConfig=FaceRecognitionConfig,
                FaceRecognitionConfigSchema=FaceRecognitionConfigSchema,
                SPEC=spec,
            )
    return globals()[name]


def __dir__():
    return sorted(set(globals()) | set(__all__))
