"""features/detect_logistics_single_person_electrical_components/ — 电气部件物流通道单人检测"""
from features._base.spec import FeatureSpec

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
