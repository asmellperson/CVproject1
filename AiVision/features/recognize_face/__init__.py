"""电子电工事业部的人脸身份识别能力。"""
from AiVision.features._base.spec import FeatureSpec
from .consumer import FaceRecognitionConsumer
from .orm import FaceRecognitionConfig
from .schema import FaceRecognitionConfigSchema

SPEC = FeatureSpec(
    name="recognize_face",
    display_name="人脸身份识别",
    consumer_cls=FaceRecognitionConsumer,
    orm_class=FaceRecognitionConfig,
    config_schema=FaceRecognitionConfigSchema,
    required_models=("insightface",),
    departments=("electronics_electrician",),
)
