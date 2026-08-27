"""皓达公司人员违规逗留检测：复用算法，独立保存摄像头与配置。"""

from features._base.spec import FeatureSpec
from features.detect_human.consumer import HumanConsumer
from features.detect_human.schema import HumanConfigSchema

from .orm import HaodaHumanConfigORM


SPEC = FeatureSpec(
    name="detect_human_haoda",
    display_name="人员违规逗留检测（皓达公司）",
    consumer_cls=HumanConsumer,
    orm_class=HaodaHumanConfigORM,
    config_schema=HumanConfigSchema,
    required_models=("yolo_human",),
    violation_type=10,
    departments=("haoda_company",),
)
