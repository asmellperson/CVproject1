"""注册 AGV 请求触发型检测功能。"""
from AiVision.features._shared.spec import FeatureSpec

from .consumer import AgvPersonCheckConsumer
from .orm import AgvPersonCheckConfigORM
from .schema import AgvPersonCheckConfigSchema

SPEC = FeatureSpec(
    name="agv_person_check",
    display_name="AGV无人运货检测",
    consumer_cls=AgvPersonCheckConsumer,
    orm_class=AgvPersonCheckConfigORM,
    config_schema=AgvPersonCheckConfigSchema,
    required_models=("yolo_human",),
)
