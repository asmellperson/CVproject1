"""features/intrusion/ — 区域入侵检测功能"""
from AiVision.features._shared.spec import FeatureSpec
from .consumer import BlocksConsumer
from .orm import BlocksConfigORM
from .schema import BlocksConfigSchema

SPEC = FeatureSpec(
    name="blocks",
    display_name="区域入侵检测",
    consumer_cls=BlocksConsumer,
    orm_class=BlocksConfigORM,
    config_schema=BlocksConfigSchema,
    required_models=("yolo_human",),
    alarm_types=(1,),
)
