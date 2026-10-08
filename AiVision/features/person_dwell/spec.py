"""声明 detect_human 人员逗留功能，绑定公共停留检测的具体消费者。

使用 yolo_human 推理，正式告警类型为 5。
"""
from AiVision.features._shared.spec import FeatureSpec
from .consumer import HumanConsumer
from .orm import HumanConfigORM
from .schema import HumanConfigSchema

SPEC = FeatureSpec(
    name="detect_human",
    display_name="人员违规逗留检测",
    consumer_cls=HumanConsumer,
    orm_class=HumanConfigORM,
    config_schema=HumanConfigSchema,
    required_models=("yolo_human",),
    alarm_types=(5,),
)
