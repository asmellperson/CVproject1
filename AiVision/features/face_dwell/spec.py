"""features/face_dwell/ — 人脸逗留检测"""
from AiVision.features._shared.spec import FeatureSpec
from .consumer import FaceConsumer
from .orm import FaceConfigORM
from .schema import FaceConfigSchema

SPEC = FeatureSpec(
    name="detect_face",
    display_name="人脸逗留检测",
    consumer_cls=FaceConsumer,
    orm_class=FaceConfigORM,
    config_schema=FaceConfigSchema,
    required_models=("insightface_detection",),
    alarm_types=(4,),
)
