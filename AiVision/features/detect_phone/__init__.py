"""features/detect_phone/ — 手机检测"""
from features._base.spec import FeatureSpec
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
    departments=("general_electric", "research_institute"),
)
