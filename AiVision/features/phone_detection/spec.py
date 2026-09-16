"""features/phone_detection/ — 手机检测"""
from AiVision.features._shared.spec import FeatureSpec
from .consumer import PhoneConsumer
from .orm import PhoneConfigORM
from .schema import PhoneConfigSchema

SPEC = FeatureSpec(
    name="detect_phone",
    display_name="手机使用检测",
    consumer_cls=PhoneConsumer,
    orm_class=PhoneConfigORM,
    config_schema=PhoneConfigSchema,
    required_models=("yolo_phone",),
    violation_type=3,
)
