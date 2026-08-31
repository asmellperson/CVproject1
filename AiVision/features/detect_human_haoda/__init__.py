# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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
