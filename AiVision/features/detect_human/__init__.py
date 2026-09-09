"""features/detect_human/ — 人员违规逗留检测"""
from AiVision.features._base.spec import FeatureSpec
from .consumer import HumanConsumer
from .orm import HumanConfigORM
from .schema import HumanConfigSchema

SPEC = FeatureSpec(
    name="detect_human",
    display_name="人员违规逗留检测",
    consumer_cls=HumanConsumer,
    orm_class=HumanConfigORM,
    config_schema=HumanConfigSchema,
    required_models=("yolo_human",),
    violation_type=5,
    departments=("general_electric",),
)
