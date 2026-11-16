"""注册摄像头烟雾报警功能，不依赖模型推理。"""
from AiVision.features._shared.spec import FeatureSpec

from .consumer import SmokeConsumer
from .orm import SmokeConfigORM
from .schema import SmokeConfigSchema


SPEC = FeatureSpec(
    name="smoke_detection",
    display_name="烟雾检测",
    consumer_cls=SmokeConsumer,
    orm_class=SmokeConfigORM,
    config_schema=SmokeConfigSchema,
    required_models=(),
    alarm_types=(18,),
)
