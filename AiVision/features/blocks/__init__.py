# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/blocks/ — 区域入侵检测功能"""
from features._base.spec import FeatureSpec
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
    violation_type=1,
    departments=("research_institute",),
)
