"""人脸身份识别功能声明；业务标识保持 recognize_face。"""
from AiVision.features._shared.spec import FeatureSpec
from .consumer import FaceRecognitionConsumer
from .orm import FaceRecognitionConfig
from .schema import FaceRecognitionConfigSchema

SPEC = FeatureSpec(
    name="recognize_face",
    display_name="人脸身份识别",
    consumer_cls=FaceRecognitionConsumer,
    orm_class=FaceRecognitionConfig,
    config_schema=FaceRecognitionConfigSchema,
    alarm_types=(7,),
    required_models=("insightface",),
)
