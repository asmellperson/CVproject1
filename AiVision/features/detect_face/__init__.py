"""features/detect_face/ — 人脸逗留检测"""
from features._base.spec import FeatureSpec
from .consumer import FaceConsumer
from .orm import FaceConfigORM
from .schema import FaceConfigSchema

SPEC = FeatureSpec(
    name="detect_face",
    display_name="人脸检测",
    consumer_cls=FaceConsumer,
    orm_class=FaceConfigORM,
    config_schema=FaceConfigSchema,
    required_models=("yolo_face",),
    violation_type=4,
)
