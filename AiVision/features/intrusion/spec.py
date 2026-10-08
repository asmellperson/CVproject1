"""将区域入侵功能注册为 blocks，关联配置模型与 BlocksConsumer。

依赖 yolo_human 模型，正式告警类型为 1；目录名 intrusion 不作为配置键。
"""
from AiVision.features._shared.spec import FeatureSpec
from .consumer import BlocksConsumer
from .orm import BlocksConfigORM
from .schema import BlocksConfigSchema

SPEC = FeatureSpec(
    name="blocks",
    display_name="区域入侵检测",
    consumer_cls=BlocksConsumer,
    orm_class=BlocksConfigORM,
    config_schema=BlocksConfigSchema,
    required_models=("yolo_human",),
    alarm_types=(1,),
)
