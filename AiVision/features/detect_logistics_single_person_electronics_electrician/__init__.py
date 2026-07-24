"""features/detect_logistics_single_person_electronics_electrician/ — 电子电工物流通道单人检测"""
from features._base.spec import FeatureSpec

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
