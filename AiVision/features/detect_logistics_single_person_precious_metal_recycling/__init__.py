# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""伟达公司物流通道单人检测（保留原内部 feature 标识）。"""
from AiVision.features._base.spec import FeatureSpec

from .consumer import LogisticsSinglePersonPreciousMetalRecyclingConsumer
from .orm import LogisticsSinglePersonPreciousMetalRecyclingConfigORM
from .schema import LogisticsSinglePersonPreciousMetalRecyclingConfigSchema

SPEC = FeatureSpec(
    name="detect_logistics_single_person_precious_metal_recycling",
    display_name="物流通道单人检测（伟达公司）",
    consumer_cls=LogisticsSinglePersonPreciousMetalRecyclingConsumer,
    orm_class=LogisticsSinglePersonPreciousMetalRecyclingConfigORM,
    config_schema=LogisticsSinglePersonPreciousMetalRecyclingConfigSchema,
    required_models=("yolo_human",),
    violation_type=9,
)
