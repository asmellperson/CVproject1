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
    departments=(
        "general_electric",
        "electronics_electrician",
        "electrical_components",
        "precious_metal_recycling",
    ),
)
