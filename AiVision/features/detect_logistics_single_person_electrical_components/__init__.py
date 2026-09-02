# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_logistics_single_person_electrical_components/ — 电气部件物流通道单人检测"""
from AiVision.features._base.spec import FeatureSpec

from .consumer import LogisticsSinglePersonElectricalComponentsConsumer
from .orm import LogisticsSinglePersonElectricalComponentsConfigORM
from .schema import LogisticsSinglePersonElectricalComponentsConfigSchema

SPEC = FeatureSpec(
    name="detect_logistics_single_person_electrical_components",
    display_name="物流通道单人检测（电气部件）",
    consumer_cls=LogisticsSinglePersonElectricalComponentsConsumer,
    orm_class=LogisticsSinglePersonElectricalComponentsConfigORM,
    config_schema=LogisticsSinglePersonElectricalComponentsConfigSchema,
    required_models=("yolo_human",),
    violation_type=8,
)
