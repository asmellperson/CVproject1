# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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
