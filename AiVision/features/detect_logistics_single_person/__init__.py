# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_logistics_single_person/ — 物流通道单人检测"""
from AiVision.features._base.spec import FeatureSpec

from .consumer import LogisticsSinglePersonConsumer
from .orm import LogisticsSinglePersonConfigORM
from .schema import LogisticsSinglePersonConfigSchema

SPEC = FeatureSpec(
    name="detect_logistics_single_person",
    display_name="物流通道单人检测",
    consumer_cls=LogisticsSinglePersonConsumer,
    orm_class=LogisticsSinglePersonConfigORM,
    config_schema=LogisticsSinglePersonConfigSchema,
    required_models=("yolo_human",),
    violation_type=6,
)
