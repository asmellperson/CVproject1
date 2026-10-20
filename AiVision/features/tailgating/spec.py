"""非法闯闸复用人体模型、摄像头配置和统一报警。"""
from AiVision.features._shared.spec import FeatureSpec
from .consumer import TailgatingConsumer
from .orm import TailgatingConfigORM
from .schema import ALARM_TYPE, FEATURE, TailgatingConfig

SPEC = FeatureSpec(
    name=FEATURE, display_name="非法闯闸检测", consumer_cls=TailgatingConsumer,
    orm_class=TailgatingConfigORM, config_schema=TailgatingConfig,
    required_models=("yolo_human",), alarm_types=(ALARM_TYPE,),
)
