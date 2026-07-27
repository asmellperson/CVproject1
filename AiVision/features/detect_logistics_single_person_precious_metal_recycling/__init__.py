"""features/detect_logistics_single_person_precious_metal_recycling/ — 贵金属回收物流通道单人检测"""
from features._base.spec import FeatureSpec

from .consumer import LogisticsSinglePersonPreciousMetalRecyclingConsumer
from .orm import LogisticsSinglePersonPreciousMetalRecyclingConfigORM
from .schema import LogisticsSinglePersonPreciousMetalRecyclingConfigSchema

SPEC = FeatureSpec(
    name="detect_logistics_single_person_precious_metal_recycling",
    display_name="物流通道单人检测（贵金属回收）",
    consumer_cls=LogisticsSinglePersonPreciousMetalRecyclingConsumer,
    orm_class=LogisticsSinglePersonPreciousMetalRecyclingConfigORM,
    config_schema=LogisticsSinglePersonPreciousMetalRecyclingConfigSchema,
    required_models=("yolo_human",),
    violation_type=9,
)
