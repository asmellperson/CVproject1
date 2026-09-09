"""features/detect_door/ — 门禁状态检测"""
from AiVision.features._base.spec import FeatureSpec
from .consumer import DoorConsumer
from .orm import DoorConfigORM
from .schema import DoorConfigSchema

SPEC = FeatureSpec(
    name="detect_door",
    display_name="大门开关检测",
    consumer_cls=DoorConsumer,
    orm_class=DoorConfigORM,
    config_schema=DoorConfigSchema,
    required_models=(),
    violation_type=2,
    departments=("general_electric",),
)
