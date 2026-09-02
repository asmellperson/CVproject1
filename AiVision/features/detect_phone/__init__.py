# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_phone/ — 手机检测"""
from AiVision.features._base.spec import FeatureSpec
from .consumer import PhoneConsumer
from .orm import PhoneConfigORM
from .schema import PhoneConfigSchema

SPEC = FeatureSpec(
    name="detect_phone",
    display_name="手机使用检测",
    consumer_cls=PhoneConsumer,
    orm_class=PhoneConfigORM,
    config_schema=PhoneConfigSchema,
    required_models=("yolo_phone",),
    violation_type=3,
    departments=("general_electric", "research_institute"),
)
