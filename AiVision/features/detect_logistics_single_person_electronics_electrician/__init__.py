# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_logistics_single_person_electronics_electrician/ — 电子电工物流通道单人检测"""
from AiVision.features._base.spec import FeatureSpec

from .consumer import LogisticsSinglePersonElectronicsElectricianConsumer
from .orm import LogisticsSinglePersonElectronicsElectricianConfigORM
from .schema import LogisticsSinglePersonElectronicsElectricianConfigSchema

SPEC = FeatureSpec(
    name="detect_logistics_single_person_electronics_electrician",
    display_name="物流通道单人检测（电子电工）",
    consumer_cls=LogisticsSinglePersonElectronicsElectricianConsumer,
    orm_class=LogisticsSinglePersonElectronicsElectricianConfigORM,
    config_schema=LogisticsSinglePersonElectronicsElectricianConfigSchema,
    required_models=("yolo_human",),
    violation_type=7,
)
