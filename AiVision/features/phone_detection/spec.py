"""声明 detect_phone 手机使用检测功能及正式告警类型 3。

必需模型为 yolo_phone；消费者在人体模型可用时可进一步约束人体关联。
"""
from AiVision.features._shared.spec import FeatureSpec
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
    alarm_types=(3,),
)
